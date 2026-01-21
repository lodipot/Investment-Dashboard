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
# 정렬 우선순위 (JEPQ 추가됨)
TICKER_PRIORITY = ['💵 USD CASH', 'O', 'PLD', 'SCHD', 'JEPI', 'JEPQ', 'KO', 'MSFT', 'GOOGL', 'NVDA', 'TSLA', 'AMD']

# -------------------------------------------------------------------
# 2. 데이터 로드 및 전처리 (Data Ops)
# -------------------------------------------------------------------
def clean_currency(series):
    """ 콤마 제거 및 숫자 변환 (방탄 로직) """
    return pd.to_numeric(series.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

@st.cache_data(ttl=300) # 5분 캐시
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
        etf_df = pd.DataFrame(sh.worksheet("Domestic_ETF").get_all_records())
        try:
            div_df = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        except:
            div_df = pd.DataFrame(columns=['Date', 'Ticker', 'Amount_USD', 'Note'])

        return trade_df, exchange_df, krw_assets_df, etf_df, div_df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_market_data(tickers):
    """ 야후 파이낸스에서 현재가 및 환율 일괄 조회 """
    data_map = {}
    try:
        fx = yf.Ticker("USDKRW=X").history(period="1d")['Close'].iloc[-1]
    except:
        fx = 1450.0 # Fallback

    if tickers:
        try:
            # JEPQ 등 신규 종목이 있을 수 있으므로 필터링
            valid_tickers = [t for t in tickers if t != '💵 USD CASH']
            if valid_tickers:
                tickers_str = " ".join(valid_tickers)
                df = yf.download(tickers_str, period="1d", progress=False)['Close']
                if len(valid_tickers) == 1:
                    data_map[valid_tickers[0]] = df.iloc[-1]
                else:
                    for t in valid_tickers:
                        # yfinance 구조상 멀티인덱스일수도, 아닐수도 있어 안전하게 처리
                        try:
                            val = df[t].iloc[-1]
                            data_map[t] = val
                        except:
                            data_map[t] = 0
        except:
            pass
    return fx, data_map

# -------------------------------------------------------------------
# 3. 사이드바 및 컨트롤
# -------------------------------------------------------------------
with st.sidebar:
    st.header("🎮 Control Tower")
    
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
    
    if not exchange_df.empty:
        exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
        exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
    if not trade_df.empty:
        trade_df['Qty'] = clean_currency(trade_df['Qty'])
        trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
        trade_df['Exchange_Rate'] = clean_currency(trade_df['Exchange_Rate'])
    if not div_df.empty: 
        div_df['Amount_USD'] = clean_currency(div_df['Amount_USD'])

    unique_tickers = trade_df['Ticker'].unique().tolist()
    current_rate, price_map = get_market_data(unique_tickers)

    # ---------------- [A. 달러 현금] ----------------
    total_usd_exchanged = exchange_df['USD_Amount'].sum() if not exchange_df.empty else 0
    total_krw_exchanged = exchange_df['KRW_Amount'].sum() if not exchange_df.empty else 0
    avg_cash_rate = total_krw_exchanged / total_usd_exchanged if total_usd_exchanged > 0 else 0
    
    total_usd_invested = (trade_df['Qty'] * trade_df['Price_USD']).sum() if not trade_df.empty else 0
    usd_cash_balance = total_usd_exchanged - total_usd_invested
    
    cash_principal_krw = usd_cash_balance * avg_cash_rate
    cash_eval_krw = usd_cash_balance * current_rate
    
    cash_fx_profit = cash_principal_krw * (current_rate / avg_cash_rate - 1) if avg_cash_rate else 0
    cash_row = {
        'Ticker': '💵 USD CASH', 'Name': '달러예수금',
        'Qty': usd_cash_balance,
        'Principal': cash_principal_krw, 'Eval': cash_eval_krw,
        'Price_Profit': 0, 
        'FX_Profit': cash_fx_profit, 'Div_Profit': 0,
        'Total_Profit': cash_eval_krw - cash_principal_krw,
        'Buy_Rate': avg_cash_rate, 'BE_Rate': 0, 'Safety_Margin': 9999
    }

    # ---------------- [B. 미국 주식] ----------------
    stock_rows = []
    
    if not trade_df.empty:
        for ticker, group in trade_df.groupby('Ticker'):
            qty = group['Qty'].sum()
            if qty == 0: continue
            
            principal_usd = (group['Qty'] * group['Price_USD']).sum()
            principal_krw = (group['Qty'] * group['Price_USD'] * group['Exchange_Rate']).sum()
            avg_buy_rate = principal_krw / principal_usd if principal_usd else 0
            avg_buy_price = principal_usd / qty

            cur_price = price_map.get(ticker, avg_buy_price)
            if pd.isna(cur_price): cur_price = avg_buy_price # NaN 방지
            
            eval_usd = qty * cur_price
            eval_krw = eval_usd * current_rate
            
            div_usd = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() if not div_df.empty else 0
            div_krw = div_usd * current_rate

            total_profit = eval_krw - principal_krw
            fx_profit = principal_usd * (current_rate - avg_buy_rate)
            price_profit = total_profit - fx_profit
            
            if show_tax:
                taxable = total_profit + div_krw - 2500000 
                if taxable > 0:
                    tax = taxable * 0.22
                    eval_krw -= tax
                    total_profit -= tax

            be_rate = (principal_krw - div_krw) / eval_usd if eval_usd > 0 else 0
            safety_margin = current_rate - be_rate

            stock_rows.append({
                'Ticker': ticker, 'Name': group['Name'].iloc[0],
                'Qty': qty,
                'Principal': principal_krw, 'Eval': eval_krw,
                'Price_Profit': price_profit,
                'FX_Profit': fx_profit,
                'Div_Profit': div_krw,
                'Total_Profit': total_profit + div_krw,
                'Buy_Rate': avg_buy_rate, 'BE_Rate': be_rate, 'Safety_Margin': safety_margin
            })
    
    df_stocks = pd.DataFrame(stock_rows)
    df_combined = pd.concat([pd.DataFrame([cash_row]), df_stocks], ignore_index=True)

    # ---------------- [C. 국내 ETF] ----------------
    etf_rows = []
    if not etf_df.empty:
        etf_df['Qty'] = clean_currency(etf_df['Qty'])
        etf_df['Price_KRW'] = clean_currency(etf_df['Price_KRW'])
        for _, row in etf_df.iterrows():
            eval_v = row['Qty'] * row['Price_KRW'] 
            princ_v = row['Qty'] * row['Price_KRW']
            prof = eval_v - princ_v
            
            if show_tax and prof > 2000000:
                prof -= (prof - 2000000) * 0.099
            etf_rows.append({'Name': row['Name'], 'Profit': prof})
    df_etf_res = pd.DataFrame(etf_rows)

    # -------------------------------------------------------------------
    # 5. UI 렌더링 (Visual Presentation)
    # -------------------------------------------------------------------
    
    # A. KPI Section
    total_principal = df_combined['Principal'].sum()
    grand_total_profit = df_combined['Total_Profit'].sum()
    total_return_rate = (grand_total_profit / total_principal * 100) if total_principal else 0
    excess_return = total_return_rate - (BENCHMARK_RATE * 100)
    
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

    # B. Sector Analysis
    st.subheader("⚖️ 포트폴리오 밸런스 (Sector PnL)")
    dividend_tickers = ['O', 'PLD', 'SCHD', 'JEPI', 'JEPQ', 'KO']
    tech_tickers = ['MSFT', 'GOOGL', 'NVDA', 'TSLA', 'AMD']
    
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
    fig_bar.add_vline(x=0, line_width=1, line_color="gray")
    st.plotly_chart(fig_bar, use_container_width=True)

    # C. Main Table (HTML Custom Render)
    st.subheader("📑 해외자산 통합 현황")
    
    df_combined['SortKey'] = df_combined['Ticker'].apply(lambda x: TICKER_PRIORITY.index(x) if x in TICKER_PRIORITY else 999)
    df_combined = df_combined.sort_values(['SortKey', 'Ticker'])
    
    def make_html_table(df):
        # 다크모드 대응을 위해 th 색상 강제 지정 (배경 연회색, 글자 검정)
        html = """
        <style>
            table {width: 100%; border-collapse: collapse; font-size: 0.95em; color: #333333;}
            th {background-color: #f0f2f6; color: #000000 !important; padding: 10px; text-align: right; border-bottom: 2px solid #ddd;}
            td {padding: 8px; text-align: right; border-bottom: 1px solid #eee; vertical-align: middle; color: inherit;}
            .left {text-align: left;}
            .sub {font-size: 0.8em; color: gray; display: block;}
            .red {color: #D32F2F; font-weight: bold;}
            .blue {color: #1976D2; font-weight: bold;}
            .zero {color: #ccc;}
            /* 다크모드에서 테이블 본문 글씨가 안 보일 수 있으므로 명시적 지정이 안전하나, 
               스트림릿 테마를 따르기 위해 td color는 inherit으로 두고 red/blue 클래스로 덮어씀 */
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
        
        for _, row in df.iterrows():
            def color_val(val, sub_val=None):
                # [수정] 소수점 둘째자리(.2f) 강제 통일
                if val > 0: 
                    c = "red"; s = "+"
                    main_txt = f'<span class="{c}">{s}{val:,.2f}</span>'
                elif val < 0: 
                    c = "blue"; s = "" # 마이너스는 숫자에 포함됨
                    main_txt = f'<span class="{c}">{val:,.2f}</span>'
                else: 
                    return '<span class="zero">-</span>'
                
                if sub_val is not None:
                    # 수익률도 .2f 통일
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
            
        t_price = df['Price_Profit'].sum()
        t_fx = df['FX_Profit'].sum()
        t_div = df['Div_Profit'].sum()
        t_total = df['Total_Profit'].sum()
        t_roi = t_total / df['Principal'].sum() * 100 if df['Principal'].sum() else 0
        
        # 합계행
        html += f"""
            <tr style="background-color: #fafafa; font-weight: bold; color: #000;">
                <td class="left">🔴 TOTAL</td>
                <td>{t_price:,.2f}</td>
                <td>{t_fx:,.2f}</td>
                <td>{t_div:,.2f}</td>
                <td>{t_total:,.2f}<br><span class="sub" style="color:gray">({t_roi:+.2f}%)</span></td>
                <td>-</td>
            </tr>
            </tbody></table>
        """
        return html

    # [수정] unsafe_allow_html=True 필수 적용
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
        if not krw_assets_df.empty:
            st.caption("※ 예금/공제 자산은 메인 포트폴리오 성과 분석에서 제외되었습니다.")
            st.dataframe(krw_assets_df, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")

except Exception as e:
    st.error("시스템 오류 발생")
    st.write(e)
