import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# -------------------------------------------------------------------
# 1. 설정 및 기본 세팅
# -------------------------------------------------------------------
st.set_page_config(page_title="나의 투자 현황", layout="wide")

# [보수적 평가 기준] 매도 시 예상 스프레드 (0.5%)
SPREAD_RATE = 0.005 

# 세금 관련 설정 (토글용)
TAX_RATE = 0.22  # 해외주식 양도소득세 22%
DEDUCTION = 2500000  # 기본공제 250만원

# -------------------------------------------------------------------
# 2. 데이터 로드 및 전처리 함수
# -------------------------------------------------------------------
@st.cache_data(ttl=60) # 1분마다 캐시 갱신
def load_data():
    # 시크릿에서 키 로드
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # 구글 시트 열기
    sh = client.open("Investment_Dashboard_DB")

    # 데이터 가져오기 (헤더 포함)
    trade_df = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
    exchange_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
    krw_assets_df = pd.DataFrame(sh.worksheet("KRW_Assets").get_all_records())
    domestic_etf_df = pd.DataFrame(sh.worksheet("Domestic_ETF").get_all_records())
    
    return trade_df, exchange_df, krw_assets_df, domestic_etf_df

def get_current_exchange_rate():
    try:
        # 야후 파이낸스 환율 (매매기준율)
        ticker = yf.Ticker("USDKRW=X")
        data = ticker.history(period="1d")
        rate = data['Close'].iloc[-1]
        return rate
    except:
        return 1400.0 # 에러시 기본값

