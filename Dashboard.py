import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import re
import yfinance as yf
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# [1] 설정 & 스타일 (기존 UI 유지)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="🏦")

# [세션 상태 초기화]
if 'price_cache' not in st.session_state: st.session_state['price_cache'] = {}
if 'last_update' not in st.session_state: st.session_state['last_update'] = None

# [색상 팔레트]
THEME_BG = "#131314"
THEME_CARD = "#18181A"
THEME_BORDER = "#444746"
THEME_TEXT = "#E3E3E3"
THEME_SUB = "#C4C7C5"

COLOR_RED = "#FF5252"
COLOR_BLUE = "#448AFF"
COLOR_BG_RED = "rgba(255, 82, 82, 0.15)"
COLOR_BG_BLUE = "rgba(68, 138, 255, 0.15)"

st.markdown(f"""
<style>
    .stApp {{ background-color: {THEME_BG} !important; color: {THEME_TEXT} !important; }}
    header {{visibility: hidden;}}
    .block-container {{ padding-top: 1.5rem; }}
    
    /* KPI */
    .kpi-container {{ display: grid; grid-template-columns: 2fr 1.5fr 1.5fr; gap: 16px; margin-bottom: 24px; }}
    .kpi-card {{ background-color: {THEME_CARD}; padding: 24px; border-radius: 16px; border: 1px solid {THEME_BORDER}; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.2); }}
    .kpi-title {{ font-size: 0.95rem; color: {THEME_SUB}; margin-bottom: 8px; font-weight: 500; }}
    .kpi-main {{ font-size: 2.2rem; font-weight: 800; color: {THEME_TEXT}; letter-spacing: -0.5px; }}
    .kpi-sub {{ font-size: 1.1rem; margin-top: 8px; font-weight: 600; color: {THEME_SUB}; }}
    
    /* Utilities */
    .txt-red {{ color: {COLOR_RED} !important; }}
    .txt-blue {{ color: {COLOR_BLUE} !important; }}
    .txt-orange {{ color: #FF9800 !important; }}
    .bg-red {{ background-color: {COLOR_BG_RED} !important; }}
    .bg-blue {{ background-color: {COLOR_BG_BLUE} !important; }}
    
    /* Cards */
    .stock-card {{ background-color: {THEME_CARD}; border-radius: 16px; padding: 20px; margin-bottom: 16px; border: 1px solid {THEME_BORDER}; border-left: 6px solid #555; transition: transform 0.2s, box-shadow 0.2s; }}
    .stock-card:hover {{ transform: translateY(-4px); box-shadow: 0 6px 12px rgba(0,0,0,0.4); }}
    .card-up {{ border-left-color: {COLOR_RED} !important; }}
    .card-down {{ border-left-color: {COLOR_BLUE} !important; }}
    .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
    .card-ticker {{ font-size: 1.4rem; font-weight: 900; color: {THEME_TEXT}; }}
    .card-price {{ font-size: 1.1rem; font-weight: 500; color: {THEME_SUB}; }}
    .card-main-val {{ font-size: 1.6rem; font-weight: 800; color: {THEME_TEXT}; text-align: right; margin-bottom: 4px; letter-spacing: -0.5px; }}
    .card-sub-box {{ text-align: right; font-size: 1.0rem; font-weight: 600; }}
    
    /* Tables */
    .int-table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; text-align: right; color: {THEME_TEXT}; }}
    .int-table th {{ background-color: #252627; color: {THEME_SUB}; padding: 14px 10px; text-align: right; border-bottom: 1px solid {THEME_BORDER}; font-weight: 600; }}
    .int-table th:first-child {{ text-align: left; }}
    .int-table td {{ padding: 12px 10px; border-bottom: 1px solid #2D2E30; }}
    .int-table td:first-child {{ text-align: left; font-weight: 700; color: #A8C7FA; }}
    .row-total {{ background-color: #2A2B2D; font-weight: 800; border-top: 2px solid {THEME_BORDER}; }}
    .row-cash {{ background-color: {THEME_BG}; font-style: italic; color: {THEME_SUB}; }}

    /* Streamlit Overrides */
    .stTabs [data-baseweb="tab-list"] {{ gap: 8px; }}
    .stTabs [data-baseweb="tab"] {{ background-color: {THEME_CARD}; border-radius: 8px; color: {THEME_SUB}; padding: 6px 16px; border: 1px solid {THEME_BORDER}; }}
    .stTabs [aria-selected="true"] {{ background-color: #3C4043 !important; color: #A8C7FA !important; border-color: #A8C7FA !important; }}
    
    /* Input Fields Fix */
    [data-testid="stForm"] {{ background-color: {THEME_CARD}; border: 1px solid {THEME_BORDER}; border-radius: 16px; padding: 24px; }}
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"], .stTextArea textarea {{ 
        color: {THEME_TEXT} !important; 
        background-color: #252627 !important; 
        border-color: {THEME_BORDER} !important;
    }}
    .stTextInput label, .stNumberInput label, .stSelectbox label, .stRadio label, .stTextArea label {{ color: {THEME_SUB} !important; }}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# [2] 상수 및 데이터 정의
# -------------------------------------------------------------------
SECTOR_ORDER_LIST = {
    '배당': ['O', 'JEPI', 'JEPQ', 'SCHD', 'MAIN', 'KO'], 
    '테크': ['GOOGL', 'NVDA', 'AMD', 'TSM', 'MSFT', 'AAPL', 'AMZN', 'TSLA', 'AVGO', 'SOXL'],
    '리츠': ['PLD', 'AMT'],
    '기타': [] 
}
SORT_ORDER_TABLE = ['O', 'JEPI', 'JEPQ', 'GOOGL', 'NVDA', 'AMD', 'TSM']

# -------------------------------------------------------------------
# [3] 유틸리티 & 데이터 로드
# -------------------------------------------------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def safe_float(val):
    if pd.isna(val) or val == '' or val == '-': return 0.0
    try: return float(str(val).replace(',', '').strip())
    except: return 0.0

def load_data():
    client = get_gsheet_client()
    sh = client.open("Investment_Dashboard_DB")
    df_money = pd.DataFrame(sh.worksheet("Money_Log").get_all_records())
    df_trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
    
    df_money.columns = df_money.columns.str.strip()
    df_trade.columns = df_trade.columns.str.strip()

    cols_money = ['KRW_Amount', 'USD_Amount', 'Ex_Rate', 'Avg_Rate', 'Balance']
    for c in cols_money:
        if c in df_money.columns:
            df_money[c] = pd.to_numeric(df_money[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
    cols_trade = ['Qty', 'Price_USD', 'Ex_Avg_Rate']
    for c in cols_trade:
        if c in df_trade.columns:
            df_trade[c] = pd.to_numeric(df_trade[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    return df_trade, df_money, sh

def get_realtime_rate():
    try:
        # 환율도 세션에 캐싱하여 반복 호출 방지
        if 'fx_rate' not in st.session_state:
            ticker = yf.Ticker("KRW=X")
            data = ticker.history(period="1d")
            if not data.empty:
                st.session_state['fx_rate'] = data['Close'].iloc[-1]
            else:
                st.session_state['fx_rate'] = 1450.0
        return st.session_state['fx_rate']
    except: return 1450.0

# -------------------------------------------------------------------
# [4] 엔진: 달러 저수지 & 포트폴리오 계산
# -------------------------------------------------------------------
def process_timeline(df_trade, df_money):
    df_money['Source'] = 'Money'
    df_trade['Source'] = 'Trade'
    
    if 'Order_ID' not in df_money.columns: df_money['Order_ID'] = 0
    if 'Order_ID' not in df_trade.columns: df_trade['Order_ID'] = 0
    
    timeline = pd.concat([df_money, df_trade], ignore_index=True)
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    # 날짜 정렬
    timeline['Date'] = pd.to_datetime(timeline['Date'])
    timeline = timeline.sort_values(by=['Date', 'Order_ID'])
    
    current_balance = 0.0
    current_avg_rate = 0.0
    portfolio = {} 
    
    for idx, row in timeline.iterrows():
        source = row['Source']
        t_type = str(row.get('Type', '')).lower()
        
        if source == 'Money':
            usd_amt = safe_float(row.get('USD_Amount'))
            krw_amt = safe_float(row.get('KRW_Amount'))
            ticker = str(row.get('Ticker', '')).strip()
            if ticker == '' or ticker == '-' or ticker == 'nan': ticker = 'Cash'
            
            if 'dividend' in t_type or '배당' in t_type:
                if ticker != 'Cash':
                    if ticker not in portfolio: 
                        portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_usd':0, 'realized_krw':0, 'accum_div_usd':0}
                    portfolio[ticker]['accum_div_usd'] += usd_amt
            
            current_balance += usd_amt
            if current_balance > 0.0001:
                prev_val = (current_balance - usd_amt) * current_avg_rate
                added_val = 0 if ('dividend' in t_type or '배당' in t_type) else krw_amt
                current_avg_rate = (prev_val + added_val) / current_balance

        elif source == 'Trade':
            qty = safe_float(row.get('Qty'))
            price = safe_float(row.get('Price_USD'))
            amount = qty * price
            ticker = str(row.get('Ticker', '')).strip()
            
            if ticker not in portfolio: 
                portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_usd':0, 'realized_krw':0, 'accum_div_usd':0}
            
            if 'buy' in t_type or '매수' in t_type:
                current_balance -= amount
                ex_rate = safe_float(row.get('Ex_Avg_Rate'))
                if ex_rate == 0: 
                    ex_rate = current_avg_rate
                
                portfolio[ticker]['qty'] += qty
                portfolio[ticker]['invested_krw'] += (amount * ex_rate)
                portfolio[ticker]['invested_usd'] += amount 
                
            elif 'sell' in t_type or '매도' in t_type:
                current_balance += amount
                sell_val_krw = amount * current_avg_rate 
                
                if portfolio[ticker]['qty'] > 0:
                    avg_unit_invest_krw = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                    cost_krw = qty * avg_unit_invest_krw
                    
                    avg_unit_invest_usd = portfolio[ticker]['invested_usd'] / portfolio[ticker]['qty']
                    cost_usd = qty * avg_unit_invest_usd
                    
                    pl_krw = sell_val_krw - cost_krw
                    portfolio[ticker]['realized_krw'] += pl_krw
                    
                    portfolio[ticker]['qty'] -= qty
                    portfolio[ticker]['invested_krw'] -= cost_krw
                    portfolio[ticker]['invested_usd'] -= cost_usd

    return df_trade, df_money, current_balance, current_avg_rate, portfolio

# -------------------------------------------------------------------
# [5] Main App
# -------------------------------------------------------------------
def main():
    try:
        df_trade, df_money, sheet_instance = load_data()
    except:
        st.error("DB 연결 실패.")
        st.stop()
        
    u_trade, u_money, cur_bal, cur_rate, portfolio = process_timeline(df_trade, df_money)
    cur_real_rate = get_realtime_rate()
    
    # [시세 조회 캐싱] - 화면 깜빡임 방지 Logic
    tickers = list(portfolio.keys())
    if tickers:
        # 캐시가 비어있거나, 종목이 추가되었을 때만 API 호출
        uncached = [t for t in tickers if t not in st.session_state['price_cache']]
        if uncached:
            with st.spinner("데이터 동기화 중..."):
                for t in uncached:
                    st.session_state['price_cache'][t] = kis.get_current_price(t)
        prices = st.session_state['price_cache']
    else:
        prices = {}
    
    # KPI Logic
    total_stock_val_krw = 0.0
    total_input_principal = df_money[df_money['Type'] == 'KRW_to_USD']['KRW_Amount'].apply(safe_float).sum()
    
    for tk, data in portfolio.items():
        if data['qty'] > 0:
            val_usd = data['qty'] * prices.get(tk, 0)
            total_stock_val_krw += (val_usd * cur_real_rate)

    total_asset_krw = total_stock_val_krw + (cur_bal * cur_real_rate)
    total_pl_krw = total_asset_krw - total_input_principal
    total_pl_pct = (total_pl_krw / total_input_principal * 100) if total_input_principal > 0 else 0
    
    total_realized_krw = sum(d['realized_krw'] for d in portfolio.values())
    total_div_usd = sum(d['accum_div_usd'] for d in portfolio.values())
    
    bep_numerator = total_input_principal - total_realized_krw - (total_div_usd * cur_real_rate)
    total_usd_assets = (total_stock_val_krw / cur_real_rate) + cur_bal
    bep_rate = bep_numerator / total_usd_assets if total_usd_assets > 0 else 0
    safety_margin = cur_real_rate - bep_rate

    # Header
    c1, c2 = st.columns([3, 1])
    with c1: st.title("🚀 Investment Command Center")
    with c2:
        # [수동 새로고침 버튼]
        if st.button("🔄 시세/데이터 새로고침"):
            st.session_state['price_cache'] = {} # 캐시 초기화
            if 'fx_rate' in st.session_state: del st.session_state['fx_rate']
            st.cache_resource.clear()
            st.rerun()

    # KPI UI
    st.markdown(f"""
    <div class="kpi-container">
        <div class="kpi-card">
            <div class="kpi-title">총 자산 (Total Assets)</div>
            <div class="kpi-main">₩ {total_asset_krw:,.0f}</div>
            <div class="kpi-sub {'txt-red' if total_pl_krw >= 0 else 'txt-blue'}">
                {'▲' if total_pl_krw >= 0 else '▼'} {abs(total_pl_krw):,.0f} &nbsp; {total_pl_pct:+.2f}%
            </div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">달러 잔고 (USD Balance)</div>
            <div class="kpi-main">$ {cur_bal:,.2f}</div>
            <div class="kpi-sub">매수환율: ₩ {cur_rate:,.2f}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">안전마진 (Safety Margin)</div>
            <div class="kpi-main {'txt-red' if safety_margin >= 0 else 'txt-blue'}">{safety_margin:+.2f} 원</div>
            <div class="kpi-sub">BEP: ₩ {bep_rate:,.2f}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 대시보드", "📋 통합 상세", "📜 통합 로그", "🕹️ 입력 매니저"])
    
    # [Tab 1] Dashboard (Card View + Detail Restore)
    with tab1:
        st.write("### 💳 Portfolio Status")
        for sec in ['배당', '테크', '리츠', '기타']:
            target_list = SECTOR_ORDER_LIST.get(sec, [])
            if sec == '기타':
                all_defined = [t for lst in SECTOR_ORDER_LIST.values() for t in lst]
                target_list = [t for t in portfolio.keys() if t not in all_defined and portfolio[t]['qty'] > 0]
            
            valid_tickers = [t for t in target_list if t in portfolio and portfolio[t]['qty'] > 0]
            if not valid_tickers: continue
            
            st.caption(f"**{sec}** Sector")
            cols = st.columns(4)
            for idx, tk in enumerate(valid_tickers):
                data = portfolio[tk]
                qty = data['qty']
                cur_p = prices.get(tk, 0)
                val_krw = qty * cur_p * cur_real_rate
                invested_krw = data['invested_krw']
                div_krw = data['accum_div_usd'] * cur_real_rate
                
                total_pl_tk = val_krw - invested_krw + data['realized_krw'] + div_krw
                total_ret = (total_pl_tk / invested_krw * 100) if invested_krw > 0 else 0
                
                bep_rate_tk = (invested_krw - data['realized_krw'] - div_krw) / (qty * cur_p) if (qty*cur_p) > 0 else 0
                margin_tk = cur_real_rate - bep_rate_tk
                
                is_plus = total_pl_tk >= 0
                color_cls = "card-up" if is_plus else "card-down"
                txt_cls = "txt-red" if is_plus else "txt-blue"
                arrow = "▲" if is_plus else "▼"
                sign = "+" if is_plus else ""
                
                html = f"""
                <div class="stock-card {color_cls}">
                    <div class="card-header">
                        <span class="card-ticker">{tk}</span>
                        <span class="card-price">${cur_p:.2f}</span>
                    </div>
                    <div class="card-main-val">₩ {val_krw:,.0f}</div>
                    <div class="card-sub-box {txt_cls}">
                        <span class="pl-amt">{arrow} {abs(total_pl_tk):,.0f}</span>
                        <span class="pl-pct">{sign}{total_ret:.1f}%</span>
                    </div>
                    <details>
                        <summary style="text-align:right; font-size:0.8rem; color:#888; cursor:pointer; margin-top:5px;">상세 내역</summary>
                        <table class="detail-table" style="width:100%; font-size:0.85rem; color:#ccc;">
                            <tr><td>보유수량</td><td style="text-align:right;">{qty:,.0f}</td></tr>
                            <tr><td>투자원금</td><td style="text-align:right;">₩ {invested_krw:,.0f}</td></tr>
                            <tr><td>누적실현</td><td style="text-align:right;">₩ {data['realized_krw']:,.0f}</td></tr>
                            <tr><td>누적배당</td><td style="text-align:right;">₩ {div_krw:,.0f}</td></tr>
                            <tr><td style="color:#AAA">안전마진</td><td style="text-align:right; color:{COLOR_RED if margin_tk >= 0 else COLOR_BLUE}">{margin_tk:+.1f} 원</td></tr>
                        </table>
                    </details>
                </div>
                """
                with cols[idx % 4]:
                    st.markdown(html, unsafe_allow_html=True)

    # [Tab 2] Integrated Table
    with tab2:
        header = "<table class='int-table'><thead><tr><th>종목</th><th>평가액 (₩)</th><th>평가손익</th><th>환손익</th><th>실현+배당</th><th>총 손익 (Total)</th><th>안전마진</th></tr></thead><tbody>"
        rows_html = ""
        
        all_keys = list(portfolio.keys())
        def sort_key(tk):
            if tk in SORT_ORDER_TABLE: return SORT_ORDER_TABLE.index(tk)
            return 999
        sorted_tickers = sorted(all_keys, key=sort_key)
        
        sum_eval_krw = 0; sum_realized = 0;
        
        for tk in sorted_tickers:
            if tk == 'Cash': continue
            data = portfolio[tk]
            qty = data['qty']
            cur_p = prices.get(tk, 0)
            
            if qty == 0 and data['realized_krw'] == 0 and data['accum_div_usd'] == 0:
                continue

            eval_krw = qty * cur_p * cur_real_rate
            invested_krw = data['invested_krw']
            invested_usd = data['invested_usd']
            div_krw = data['accum_div_usd'] * cur_real_rate
            
            total_pl = eval_krw - invested_krw + data['realized_krw'] + div_krw
            
            if qty > 0:
                my_avg_rate_tk = invested_krw / invested_usd if invested_usd > 0 else 0
                fx_profit = invested_usd * (cur_real_rate - my_avg_rate_tk)
                val_usd = qty * cur_p
                price_profit = (val_usd - invested_usd) * cur_real_rate
            else:
                fx_profit = 0
                price_profit = 0

            realized_total = data['realized_krw'] + div_krw
            bep_tk = (invested_krw - realized_total) / (qty * cur_p) if (qty*cur_p) > 0 else 0
            margin_tk = cur_real_rate - bep_tk if qty > 0 else 0
            
            cls_price = "txt-red" if price_profit >= 0 else "txt-blue"
            cls_fx = "txt-red" if fx_profit >= 0 else "txt-blue"
            cls_tot = "txt-red" if total_pl >= 0 else "txt-blue"
            bg_cls = "bg-red" if total_pl >= 0 else "bg-blue"
            
            sum_eval_krw += eval_krw
            sum_realized += realized_total
            
            margin_str = f"{margin_tk:+.1f}" if qty > 0 else "-"
            
            rows_html += f"<tr><td>{tk}</td><td>{eval_krw:,.0f}</td><td class='{cls_price}'>{price_profit:,.0f}</td><td class='{cls_fx}'>{fx_profit:,.0f}</td><td>{realized_total:,.0f}</td><td class='{cls_tot} {bg_cls}'><b>{total_pl:,.0f}</b></td><td>{margin_str}</td></tr>"
            
        cash_krw = cur_bal * cur_real_rate
        final_pl_calc = (sum_eval_krw + cash_krw) - total_input_principal
        cls_fin = "txt-red" if final_pl_calc >= 0 else "txt-blue"
        
        cash_row = f"<tr class='row-cash'><td>Cash (USD)</td><td>{cash_krw:,.0f}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
        total_row = f"<tr class='row-total'><td>TOTAL</td><td>{(sum_eval_krw + cash_krw):,.0f}</td><td>-</td><td>-</td><td>{sum_realized:,.0f}</td><td class='{cls_fin}'>{final_pl_calc:,.0f}</td><td>{safety_margin:+.1f}</td></tr>"
        
        full_table = header + rows_html + cash_row + total_row + "</tbody></table>"
        st.markdown(full_table, unsafe_allow_html=True)

    with tab3:
        st.dataframe(u_trade[['Date', 'Ticker', 'Type', 'Qty', 'Price_USD', 'Note']].fillna(''), use_container_width=True)
        st.dataframe(u_money[['Date', 'Type', 'USD_Amount', 'KRW_Amount', 'Note']].fillna(''), use_container_width=True)

    # ---------------------------------------------------------
    # [Tab 4] Input Manager (1월 28일 구버전 로직 부활)
    # ---------------------------------------------------------
    with tab4:
        st.subheader("📝 입출금 및 배당 관리")
        mode = st.radio("입력 모드", ["💬 카카오톡 파싱 (추천)", "✍️ 수기 입력"], horizontal=True)
        st.divider()
        
        if mode == "💬 카카오톡 파싱 (추천)":
            c1, c2 = st.columns([1, 2])
            with c1:
                ref_date = st.date_input("📅 기준 날짜 (카톡 수신일)", datetime.now())
            with c2:
                st.info("카톡 내용을 복사해서 아래에 붙여넣으세요. '저장하기' 버튼을 누르면 즉시 DB에 저장됩니다.")
            
            raw_text = st.text_area("카톡 내용 붙여넣기", height=200, placeholder="[한국투자증권 체결안내]08:05\n...")
            
            # [구버전 스타일 복구] : 분석 과정을 거치지 않고 바로 쏘는 버튼 하나만 존재
            if st.button("🚀 저장하기 (분석 및 DB전송)", type="primary"):
                if raw_text:
                    ws_trade = sheet_instance.worksheet("Trade_Log")
                    ws_money = sheet_instance.worksheet("Money_Log")
                    
                    # Max ID 계산
                    max_id = max(pd.to_numeric(u_trade['Order_ID']).max(), pd.to_numeric(u_money['Order_ID']).max())
                    next_id = int(max_id) + 1
                    
                    count = 0
                    base_year = ref_date.year
                    
                    # 텍스트 전처리
                    full_text = raw_text.replace('\r', '')
                    
                    # 1. 매수/매도 파싱 (구버전 로직 + 시간보정)
                    # 구버전처럼 split 활용하되, 정규식으로 안전하게 추출
                    trade_blocks = re.split(r'\[한국투자증권 체결안내\]', full_text)
                    for block in trade_blocks:
                        if "종목명" not in block: continue
                        try:
                            # 시간 추출 (블록 맨 앞)
                            time_match = re.match(r'(\d{2}:\d{2})', block.strip())
                            time_str = time_match.group(1) if time_match else "00:00"
                            
                            type_m = re.search(r'\*매매구분:(매수|매도)', block)
                            name_m = re.search(r'\*종목명:([A-Za-z0-9 ]+)(?:/|$)', block)
                            qty_m = re.search(r'\*체결수량:(\d+)', block)
                            price_m = re.search(r'\*체결단가:USD\s*([\d.]+)', block)
                            
                            if type_m and name_m and qty_m and price_m:
                                # 시간 보정: 전날 23:30
                                trade_dt = datetime.combine(ref_date, datetime.min.time()) - timedelta(days=1)
                                final_dt = trade_dt.strftime("%Y-%m-%d 23:30:00")
                                
                                t_type = "Buy" if type_m.group(1) == "매수" else "Sell"
                                
                                # [중요] Python Native Type으로 변환하여 저장
                                ws_trade.append_row([
                                    str(final_dt),
                                    int(next_id),
                                    str(name_m.group(1).strip()),
                                    str(name_m.group(1).strip()),
                                    str(t_type),
                                    int(qty_m.group(1)),
                                    float(price_m.group(1)),
                                    "", 
                                    f"카톡파싱_{time_str}"
                                ])
                                next_id += 1
                                count += 1
                        except: continue

                    # 2. 배당 파싱
                    div_pattern = re.compile(r'최원준님\s*(\d{2}/\d{2}).*?([A-Z]+)/.*?USD\s*([\d.]+)\s*세전배당입금', re.DOTALL)
                    for match in div_pattern.finditer(full_text):
                        try:
                            date_part, ticker, amount = match.groups()
                            m, d = map(int, date_part.split('/'))
                            div_dt = datetime(base_year, m, d, 15, 0, 0) # 오후 3시
                            
                            ws_money.append_row([
                                div_dt.strftime("%Y-%m-%d %H:%M:%S"),
                                int(next_id),
                                "Dividend",
                                str(ticker.strip()),
                                0, # KRW
                                float(amount),
                                0, "", "", "카톡파싱_배당"
                            ])
                            next_id += 1
                            count += 1
                        except: continue

                    # 3. 환전 파싱
                    exch_pattern = re.compile(r'외화매수환전.*?￦([0-9,]+).*?@([0-9,.]+).*?USD\s*([0-9,.]+)', re.DOTALL)
                    for match in exch_pattern.finditer(full_text):
                        try:
                            krw_str, rate_str, usd_str = match.groups()
                            exch_dt = datetime.combine(ref_date, datetime.min.time()).replace(hour=14, minute=0) # 오후 2시
                            
                            ws_money.append_row([
                                exch_dt.strftime("%Y-%m-%d %H:%M:%S"),
                                int(next_id),
                                "KRW_to_USD",
                                "-",
                                float(krw_str.replace(',', '')),
                                float(usd_str.replace(',', '')),
                                float(rate_str.replace(',', '')),
                                "", "", "카톡파싱_환전"
                            ])
                            next_id += 1
                            count += 1
                        except: continue
                        
                    if count > 0:
                        st.success(f"✅ {count}건 저장 완료! (캐시 초기화됨)")
                        st.session_state['price_cache'] = {}
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.warning("⚠️ 저장할 내역을 찾지 못했습니다. 텍스트를 확인해주세요.")

        else:
            with st.form("input_form"):
                col1, col2 = st.columns(2)
                i_date = col1.date_input("날짜", datetime.now())
                i_usd = col2.number_input("금액 (USD)", min_value=0.01, step=0.01, format="%.2f")
                i_krw = st.number_input("입금 원화 (KRW)", min_value=0, step=100)
                i_ticker = st.text_input("종목코드 (배당 시)")
                i_type = st.selectbox("유형", ["KRW_to_USD", "Dividend", "Withdraw"])
                i_note = st.text_input("비고", value="수기입력")
                
                if st.form_submit_button("💾 저장하기"):
                    max_id = max(pd.to_numeric(u_trade['Order_ID']).max(), pd.to_numeric(u_money['Order_ID']).max())
                    next_id = int(max_id) + 1
                    rate = i_krw / i_usd if i_type=="KRW_to_USD" and i_usd > 0 else 0
                    
                    sheet_instance.worksheet("Money_Log").append_row([
                        i_date.strftime("%Y-%m-%d"), int(next_id), i_type, i_ticker,
                        int(i_krw), float(i_usd), float(rate), "", "", i_note
                    ])
                    st.success("저장 완료!")
                    st.session_state['price_cache'] = {}
                    time.sleep(1)
                    st.rerun()

if __name__ == "__main__":
    main()
