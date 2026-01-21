import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.graph_objects as go
from datetime import datetime
import pytz

# -------------------------------------------------------------------
# 1. 초기 설정 (Config)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈")

# [상수 설정]
BENCHMARK_RATE = 0.035  # 비교군: 예금 금리 3.5%
# 정렬 우선순위 (리츠/배당 -> 성장 -> 기타)
TICKER_PRIORITY = ['💵 USD CASH', 'O', 'PLD', 'SCHD', 'JEPI', 'KO', 'MSFT', 'GOOGL', 'NVDA', 'TSLA']

# -------------------------------------------------------------------
# 2. 데이터 로드 및 전처리 (Data Ops)
# -------------------------------------------------------------------
def clean_currency(series):
    """ 콤마 제거 및 숫자 변환 (방탄 로직) """
    return pd.to_numeric(series.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

@st.cache_data(ttl=300) # 5분 캐시 (새로고침 버튼으로 초기화 가능)
def load_data():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")

        # 5개 시트 로드 (Dividend_Log 추가됨)
        trade_df = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        exchange_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        krw_assets_df = pd.DataFrame(sh.worksheet("KRW_Assets").get_all_records())
        etf_df = pd.DataFrame(sh.worksheet("Domestic_ETF").get_all_records())
        try:
            div_df = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        except:
            div_df = pd.DataFrame(columns=['Date', 'Ticker', 'Amount_USD', 'Note']) # 없을 경우 대비

        return trade_df, exchange_df, krw_assets_df, etf_df, div_df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_market_data(tickers):
    """ 야후 파이낸스에서 현재가 및 환율 일괄 조회 """
    data_map = {}
    try:
        # 환율
        fx = yf.Ticker("USDKRW=X").history(period="1d")['Close'].iloc[-1]
    except:
        fx = 1450.0 # Fallback

    # 주가
    if tickers:
        try:
            tickers_str = " ".join(tickers)
            df = yf.download(tickers_str, period="1d", progress=False)['Close']
            # 단일 종목일 경우 Series, 다수일 경우 DataFrame 처리
            if len(tickers) == 1:
                data_map[tickers[0]] = df.iloc[-1]
            else:
                for t in tickers:
                    data_map[t] = df[t].iloc[-1] if t in df.columns else 0
        except:
            pass
    return fx, data_map

# -------------------------------------------------------------------
# 3. 사이드바 및 컨트롤
# -------------------------------------------------------------------
with st.sidebar:
    st.header("🎮 Control Tower")
    
    # [기능] 새로고침 버튼
    if st.button("🔄 데이터 최신화 (API 호출)", type="primary"):
        st.cache_data.clear()
        st.rerun()
    
    korea_tz = pytz.timezone('Asia/Seoul')
    now_str = datetime.now(korea_tz).strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"Last Update: {now_str}")
    
    st.markdown("---")
    show_tax = st.toggle("세후 실질 가치 (Tax Cut)", value=False)
    if show_tax:
        st.info("🇺🇸 미국: 250만원 공제 후 22%\n🇰🇷 ISA: 200만원 비과세 후 9.9%")