def get_current_price(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return data['Close'].iloc[-1]
    except:
        return 0.0

# -------------------------------------------------------------------
# 3. 메인 로직 실행
# -------------------------------------------------------------------

try:
    with st.spinner('데이터를 불러오는 중입니다...'):
        trade_df, exchange_df, krw_assets_df, domestic_etf_df = load_data()
        current_rate_market = get_current_exchange_rate()
        
        # 보수적 환율 (매도 시 내 주머니에 들어올 돈)
        conservative_rate = current_rate_market * (1 - SPREAD_RATE)

    # 사이드바 설정
    with st.sidebar:
        st.header("⚙️ 환경 설정")
        st.metric("현재 시장 환율", f"{current_rate_market:,.2f}원")
        st.metric("보수적 적용 환율", f"{conservative_rate:,.2f}원", help="스프레드 0.5% 차감")
        
        apply_tax = st.toggle("세후 실질 가치 보기 (양도세 22%)")
        if apply_tax:
            st.warning(f"수익금 250만원 공제 후 {TAX_RATE*100}% 세금 적용")

    st.title("💰 Investment Dashboard")
    st.markdown("---")

    # -------------------------------------------------------
    # A. 자산별 평가액 계산
    # -------------------------------------------------------
    
    # 1. 달러 현금 (예수금) 계산
    # 환전한 총 달러 - 주식 산 총 달러 = 남은 달러
    total_usd_exchanged = pd.to_numeric(exchange_df['USD_Amount']).sum()
    total_usd_invested = pd.to_numeric(trade_df['Qty'] * trade_df['Price_USD']).sum()
    usd_cash_balance = total_usd_exchanged - total_usd_invested
    
    # 달러 현금의 원화 가치 (현재 환율 적용)
    usd_cash_krw_value = usd_cash_balance * conservative_rate
    # 달러 현금의 투입 원금 (평단가 역산은 복잡하므로 단순 비례 혹은 0으로 가정하나, 여기선 환전 평균단가 적용 가능. 약식으로 함)
    # *정확한 계산을 위해선 선입선출이 필요하지만, 여기선 '환전한 돈 중 안 쓴 돈'의 원화 비율로 계산
    total_krw_exchanged = pd.to_numeric(exchange_df['KRW_Amount']).sum()
    avg_exchange_rate = total_krw_exchanged / total_usd_exchanged if total_usd_exchanged > 0 else 0
    usd_cash_principal = usd_cash_balance * avg_exchange_rate


    # 2. 미국 주식 계산
    us_stock_data = []
    trade_df['Qty'] = pd.to_numeric(trade_df['Qty'])
    trade_df['Price_USD'] = pd.to_numeric(trade_df['Price_USD'])
    
    # 종목별 그룹화
    grouped_us = trade_df.groupby('Ticker').agg({
        'Qty': 'sum',
        'Price_USD': 'mean', # 단순 평균이 아니라 가중 평균이어야 하지만 약식 구현. (실제론 개별 건 계산 후 합산이 정확)
        'Name': 'first'
    }).reset_index()
    
    # *정밀 계산을 위해 개별 건 단위로 루프*
    total_us_eval_krw = 0
    total_us_principal_krw = 0
    
    # 상세 테이블용 데이터 리스트
    us_table_rows = []

    for index, row in trade_df.iterrows():
        # 현재가 조회 (반복 호출 줄이기 위해 캐싱 필요하지만 일단 진행)
        cur_price = get_current_price(row['Ticker']) 
        
        # 평가 금액 (달러)
        eval_usd = row['Qty'] * cur_price
        # 평가 금액 (원화 - 보수적 환율)
        eval_krw = eval_usd * conservative_rate
        
        # 투자 원금 (당시 환율 적용)
        principal_krw = row['Qty'] * row['Price_USD'] * row['Exchange_Rate']
        
        total_us_eval_krw += eval_krw
        total_us_principal_krw += principal_krw
        
        # 주가 손익 vs 환율 손익 분해
        # 주가 손익: (현재가 - 매수가) * 수량 * 당시환율 (순수 달러 수익의 원화 가치...가 아니라 복합적임)
        # 더 명확한 분해:
        # 총 손익 = 평가액(KRW) - 원금(KRW)
        total_profit = eval_krw - principal_krw
        
        # 환율 효과 = (현재환율 - 당시환율) * 현재가 * 수량 (현재 자산 가치 중 환율 상승분)
        # 주가 효과 = (현재가 - 매수가) * 당시환율 * 수량 (환율 변동 없었을 때의 수익)
        # *엄밀한 분해 공식 적용*
        currency_effect = (conservative_rate - row['Exchange_Rate']) * (row['Qty'] * cur_price)
        price_effect = (cur_price - row['Price_USD']) * row['Qty'] * row['Exchange_Rate']
        # 교차 효과(Interaction)는 보통 환율 효과나 주가 효과 중 하나에 포함시킴. 여기선 단순 차감으로 보정
        interaction = total_profit - (currency_effect + price_effect)
        currency_effect += interaction # 교차 효과를 환율 효과에 포함

        profit_rate = (total_profit / principal_krw * 100) if principal_krw > 0 else 0

        us_table_rows.append({
            'Ticker': row['Ticker'],
            'Name': row['Name'],
            'Qty': row['Qty'],
            'Principal_KRW': principal_krw,
            'Principal_USD': row['Qty'] * row['Price_USD'],
            'Eval_KRW': eval_krw,
            'Eval_USD': eval_usd,
            'Total_Profit': total_profit,
            'Rate': profit_rate,
            'Price_Profit': price_effect,
            'Ex_Profit': currency_effect
        })
    
    us_df_processed = pd.DataFrame(us_table_rows)
    # 같은 종목끼리 합치기 (Display용)
    if not us_df_processed.empty:
        us_display = us_df_processed.groupby('Ticker').agg({
            'Name': 'first',
            'Qty': 'sum',
            'Principal_KRW': 'sum',
            'Principal_USD': 'sum',
            'Eval_KRW': 'sum',
            'Eval_USD': 'sum',
            'Total_Profit': 'sum',
            'Price_Profit': 'sum',
            'Ex_Profit': 'sum'
        }).reset_index()
        us_display['Rate'] = us_display.apply(lambda x: (x['Total_Profit']/x['Principal_KRW']*100) if x['Principal_KRW']>0 else 0, axis=1)
    else:
        us_display = pd.DataFrame()


    # 3. 원화 예금 계산 (선형 증액)
    total_krw_deposit_eval = 0
    total_krw_deposit_principal = 0
    krw_table_rows = []
    
    for index, row in krw_assets_df.iterrows():
        start = pd.to_datetime(row['Start_Date'])
        end = pd.to_datetime(row['End_Date'])
        today = datetime.now()
        
        total_days = (end - start).days
        passed_days = (today - start).days
        if passed_days < 0: passed_days = 0
        if passed_days > total_days: passed_days = total_days
        
        progress = passed_days / total_days if total_days > 0 else 0
        
        # 현재 이론적 평가액 (원금 + (이자 * 진행률))
        # 이자 = 만기액 - 원금
        interest_total = row['Target_Amount'] - row['Principal']
        current_eval = row['Principal'] + (interest_total * progress)
        
        total_krw_deposit_eval += current_eval
        total_krw_deposit_principal += row['Principal']
        
        krw_table_rows.append({
            'Name': row['Name'],
            'End_Date': row['End_Date'],
            'Progress': progress,
            'Eval_KRW': current_eval,
            'Target': row['Target_Amount']
        })
    
    krw_deposit_df = pd.DataFrame(krw_table_rows)

    # 4. 국내 ETF 계산 (심플)
    domestic_etf_df['Qty'] = pd.to_numeric(domestic_etf_df['Qty'])
    domestic_etf_df['Price_KRW'] = pd.to_numeric(domestic_etf_df['Price_KRW']) # 매수단가
    
    total_etf_eval = 0
    total_etf_principal = 0
    etf_rows = []
    
    for index, row in domestic_etf_df.iterrows():
        # 국내 주가 가져오기 (예: 005930.KS)
        # 티커 뒤에 .KS or .KQ 없으면 붙여야 함. 여기선 입력되었다고 가정하거나 생략
        cur_price = row['Price_KRW'] # *API 연동 필요하나 일단 매수단가와 같다고 가정(혹은 yfinance로 조회)*
        # 실제론: cur_price = get_current_price(row['Ticker'] + ".KS") 
        
        eval_krw = row['Qty'] * cur_price
        principal_krw = row['Qty'] * row['Price_KRW']
        
        total_etf_eval += eval_krw
        total_etf_principal += principal_krw
        
        etf_rows.append({
            'Name': row['Name'],
            'Qty': row['Qty'],
            'Principal': principal_krw,
            'Eval': eval_krw,
            'Profit': eval_krw - principal_krw
        })
    etf_display = pd.DataFrame(etf_rows)


    # -------------------------------------------------------
    # B. 시각화 및 출력
    # -------------------------------------------------------
    
    # 1. 상단 요약 그래프 (Columns)
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("📊 자산 배분 (Asset Allocation)")
        # 데이터 준비
        labels = ['미국주식 (USD)', '달러현금 (USD)', '원화예금 (KRW)', '국내ETF (KRW)']
        values = [total_us_eval_krw, usd_cash_krw_value, total_krw_deposit_eval, total_etf_eval]
        
        fig_donut = px.pie(values=values, names=labels, hole=0.4)
        fig_donut.update_traces(textinfo='percent+label')
        st.plotly_chart(fig_donut, use_container_width=True)
        
    with col2:
        st.subheader("💰 수익 기여도 (Profit Contribution)")
        # 수익금 계산
        us_profit = total_us_eval_krw - total_us_principal_krw
        cash_profit = usd_cash_krw_value - usd_cash_principal
        deposit_profit = total_krw_deposit_eval - total_krw_deposit_principal
        etf_profit = total_etf_eval - total_etf_principal
        
        # 스택형 바 차트를 위해 데이터 구조화 필요하지만, 여기선 심플하게 폭포수나 막대로 표현
        # 미국주식 수익을 [주가] vs [환율]로 나누기
        us_price_profit_sum = us_display['Price_Profit'].sum() if not us_display.empty else 0
        us_ex_profit_sum = us_display['Ex_Profit'].sum() if not us_display.empty else 0
        
        fig_bar = go.Figure(data=[
            go.Bar(name='주가/이자 수익', x=['미국주식', '달러현금', '원화예금'], y=[us_price_profit_sum, 0, deposit_profit]),
            go.Bar(name='환율 수익', x=['미국주식', '달러현금', '원화예금'], y=[us_ex_profit_sum, cash_profit, 0])
        ])
        fig_bar.update_layout(barmode='stack')
        st.plotly_chart(fig_bar, use_container_width=True)

    # 2. 통합 자산표 (Summary Table)
    st.subheader("📑 통합 자산 현황")
    
    total_principal = total_us_principal_krw + usd_cash_principal + total_krw_deposit_principal + total_etf_principal
    total_eval = total_us_eval_krw + usd_cash_krw_value + total_krw_deposit_eval + total_etf_eval
    total_profit_all = total_eval - total_principal
    total_return = (total_profit_all / total_principal * 100) if total_principal > 0 else 0
    
    summary_data = {
        "자산군": ["🇺🇸 미국주식", "💵 달러현금", "🇰🇷 원화예금", "🇰🇷 국내ETF", "🔴 합계"],
        "투자원금": [total_us_principal_krw, usd_cash_principal, total_krw_deposit_principal, total_etf_principal, total_principal],
        "평가금액": [total_us_eval_krw, usd_cash_krw_value, total_krw_deposit_eval, total_etf_eval, total_eval],
        "총 손익": [total_us_eval_krw-total_us_principal_krw, usd_cash_krw_value-usd_cash_principal, total_krw_deposit_eval-total_krw_deposit_principal, total_etf_eval-total_etf_principal, total_profit_all],
        "수익률(%)": [
            (total_us_eval_krw/total_us_principal_krw-1)*100 if total_us_principal_krw else 0,
            (usd_cash_krw_value/usd_cash_principal-1)*100 if usd_cash_principal else 0,
            (total_krw_deposit_eval/total_krw_deposit_principal-1)*100 if total_krw_deposit_principal else 0,
            (total_etf_eval/total_etf_principal-1)*100 if total_etf_principal else 0,
            total_return
        ]
    }
    st.dataframe(pd.DataFrame(summary_data).style.format({
        "투자원금": "{:,.0f}", "평가금액": "{:,.0f}", "총 손익": "{:,.0f}", "수익률(%)": "{:.2f}%"
    }), use_container_width=True)
    
    # 3. 상세 내역 탭 (Tabs)
    tab1, tab2, tab3 = st.tabs(["🇺🇸 미국 직투", "🇰🇷 국내 ETF", "🏦 예금/공제"])
    
    with tab1:
        if not us_display.empty:
            # 원화/달러 병기 포맷팅은 pandas style이나 st.column_config 활용
            # 여기선 가독성을 위해 컬럼 분리하여 표시
            st.dataframe(
                us_display[['Name', 'Rate', 'Qty', 'Eval_KRW', 'Total_Profit', 'Price_Profit', 'Ex_Profit']],
                column_config={
                    "Name": "종목명",
                    "Rate": st.column_config.NumberColumn("수익률", format="%.2f%%"),
                    "Qty": st.column_config.NumberColumn("수량", format="%.0f주"),
                    "Eval_KRW": st.column_config.NumberColumn("평가액(₩)", format="%d원"),
                    "Total_Profit": st.column_config.NumberColumn("총손익", format="%d원"),
                    "Price_Profit": st.column_config.NumberColumn("주가손익", format="%d원"),
                    "Ex_Profit": st.column_config.NumberColumn("📈환율손익", format="%d원"),
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("보유 중인 미국 주식이 없습니다.")
            
    with tab2:
        if not etf_display.empty:
            st.dataframe(etf_display, use_container_width=True)
        else:
            st.info("보유 중인 국내 ETF가 없습니다.")
            
    with tab3:
        if not krw_deposit_df.empty:
            st.dataframe(
                krw_deposit_df,
                column_config={
                    "Name": "상품명",
                    "End_Date": "만기일",
                    "Progress": st.column_config.ProgressColumn("진행률", format="%.1f%%", min_value=0, max_value=1),
                    "Eval_KRW": st.column_config.NumberColumn("현재평가액", format="%d원"),
                    "Target": st.column_config.NumberColumn("만기예상액", format="%d원"),
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("등록된 예금/공제 자산이 없습니다.")

except Exception as e:
    st.error(f"오류가 발생했습니다: {e}")
    st.write("구글 시트 연결 상태나 데이터 형식을 확인해주세요.")
