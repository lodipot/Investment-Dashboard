import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import textwrap
import re

# -------------------------------------------------------------------
# 1. 초기 설정 & 통합 스타일링
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

# 세션 상태 초기화 (입력 로그용)
if 'input_log' not in st.session_state:
    st.session_state['input_log'] = []

st.markdown("""
<style>
    /* [1] 사이드바 완전 숨김 (원페이지 앱 느낌) */
    [data-testid="stSidebar"] { display: none; }
    
    /* [2] 메인 탭바 상단 고정 (Sticky Main Tabs) */
    div[data-testid="stTabs"] > div:first-child {
        position: sticky;
        top: 0;
        z-index: 1000;
        background-color: white;
        padding-top: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid #f0f0f0;
    }

    /* [3] KPI 컨테이너 (3열 고정 Grid) */
    .kpi-container {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 8px;
        margin-bottom: 20px;
    }
    .kpi-cube {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 1vw;
        text-align: center;
        display: flex;
        flex-direction: column;
        justify-content: center;
        aspect-ratio: 1 / 0.8;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .kpi-title { font-size: clamp(10px, 1.2vw, 16px); color: #6c757d; font-weight: 600; white-space: nowrap; }
    .kpi-value { font-size: clamp(14px, 2.5vw, 32px); font-weight: 800; color: #212529; margin: 4px 0; }
    .kpi-sub { font-size: clamp(9px, 1vw, 14px); font-weight: 500; }

    /* [4] 주식 카드 (Rich Info Style) */
    .stock-card {
        background-color: white;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        transition: transform 0.2s;
    }
    .card-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
    .ticker-name { font-size: 1.1rem; font-weight: 700; color: #333; }
    .full-name { font-size: 0.8rem; color: #888; margin-left: 6px; }
    .main-val { font-size: 1.4rem; font-weight: 800; color: #212529; margin-bottom: 4px; }
    .profit-row { font-size: 0.95rem; font-weight: 600; margin-bottom: 12px; }
    .badge-margin { display: inline-block; padding: 4px 8px; border-radius: 6px; font-size: 0.8rem; font-weight: 700; }

    /* [5] 모바일 버튼 텍스트 깨짐 방지 */
    div[data-testid="stPopover"] > button {
        width: 100%;
        color: transparent !important;
        text-shadow: 0 0 0 #495057;
        height: 38px;
    }

    /* 유틸리티 색상 */
    .c-red { color: #D32F2F !important; }
    .c-blue { color: #1976D2 !important; }
    .c-gray { color: #adb5bd !important; }
    .bg-red-light { background-color: #ffebee !important; color: #c62828 !important; }
    .bg-green-light { background-color: #e8f5e9 !important; color: #2e7d32 !important; }
    .bg-gray-light { background-color: #f8f9fa !important; color: #495057 !important; }
</style>
""", unsafe_allow_html=True)

# [상수 및 설정]
BENCHMARK_RATE = 0.035
SECTORS = {
    'REITS': {'emoji': '🏢', 'name': '리츠', 'tickers': ['O', 'PLD']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'KO']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크', 'tickers': ['MSFT', 'GOOGL']},
    'VOL_TECH': {'emoji': '🚀', 'name': '성장주', 'tickers': ['NVDA', 'TSLA', 'AMD']},
    'CASH': {'emoji': '💵', 'name': '현금', 'tickers': ['💵 USD CASH']}
}
SORT_ORDER = ['O', 'PLD', 'JEPI', 'JEPQ', 'KO', 'SCHD', 'GOOGL', 'MSFT', 'AMD', 'NVDA', 'TSLA', '💵 USD CASH']

# -------------------------------------------------------------------
# 2. 공통 함수 (데이터 로드 & 계산)
# -------------------------------------------------------------------
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open("Investment_Dashboard_DB")

