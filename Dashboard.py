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

# [세금 설정]
# 1. 미국 주식 (양도소득세)
US_TAX_RATE = 0.22      # 22%
US_DEDUCTION = 2500000  # 기본공제 250만원

# 2. 국내 ETF (ISA 계좌 기준 - 일반형 가정)
ISA_LIMIT = 2000000     # 비과세 한도 200만원
ISA_TAX_RATE = 0.099    # 초과분 9.9% 과세

# -------------------------------------------------------------------
# 2. 데이터 로드 및 전처리 함수
# -------------------------------------------------------------------
def clean_currency(series):
    """ 콤마(,)가 섞인 문자/숫자를 강제로 깨끗한 실수(float)로 변환 """
    return pd.to_numeric(series.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

@st.cache_data(ttl=60)
def load_data():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")

        trade_df = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        exchange_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        krw_assets_df = pd.DataFrame(sh.worksheet("KRW_Assets").get_all_records())
        domestic_etf_df = pd.DataFrame(sh.worksheet("Domestic_ETF").get_all_records())
        
        return trade_df, exchange_df, krw_assets_df, domestic_etf_df
    except Exception as e:
        st.error(f"구글 시트 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_current_exchange_rate():
    try:
        ticker = yf.Ticker("USDKRW=X")
        data = ticker.history(period="1d")
        if not data.empty:
            return data['Close'].iloc[-1]
        # [비상용 값] API 에러 시에만 사용됨 (정상 작동 시 무시됨)
        return 1450.0 
    except:
        return 1450.0

def get_current_price(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1d")
        if not data.empty:
            return data['Close'].iloc[-1]
        return 0.0
    except:
        return 0.0

# -------------------------------------------------------------------
# 3. 메인 로직 실행
# -------------------------------------------------------------------

try:
    with st.spinner('데이터를 불러오는 중입니다...'):
        trade_df, exchange_df, krw_assets_df, domestic_etf_df = load_data()
        
        # 콤마 제거 및 숫자 변환 (전처리)
        if not exchange_df.empty:
            exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
            exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
        
        if not trade_df.empty:
            trade_df['Qty'] = clean_currency(trade_df['Qty'])
            trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
            trade_df['Exchange_Rate'] = clean_currency(trade_df['Exchange_Rate'])
            
        if not krw_assets_df.empty:
            krw_assets_df['Principal'] = clean_currency(krw_assets_df['Principal'])
            krw_assets_df['Target_Amount'] = clean_currency(krw_assets_df['Target_Amount'])

        if not domestic_etf_df.empty:
            domestic_etf_df['Qty'] = clean_currency(domestic_etf_df['Qty'])
            domestic_etf_df['Price_KRW'] = clean_currency(domestic_etf_df['Price_KRW'])

        # 환율 가져오기 (스프레드 제거됨: 시장 환율 그대로 사용)
        current_rate = get_current_exchange_rate()

    # 사이드바 설정
    with st.sidebar:
        st.header("⚙️ 환경 설정")
        st.metric("현재 시장 환율", f"{current_rate:,.2f}원")
        
        apply_tax = st.toggle("세후 실질 가치 보기 (Tax Cut)")
        if apply_tax:
            st.info(f"""
            **[세금 적용 기준]**
            🇺🇸 미국주식: 250만원 공제 후 22%
            🇰🇷 국내ETF(ISA): 200만원 비과세 후 9.9%
            """)

    st.title("💰 Investment Dashboard")
    st.markdown("---")

    # -------------------------------------------------------
    # A. 자산별 평가액 계산
    # -------------------------------------------------------
    
    # 1. 달러 현금 (예수금)
    total_usd_exchanged = exchange_df['USD_Amount'].sum() if not exchange_df.empty else 0
    total_usd_invested = (trade_df['Qty'] * trade_df['Price_USD']).sum() if not trade_df.empty else 0
    usd_cash_balance = total_usd_exchanged - total_usd_invested
    
    # 원화 환산 (현재 환율 적용)
    usd_cash_krw_value = usd_cash_balance * current_rate
    
    # 달러 현금의 원금 (평균 환전 단가 적용)
    total_krw_exchanged = exchange_df['KRW_Amount'].sum() if not exchange_df.empty else 0
    avg_exchange_rate = total_krw_exchanged / total_usd_exchanged if total_usd_exchanged > 0 else 0
    usd_cash_principal = usd_cash_balance * avg_exchange_rate


    # 2. 미국 주식 계산
    total_us_eval_krw = 0
    total_us_principal_krw = 0
    us_table_rows = []
    us_display = pd.DataFrame()

    if not trade_df.empty:
        progress_text = "미국 주식 현재가 조회 중..."
        my_bar = st.progress(0, text=progress_text)
        total_rows = len(trade_df)

        for index, row in trade_df.iterrows():
            cur_price = get_current_price(row['Ticker']) 
            
            # 평가금액 (스프레드 없이 계산)
            eval_usd = row['Qty'] * cur_price
            eval_krw = eval_usd * current_rate
            principal_krw = row['Qty'] * row['Price_USD'] * row['Exchange_Rate']
            
            total_us_eval_krw += eval_krw
            total_us_principal_krw += principal_krw
            
            # 손익 분해
            total_profit = eval_krw - principal_krw
            currency_effect = (current_rate - row['Exchange_Rate']) * (row['Qty'] * cur_price)
            price_effect = (cur_price - row['Price_USD']) * row['Qty'] * row['Exchange_Rate']
            interaction = total_profit - (currency_effect + price_effect)
            currency_effect += interaction 

            profit_rate = (total_profit / principal_krw * 100) if principal_krw > 0 else 0

            us_table_rows.append({
                'Ticker': row['Ticker'],
                'Name': row['Name'],
                'Qty': row['Qty'],
                'Principal_KRW': principal_krw,
                'Principal_USD': row['Qty'] * row['Price_USD'],
                'Eval_KRW': eval_krw,
                'Total_Profit': total_profit,
                'Rate': profit_rate,
                'Price_Profit': price_effect,
                'Ex_Profit': currency_effect
            })
            my_bar.progress((index + 1) / total_rows, text=f"현재가 조회 중: {row['Ticker']}")
        
        my_bar.empty()
        
        us_df_processed = pd.DataFrame(us_table_rows)
        if not us_df_processed.empty:
            us_display = us_df_processed.groupby('Ticker').agg({
                'Name': 'first',
                'Qty': 'sum',
                'Principal_KRW': 'sum',
                'Principal_USD': 'sum',
                'Eval_KRW': 'sum',
                'Total_Profit': 'sum',
                'Price_Profit': 'sum',
                'Ex_Profit': 'sum'
            }).reset_index()
            us_display['Rate'] = us_display.apply(lambda x: (x['Total_Profit']/x['Principal_KRW']*100) if x['Principal_KRW']>0 else 0, axis=1)


    # 3. 원화 예금 계산
    total_krw_deposit_eval = 0
    total_krw_deposit_principal = 0
    krw_deposit_df = pd.DataFrame()
    
    if not krw_assets_df.empty:
        krw_table_rows = []
        for index, row in krw_assets_df.iterrows():
            try:
                start = pd.to_datetime(row['Start_Date'])
                end = pd.to_datetime(row['End_Date'])
                today = datetime.now()
                total_days = (end - start).days
                passed_days = (today - start).days
                if passed_days < 0: passed_days = 0
                if passed_days > total_days: passed_days = total_days
                progress = passed_days / total_days if total_days > 0 else 0
                
                interest_total = row['Target_Amount'] - row['Principal']
                current_eval = row['Principal'] + (interest_total * progress)
                
                total_krw_deposit_eval += current_eval
                total_krw_deposit_principal += row['Principal']
                
                krw_table_rows.append({
                    'Name': row['Name'], 'End_Date': row['End_Date'],
                    'Progress': progress, 'Eval_KRW': current_eval, 'Target': row['Target_Amount']
                })
            except: continue
        krw_deposit_df = pd.DataFrame(krw_table_rows)

    # 4. 국내 ETF 계산
    total_etf_eval = 0
    total_etf_principal = 0
    etf_display = pd.DataFrame()
    
    if not domestic_etf_df.empty:
        etf_rows = []
        for index, row in domestic_etf_df.iterrows():
            cur_price = row['Price_KRW'] # 현재가 API 연동 필요 (일단 매수단가 가정)
            eval_krw = row['Qty'] * cur_price
            principal_krw = row['Qty'] * row['Price_KRW']
            
            total_etf_eval += eval_krw
            total_etf_principal += principal_krw
            
            etf_rows.append({
                'Name': row['Name'], 'Qty': row['Qty'],
                'Principal': principal_krw, 'Eval': eval_krw,
                'Profit': eval_krw - principal_krw
            })
        etf_display = pd.DataFrame(etf_rows)

    # -------------------------------------------------------
    # [세금 계산 로직 적용] Toggle ON 일 때만 작동
    # -------------------------------------------------------
    us_tax_amount = 0
    isa_tax_amount = 0

    if apply_tax:
        # 1. 미국 주식 (양도세 22%)
        total_us_profit = total_us_eval_krw - total_us_principal_krw
        if total_us_profit > US_DEDUCTION:
            us_tax_amount = (total_us_profit - US_DEDUCTION) * US_TAX_RATE
            # 평가액과 이익금에서 세금 차감
            total_us_eval_krw -= us_tax_amount
        
        # 2. 국내 ETF (ISA 9.9%)
        total_etf_profit = total_etf_eval - total_etf_principal
        if total_etf_profit > ISA_LIMIT:
            isa_tax_amount = (total_etf_profit - ISA_LIMIT) * ISA_TAX_RATE
            # 평가액과 이익금에서 세금 차감
            total_etf_eval -= isa_tax_amount

    # -------------------------------------------------------
    # B. 시각화 및 출력
    # -------------------------------------------------------
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("📊 자산 배분")
        labels = ['미국주식 (USD)', '달러현금 (USD)', '원화예금 (KRW)', '국내ETF (KRW)']
        values = [total_us_eval_krw, usd_cash_krw_value, total_krw_deposit_eval, total_etf_eval]
        
        if sum(values) > 0:
            fig_donut = px.pie(values=values, names=labels, hole=0.4)
            fig_donut.update_traces(textinfo='percent+label')
            st.plotly_chart(fig_donut, use_container_width=True)
        
    with col2:
        st.subheader("💰 수익 기여도")
        us_profit = total_us_eval_krw - total_us_principal_krw
        cash_profit = usd_cash_krw_value - usd_cash_principal
        deposit_profit = total_krw_deposit_eval - total_krw_deposit_principal
        etf_profit = total_etf_eval - total_etf_principal # ISA 세후 이익 반영됨
        
        # 세금 반영 후 수익 시각화
        fig_bar = go.Figure(data=[
            go.Bar(name='미국주식', x=['수익금'], y=[us_profit]),
            go.Bar(name='달러현금', x=['수익금'], y=[cash_profit]),
            go.Bar(name='원화예금', x=['수익금'], y=[deposit_profit]),
            go.Bar(name='국내ETF(ISA)', x=['수익금'], y=[etf_profit])
        ])
        st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("📑 통합 자산 현황")
    
    total_principal = total_us_principal_krw + usd_cash_principal + total_krw_deposit_principal + total_etf_principal
    total_eval = total_us_eval_krw + usd_cash_krw_value + total_krw_deposit_eval + total_etf_eval
    
    # 만약 세금 토글 켜졌으면, 원금은 그대로지만 평가액이 줄어들었으므로 이익도 줄어듦
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
    
    if apply_tax:
        st.caption(f"※ 세금 차감액 - 미국주식: {us_tax_amount:,.0f}원 / ISA: {isa_tax_amount:,.0f}원")

    # 상세 탭 (생략 없이 기존과 동일한 UI 로직 유지하되 데이터만 반영)
    tab1, tab2, tab3 = st.tabs(["🇺🇸 미국 직투", "🇰🇷 국내 ETF", "🏦 예금/공제"])
    
    with tab1:
        if not us_display.empty:
            st.dataframe(us_display[['Name', 'Rate', 'Qty', 'Eval_KRW', 'Total_Profit', 'Price_Profit', 'Ex_Profit']], use_container_width=True)
    with tab2:
        if not etf_display.empty:
            st.dataframe(etf_display, use_container_width=True)
    with tab3:
        if not krw_deposit_df.empty:
            st.dataframe(krw_deposit_df[['Name','End_Date','Progress','Eval_KRW','Target']], use_container_width=True)

except Exception as e:
    st.error(f"오류: {e}")