# -------------------------------------------------------------------
# 4. 메인 로직 (Calculation Engine)
# -------------------------------------------------------------------
try:
    trade_df, exchange_df, krw_assets_df, etf_df, div_df = load_data()
    
    # 전처리
    exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
    exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
    trade_df['Qty'] = clean_currency(trade_df['Qty'])
    trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
    trade_df['Exchange_Rate'] = clean_currency(trade_df['Exchange_Rate'])
    if not div_df.empty: div_df['Amount_USD'] = clean_currency(div_df['Amount_USD'])

    # 시장 데이터 조회
    unique_tickers = trade_df['Ticker'].unique().tolist()
    current_rate, price_map = get_market_data(unique_tickers)

    # ---------------- [A. 달러 현금 (종목화)] ----------------
    total_usd_exchanged = exchange_df['USD_Amount'].sum()
    total_krw_exchanged = exchange_df['KRW_Amount'].sum()
    # 현금 평단 (이동평균)
    avg_cash_rate = total_krw_exchanged / total_usd_exchanged if total_usd_exchanged > 0 else 0
    
    total_usd_invested = (trade_df['Qty'] * trade_df['Price_USD']).sum()
    usd_cash_balance = total_usd_exchanged - total_usd_invested
    
    # 현금 가치 평가
    cash_principal_krw = usd_cash_balance * avg_cash_rate
    cash_eval_krw = usd_cash_balance * current_rate
    
    # 현금 손익 분해 (이자수익은 별도 입력 없다면 0 가정, 환차익만 계산)
    cash_fx_profit = cash_principal_krw * (current_rate / avg_cash_rate - 1) if avg_cash_rate else 0
    cash_row = {
        'Ticker': '💵 USD CASH', 'Name': '달러예수금',
        'Qty': usd_cash_balance,
        'Principal': cash_principal_krw, 'Eval': cash_eval_krw,
        'Price_Profit': 0, # 추후 RP 이자 반영 가능
        'FX_Profit': cash_fx_profit, 'Div_Profit': 0,
        'Total_Profit': cash_eval_krw - cash_principal_krw,
        'Buy_Rate': avg_cash_rate, 'BE_Rate': 0, 'Safety_Margin': 9999
    }

    # ---------------- [B. 미국 주식 (상세 계산)] ----------------
    stock_rows = []
    
    for ticker, group in trade_df.groupby('Ticker'):
        qty = group['Qty'].sum()
        if qty == 0: continue
        
        # 가중 평균 매수정보
        principal_usd = (group['Qty'] * group['Price_USD']).sum()
        principal_krw = (group['Qty'] * group['Price_USD'] * group['Exchange_Rate']).sum()
        avg_buy_rate = principal_krw / principal_usd if principal_usd else 0
        avg_buy_price = principal_usd / qty

        # 현재가
        cur_price = price_map.get(ticker, avg_buy_price)
        
        # 평가액
        eval_usd = qty * cur_price
        eval_krw = eval_usd * current_rate
        
        # 배당 수익 (누적)
        div_usd = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() if not div_df.empty else 0
        div_krw = div_usd * current_rate # 단순화를 위해 현재환율 적용 (엄밀히는 수령일 환율이나, 지표용으론 무방)

        # 손익 분해
        # 1. 총 손익 (평가액 - 원금)
        total_profit = eval_krw - principal_krw
        # 2. 환 손익 (달러원금 * 환율차)
        fx_profit = principal_usd * (current_rate - avg_buy_rate)
        # 3. 주가 손익 (나머지)
        price_profit = total_profit - fx_profit
        
        # [세금 로직]
        if show_tax:
            taxable = total_profit + div_krw - 2500000 # 배당 포함 여부는 과세 체계따라 다르나 단순화
            if taxable > 0:
                tax = taxable * 0.22
                eval_krw -= tax
                total_profit -= tax # 세금만큼 이익 감소

        # [안전마진 계산] 손익분기 환율 = (투입원화 - 누적배당) / 현재달러가치
        be_rate = (principal_krw - div_krw) / eval_usd if eval_usd else 0
        safety_margin = current_rate - be_rate

        stock_rows.append({
            'Ticker': ticker, 'Name': group['Name'].iloc[0],
            'Qty': qty,
            'Principal': principal_krw, 'Eval': eval_krw,
            'Price_Profit': price_profit,
            'FX_Profit': fx_profit,
            'Div_Profit': div_krw,
            'Total_Profit': total_profit + div_krw, # ROI 계산용 (배당 포함)
            'Buy_Rate': avg_buy_rate, 'BE_Rate': be_rate, 'Safety_Margin': safety_margin
        })
    
    # 통합 데이터프레임
    df_stocks = pd.DataFrame(stock_rows)
    df_combined = pd.concat([pd.DataFrame([cash_row]), df_stocks], ignore_index=True)

    # ---------------- [C. 국내 ETF (ISA)] ----------------
    etf_rows = []
    if not etf_df.empty:
        etf_df['Qty'] = clean_currency(etf_df['Qty'])
        etf_df['Price_KRW'] = clean_currency(etf_df['Price_KRW'])
        for _, row in etf_df.iterrows():
            eval_v = row['Qty'] * row['Price_KRW'] # 현재가 연동 필요(임시로 매수가 사용)
            princ_v = row['Qty'] * row['Price_KRW']
            prof = eval_v - princ_v
            
            if show_tax and prof > 2000000:
                prof -= (prof - 2000000) * 0.099
            
            etf_rows.append({'Name': row['Name'], 'Profit': prof})
    df_etf_res = pd.DataFrame(etf_rows)

    # -------------------------------------------------------------------
    # 5. UI 렌더링 (Visual Presentation)
    # -------------------------------------------------------------------
    
    # A. KPI Section (vs 예금)
    total_principal = df_combined['Principal'].sum()
    total_eval = df_combined['Eval'].sum()
    total_div = df_combined['Div_Profit'].sum()
    
    # 현금+주식의 총 수익금 (배당 포함)
    grand_total_profit = (df_combined['Total_Profit'].sum())
    total_return_rate = (grand_total_profit / total_principal * 100) if total_principal else 0
    excess_return = total_return_rate - (BENCHMARK_RATE * 100)
    
    # 환효과 합계
    total_fx_profit = df_combined['FX_Profit'].sum()
    total_fx_return = (total_fx_profit / total_principal * 100) if total_principal else 0

    st.title("🚀 Investment Strategy Command")
    
    col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
    with col_kpi1:
        st.metric("총 투자 수익률 (ROI)", f"{total_return_rate:+.2f}%", f"{excess_return:+.2f}%p (vs 예금)")
    with col_kpi2:
        st.metric("순수 환차익 효과", f"{total_fx_return:+.2f}%", "환율 변동 기여분")
    with col_kpi3:
        st.metric("현재 시장 환율", f"{current_rate:,.2f}원", "실시간 적용")

    # B. Sector Analysis (양방향 그래프)
    st.subheader("⚖️ 포트폴리오 밸런스 (Sector PnL)")
    
    # 섹터 분류 (임시 로직: 리스트 기반)
    dividend_tickers = ['O', 'PLD', 'SCHD', 'JEPI', 'KO']
    tech_tickers = ['MSFT', 'GOOGL', 'NVDA', 'TSLA']
    
    sec_div_profit = df_combined[df_combined['Ticker'].isin(dividend_tickers)]['Total_Profit'].sum()
    sec_tech_profit = df_combined[df_combined['Ticker'].isin(tech_tickers)]['Total_Profit'].sum()
    sec_cash_profit = cash_row['Total_Profit']
    
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        y=['배당/리츠', '테크/성장', '달러현금'],
        x=[sec_div_profit, sec_tech_profit, sec_cash_profit],
        orientation='h',
        marker=dict(color=['#FF3B30' if x>0 else '#007AFF' for x in [sec_div_profit, sec_tech_profit, sec_cash_profit]])
    ))
    fig_bar.update_layout(xaxis_title="손익금 (KRW)", margin=dict(l=0, r=0, t=0, b=0), height=150)
    # 0원 기준선 추가
    fig_bar.add_vline(x=0, line_width=1, line_color="gray")
    st.plotly_chart(fig_bar, use_container_width=True)

    # C. Main Table (HTML Custom Render)
    st.subheader("📑 해외자산 통합 현황")
    
    # 정렬 (Priority Map)
    df_combined['SortKey'] = df_combined['Ticker'].apply(lambda x: TICKER_PRIORITY.index(x) if x in TICKER_PRIORITY else 999)
    df_combined = df_combined.sort_values(['SortKey', 'Ticker'])
    
    # HTML 생성 함수
    def make_html_table(df):
        html = """
        <style>
            table {width: 100%; border-collapse: collapse; font-size: 0.95em;}
            th {background-color: #f0f2f6; padding: 10px; text-align: right; border-bottom: 2px solid #ddd;}
            td {padding: 8px; text-align: right; border-bottom: 1px solid #eee; vertical-align: middle;}
            .left {text-align: left;}
            .sub {font-size: 0.8em; color: gray; display: block;}
            .red {color: #D32F2F; font-weight: bold;}
            .blue {color: #1976D2; font-weight: bold;}
            .zero {color: #ccc;}
        </style>
        <table>
            <thead>
                <tr>
                    <th class="left">종목 (Name)</th>
                    <th>주가손익 (수익률)</th>
                    <th>환손익 (노출도)</th>
                    <th>배당수익</th>
                    <th>합계손익 (ROI)</th>
                    <th>매수 / BEP / 안전마진</th>
                </tr>
            </thead>
            <tbody>
        """
        
        # Body
        for _, row in df.iterrows():
            # Helper for Color
            def color_val(val, sub_val=None):
                if val > 0: c = "red"; s = "+"
                elif val < 0: c = "blue"; s = ""
                else: return '<span class="zero">-</span>'
                
                main_txt = f'<span class="{c}">{s}{val:,.0f}</span>'
                if sub_val is not None:
                    sub_txt = f'<span class="{c} sub">({sub_val:+.2f}%)</span>'
                    return f"{main_txt}<br>{sub_txt}"
                return main_txt

            name_cell = f"<b>{row['Ticker']}</b><span class='sub'>{row['Name']}</span>"
            
            price_roi = row['Price_Profit']/row['Principal']*100 if row['Principal'] else 0
            fx_roi = row['FX_Profit']/row['Principal']*100 if row['Principal'] else 0
            total_roi = row['Total_Profit']/row['Principal']*100 if row['Principal'] else 0
            
            price_cell = color_val(row['Price_Profit'], price_roi)
            fx_cell = color_val(row['FX_Profit'], fx_roi)
            div_cell = color_val(row['Div_Profit'])
            total_cell = color_val(row['Total_Profit'], total_roi)
            
            if row['Ticker'] == '💵 USD CASH':
                margin_cell = f"{row['Buy_Rate']:,.1f} / - / ∞"
            else:
                margin_val = row['Safety_Margin']
                margin_color = "green" if margin_val > 0 else "red"
                margin_cell = f"{row['Buy_Rate']:,.1f} / {row['BE_Rate']:,.1f} / <b style='color:{margin_color}'>{margin_val:+.1f}</b>"

            html += f"""
                <tr>
                    <td class="left">{name_cell}</td>
                    <td>{price_cell}</td>
                    <td>{fx_cell}</td>
                    <td>{div_cell}</td>
                    <td>{total_cell}</td>
                    <td>{margin_cell}</td>
                </tr>
            """
            
        # Footer (Total)
        t_price = df['Price_Profit'].sum()
        t_fx = df['FX_Profit'].sum()
        t_div = df['Div_Profit'].sum()
        t_total = df['Total_Profit'].sum()
        t_roi = t_total / df['Principal'].sum() * 100 if df['Principal'].sum() else 0
        
        html += f"""
            <tr style="background-color: #fafafa; font-weight: bold;">
                <td class="left">🔴 TOTAL</td>
                <td>{t_price:,.0f}</td>
                <td>{t_fx:,.0f}</td>
                <td>{t_div:,.0f}</td>
                <td>{t_total:,.0f}<br><span class="sub">({t_roi:+.2f}%)</span></td>
                <td>-</td>
            </tr>
            </tbody></table>
        """
        return html

    st.markdown(make_html_table(df_combined), unsafe_allow_html=True)

    # -------------------------------------------------------------------
    # 6. 하단 상세 탭
    # -------------------------------------------------------------------
    st.markdown("###")
    tab1, tab2, tab3 = st.tabs(["🇺🇸 미국 주식 원본", "🇰🇷 국내 ETF (ISA)", "🏦 예금/공제"])
    
    with tab1:
        st.dataframe(df_combined, use_container_width=True, hide_index=True)
    with tab2:
        if not df_etf_res.empty:
            st.metric("ISA 총 수익", f"{df_etf_res['Profit'].sum():,.0f}원")
            st.dataframe(df_etf_res, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")
    with tab3:
        # 예금은 총 자산 계산에서 제외되었음을 명시
        if not krw_assets_df.empty:
            st.caption("※ 예금/공제 자산은 메인 포트폴리오 성과 분석에서 제외되었습니다.")
            st.dataframe(krw_assets_df, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")

except Exception as e:
    st.error("시스템 오류 발생")
    st.write(e)