def clean_currency(series):
    return pd.to_numeric(series.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

@st.cache_data(ttl=60)
def load_data():
    try:
        sh = get_client()
        trade_df = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        exchange_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        krw_assets_df = pd.DataFrame(sh.worksheet("KRW_Assets").get_all_records())
        etf_df = pd.DataFrame(sh.worksheet("Domestic_ETF").get_all_records())
        try:
            div_df = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        except:
            div_df = pd.DataFrame(columns=['Date', 'Ticker', 'Amount_USD', 'Note'])
        return trade_df, exchange_df, krw_assets_df, etf_df, div_df
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_market_data(tickers):
    fx = 1450.0; fx_status = "Fallback"
    try:
        fx_hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not fx_hist.empty: fx = fx_hist['Close'].iloc[-1]; fx_status = "Live"
    except: pass
    
    data_map = {}
    if tickers:
        valid_tickers = [t for t in tickers if t != '💵 USD CASH']
        for t in valid_tickers:
            try:
                hist = yf.Ticker(t).history(period="1d")
                if not hist.empty: data_map[t] = hist['Close'].iloc[-1]
            except: pass
    return fx, fx_status, data_map

# 평단 자동 계산 (8자리) - Input Manager용
def calculate_metrics_live(sh):
    try:
        ex_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        tr_df = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        div_df = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        
        timeline = []
        def clean(x): return float(str(x).replace(',','')) if str(x).replace(',','').replace('.','').isdigit() else 0
        
        for _, r in ex_df.iterrows():
            timeline.append({'date': r['Date'], 'type': 'exchange', 'usd': clean(r['USD_Amount']), 'krw': clean(r['KRW_Amount'])})
        for _, r in div_df.iterrows():
            ex_rate = clean(r['Ex_Rate'])
            amt = clean(r['Amount_USD'])
            timeline.append({'date': r['Date'], 'type': 'dividend', 'usd': amt, 'krw': amt * ex_rate})
        for _, r in tr_df.iterrows():
            cost = clean(r['Qty']) * clean(r['Price_USD'])
            timeline.append({'date': r['Date'], 'type': 'trade', 'usd': -cost, 'krw': 0})
            
        prio = {'dividend':1, 'exchange':2, 'trade':3}
        timeline.sort(key=lambda x: (x['date'], prio.get(x['type'], 9)))
        
        curr_usd = 0.0; curr_krw = 0.0
        for item in timeline:
            if item['type'] in ['exchange', 'dividend']:
                curr_usd += item['usd']; curr_krw += item['krw']
            elif item['type'] == 'trade':
                if curr_usd > 0:
                    avg_rate = curr_krw / curr_usd
                    curr_krw -= abs(item['usd']) * avg_rate
                curr_usd += item['usd']
        
        final_rate = (curr_krw / curr_usd) if curr_usd > 0 else 1450.0
        return round(final_rate, 8)
    except: return 1450.0

# -------------------------------------------------------------------
# 3. 메인 앱 로직
# -------------------------------------------------------------------

# 최상단 메인 탭 (네비게이션 대체)
main_tab1, main_tab2 = st.tabs(["📊 대시보드", "📝 입력 매니저"])

# ===================================================================
# [PAGE 1] 대시보드
# ===================================================================
with main_tab1:
    trade_df, exchange_df, krw_assets_df, etf_df, div_df = load_data()
    
    # 데이터 가공 및 계산 로직 (기존 Dashboard.py 로직과 동일)
    if not exchange_df.empty:
        exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
        exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
    if not trade_df.empty:
        trade_df['Qty'] = clean_currency(trade_df['Qty'])
        trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
    if not div_df.empty:
        div_df['Amount_USD'] = clean_currency(div_df['Amount_USD'])

    unique_tickers = trade_df['Ticker'].unique().tolist()
    current_rate, fx_status, price_map = get_market_data(unique_tickers)

    # 현금 & 주식 계산 (로직 생략 없이 그대로 적용)
    total_usd_exchanged = exchange_df['USD_Amount'].sum() if not exchange_df.empty else 0
    total_krw_exchanged = exchange_df['KRW_Amount'].sum() if not exchange_df.empty else 0
    avg_cash_rate = total_krw_exchanged / total_usd_exchanged if total_usd_exchanged > 0 else 0
    
    total_usd_invested = (trade_df['Qty'] * trade_df['Price_USD']).sum() if not trade_df.empty else 0
    usd_cash_balance = total_usd_exchanged - total_usd_invested
    
    cash_row = {
        'Ticker': '💵 USD CASH', 'Name': '달러예수금',
        'Principal': usd_cash_balance * avg_cash_rate, 'Eval': usd_cash_balance * current_rate,
        'Price_Profit': 0, 'FX_Profit': (usd_cash_balance * avg_cash_rate) * (current_rate/avg_cash_rate - 1) if avg_cash_rate else 0,
        'Div_Profit': 0, 'Total_Profit': (usd_cash_balance * current_rate) - (usd_cash_balance * avg_cash_rate),
        'Buy_Rate': avg_cash_rate, 'BE_Rate': 0, 'Safety_Margin': 9999
    }

    stock_rows = []
    if not trade_df.empty:
        for ticker, group in trade_df.groupby('Ticker'):
            qty = group['Qty'].sum()
            if qty == 0: continue
            
            p_usd = (group['Qty'] * group['Price_USD']).sum()
            p_krw = (group['Qty'] * group['Price_USD'] * group['Exchange_Rate']).sum()
            if p_krw == 0 and p_usd > 0: p_krw = p_usd * 1450 # Fallback
            
            cur_p = price_map.get(ticker, 0)
            if cur_p == 0: cur_p = p_usd / qty

            eval_krw = qty * cur_p * current_rate
            div_krw = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() * current_rate if not div_df.empty else 0
            
            fx_p = p_usd * (current_rate - (p_krw/p_usd if p_usd else 0))
            tot_p = (eval_krw - p_krw) + div_krw
            pri_p = tot_p - fx_p - div_krw
            
            be = (p_krw - div_krw) / (qty * cur_p) if (qty*cur_p) > 0 else 0 # BEP 환율 역산
            if be == 0: be_rate = 0 
            else: be_rate = (p_krw - div_krw) / (qty * cur_p) # Logic check: BEP rate = (Principal_KRW - Div_KRW) / Eval_USD

            stock_rows.append({
                'Ticker': ticker, 'Name': group['Name'].iloc[0], 'Principal': p_krw, 'Eval': eval_krw,
                'Price_Profit': pri_p, 'FX_Profit': fx_p, 'Div_Profit': div_krw, 'Total_Profit': tot_p,
                'Safety_Margin': current_rate - be_rate
            })

    df_combined = pd.concat([pd.DataFrame([cash_row]), pd.DataFrame(stock_rows)], ignore_index=True)
    
    def get_sector(ticker):
        for code, info in SECTORS.items():
            if ticker in info['tickers']: return code
        return 'ETC'
    df_combined['Sector'] = df_combined['Ticker'].apply(get_sector)
    df_combined['SortKey'] = df_combined['Ticker'].apply(lambda x: SORT_ORDER.index(x) if x in SORT_ORDER else 999)
    df_combined = df_combined.sort_values(['SortKey', 'Ticker']).drop(columns=['SortKey'])

    # 대시보드 내부 서브 탭
    sub_kpi, sub_card, sub_html, sub_detail = st.tabs(["📊 KPI", "🗂️ 카드", "📑 통합", "📋 세부"])

    with sub_kpi:
        t_princ = df_combined['Principal'].sum()
        roi = (df_combined['Total_Profit'].sum() / t_princ * 100) if t_princ else 0
        fx_roi = (df_combined['FX_Profit'].sum() / t_princ * 100) if t_princ else 0
        excess = roi - (BENCHMARK_RATE*100)
        
        st.markdown(f"""
        <div class="kpi-container">
            <div class="kpi-cube">
                <div class="kpi-title">총 수익률</div>
                <div class="kpi-value {'c-red' if roi>0 else 'c-blue'}">{roi:+.2f}%</div>
                <div class="kpi-sub">vs 예금 {excess:+.2f}%p</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">순수 환차익</div>
                <div class="kpi-value {'c-red' if fx_roi>0 else 'c-blue'}">{fx_roi:+.2f}%</div>
                <div class="kpi-sub">환율 변동 효과</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">현재 환율</div>
                <div class="kpi-value">{current_rate:,.0f}원</div>
                <div class="kpi-sub">{fx_status}</div>
            </div>
        </div>""", unsafe_allow_html=True)

    with sub_card:
        st.caption("📌 섹터별 요약")
        sec_cols = st.columns(len(SECTORS))
        for i, (code, info) in enumerate(SECTORS.items()):
            s_df = df_combined[df_combined['Sector'] == code]
            s_prof = s_df['Total_Profit'].sum()
            s_roi = s_prof / s_df['Principal'].sum() * 100 if s_df['Principal'].sum() else 0
            cls = "c-red" if s_prof > 0 else "c-blue" if s_prof < 0 else "c-gray"
            with sec_cols[i]:
                st.markdown(f"""
                <div style="text-align:center; padding:5px; background:#f8f9fa; border-radius:8px;">
                    <div style="font-size:0.8rem; color:#666;">{info['emoji']} {info['name'].split(' ')[0]}</div>
                    <div class="{cls}" style="font-size:0.9rem; font-weight:bold;">{s_prof:+,.0f}</div>
                    <div class="{cls}" style="font-size:0.75rem;">({s_roi:+.1f}%)</div>
                </div>""", unsafe_allow_html=True)
        
        st.markdown("---")
        for code, info in SECTORS.items():
            s_df = df_combined[df_combined['Sector'] == code]
            if s_df.empty: continue
            st.markdown(f"**{info['emoji']} {info['name']}**")
            cols = st.columns(4)
            for idx, row in enumerate(s_df.itertuples()):
                with cols[idx % 4]:
                    r_roi = row.Total_Profit / row.Principal * 100 if row.Principal else 0
                    cls = "c-red" if row.Total_Profit > 0 else "c-blue" if row.Total_Profit < 0 else "c-gray"
                    sym = "▲" if row.Total_Profit > 0 else "▼" if row.Total_Profit < 0 else "-"
                    
                    margin_html = f'<span class="badge-margin bg-gray-light">∞</span>' if row.Ticker=='💵 USD CASH' else \
                                  f'<span class="badge-margin bg-green-light">안전 +{row.Safety_Margin:,.0f}</span>' if row.Safety_Margin > 0 else \
                                  f'<span class="badge-margin bg-red-light">위험 {row.Safety_Margin:,.0f}</span>'
                    
                    st.markdown(f"""
                    <div class="stock-card">
                        <div class="card-header"><span class="ticker-name">{row.Ticker}</span><span class="full-name">{row.Name}</span></div>
                        <div class="main-val">{row.Eval:,.0f}</div>
                        <div class="profit-row {cls}">{sym} {abs(row.Total_Profit):,.0f} ({r_roi:+.1f}%)</div>
                        <div style="text-align:right;">{margin_html}</div>
                    </div>""", unsafe_allow_html=True)
                    
                    with st.popover("🔍", use_container_width=True):
                        st.markdown(f"**{row.Ticker} 상세**")
                        st.divider()
                        st.write(f"💰 원금: {row.Principal:,.0f}"); st.write(f"💵 평가: {row.Eval:,.0f}"); st.write(f"📈 손익: {row.Total_Profit:,.0f}")
                        st.divider()
                        st.write(f"📉 주가: {row.Price_Profit:,.0f}"); st.write(f"💱 환율: {row.FX_Profit:,.0f}"); st.write(f"🏦 배당: {row.Div_Profit:,.0f}")

    with sub_html:
        def make_html(df):
            rows = ""
            for _, row in df.iterrows():
                c = "red" if row['Total_Profit'] > 0 else "blue" if row['Total_Profit'] < 0 else "zero"
                def vf(v): return f'<span class="{c}">{v:,.0f}</span>'
                rows += f"<tr><td style='text-align:left'><b>{row['Ticker']}</b><br><span style='font-size:0.8em;color:gray'>{row['Name']}</span></td>"
                rows += f"<td>{vf(row['Price_Profit'])}</td><td>{vf(row['FX_Profit'])}</td><td>{vf(row['Total_Profit'])}</td>"
                rows += f"<td><b>{row['Safety_Margin']:+.1f}</b></td></tr>"
            
            # 합계
            s_p = df['Price_Profit'].sum(); s_f = df['FX_Profit'].sum(); s_t = df['Total_Profit'].sum()
            def sf(v): return f'<span class="{"red" if v>0 else "blue"}"><b>{v:,.0f}</b></span>'
            rows += f"<tr style='background:#fafafa; border-top:2px solid #aaa;'><td style='text-align:left'>🔴 <b>TOTAL</b></td><td>{sf(s_p)}</td><td>{sf(s_f)}</td><td>{sf(s_t)}</td><td>-</td></tr>"
            
            return f"""<style>.red{{color:#D32F2F;font-weight:bold}}.blue{{color:#1976D2;font-weight:bold}}.zero{{color:#ccc}}table{{width:100%;border-collapse:collapse;font-size:0.9em}}th{{background:#f0f2f6;padding:10px;text-align:right;border-bottom:2px solid #ccc}}td{{padding:10px;border-bottom:1px solid #eee;text-align:right}}</style><table><thead><tr><th style='text-align:left'>종목</th><th>주가손익</th><th>환손익</th><th>합계손익</th><th>안전마진</th></tr></thead><tbody>{rows}</tbody></table>"""
        st.markdown(make_html(df_combined), unsafe_allow_html=True)

    with sub_detail:
        st.dataframe(df_combined[['Ticker','Principal','Eval','Price_Profit','FX_Profit','Total_Profit','Safety_Margin']], use_container_width=True)

# ===================================================================
# [PAGE 2] 입력 매니저
# ===================================================================
with main_tab2:
    st.subheader("데이터 입력")
    
    # 세션 로그 표시 (롤백 대체 기능)
    if st.session_state['input_log']:
        st.info("📋 **이번 접속 세션 입력 내역 (성공)**")
        for log in st.session_state['input_log']:
            st.caption(f"✅ {log}")
        st.divider()

    col_date, col_text = st.columns([1, 2])
    with col_date:
        input_date = st.date_input("거래 날짜", datetime.now())
        is_dividend = st.checkbox("배당금 입력 모드")
        manual_rate = 0.0
        if is_dividend:
            try: today_rate = yf.Ticker("USDKRW=X").history(period="1d")['Close'].iloc[-1]
            except: today_rate = 1450.0
            manual_rate = st.number_input("배당 적용 환율", value=float(round(today_rate, 2)), step=0.1, format="%.2f")
    
    with col_text:
        raw_text = st.text_area("카톡/텍스트 붙여넣기", height=150)
    
    if st.button("분석 및 저장", type="primary"):
        if raw_text:
            try:
                sh = get_client()
                curr_avg_rate = calculate_metrics_live(sh)
                ts = datetime.now().strftime('%Y%m%d%H%M%S')
                
                log_msg = ""
                
                if "배당" in raw_text or is_dividend:
                    # 배당 처리
                    tk = re.search(r'([A-Z]+)/', raw_text); amt = re.search(r'USD ([\d,.]+)', raw_text)
                    t_val = tk.group(1) if tk else "UNKNOWN"; a_val = float(amt.group(1).replace(',','')) if amt else 0
                    if a_val > 0:
                        sh.worksheet("Dividend_Log").append_row([str(input_date), ts, t_val, a_val, manual_rate, "카톡파싱"])
                        log_msg = f"배당: {t_val} ${a_val} (@{manual_rate}원)"
                
                elif "외화매수환전" in raw_text:
                    # 환전 처리
                    krw = re.search(r'￦([\d,]+)', raw_text); usd = re.search(r'USD ([\d,.]+)', raw_text)
                    if krw and usd:
                        k_val = int(krw.group(1).replace(',','')); u_val = float(usd.group(1).replace(',',''))
                        rate = k_val / u_val
                        sh.worksheet("Exchange_Log").append_row([str(input_date), ts, "KRW_to_USD", k_val, u_val, rate, "", "", "카톡파싱"])
                        log_msg = f"환전: ${u_val} (환율 {rate:.1f}원)"

                elif "체결안내" in raw_text:
                    # 매수 처리
                    tk = re.search(r'\*종목명:([A-Z]+)/', raw_text); qt = re.search(r'\*체결수량:([\d]+)', raw_text); pr = re.search(r'\*체결단가:USD ([\d.]+)', raw_text)
                    if tk:
                        t_val = tk.group(1); q_val = int(qt.group(1)); p_val = float(pr.group(1))
                        sh.worksheet("Trade_Log").append_row([str(input_date), ts, t_val, t_val, "Buy", q_val, p_val, curr_avg_rate, "카톡파싱"])
                        log_msg = f"매수: {t_val} {q_val}주 (${p_val}) - 평단 {curr_avg_rate:.1f}원 적용"

                if log_msg:
                    st.session_state['input_log'].append(log_msg)
                    st.success(f"저장 완료! ({log_msg})")
                    st.balloons()
                    # 데이터 갱신을 위해 캐시 클리어
                    st.cache_data.clear()
                else:
                    st.error("형식을 인식할 수 없습니다.")
                    
            except Exception as e:
                st.error(f"오류: {e}")
