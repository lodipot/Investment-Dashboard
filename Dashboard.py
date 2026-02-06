import streamlit as st
import pandas as pd
import gspread
import requests  # 엑스레이 진단용
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta # [Fix] timedelta 추가됨
import time
import yfinance as yf
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# [1] 설정 & 스타일 (Gemini Theme Fixed)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="🏦")

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
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] {{ 
        color: {THEME_TEXT} !important; 
        background-color: #252627 !important; 
        border-color: {THEME_BORDER} !important;
    }}
    .stTextInput label, .stNumberInput label, .stSelectbox label, .stRadio label {{ color: {THEME_SUB} !important; }}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# [2] 상수 및 데이터 정의
# -------------------------------------------------------------------
SECTOR_MAP = {
    'GOOGL': '테크', 'NVDA': '테크', 'AMD': '테크', 'TSM': '테크', 'MSFT': '테크', 'AAPL': '테크', 'AMZN': '테크', 'TSLA': '테크', 'AVGO': '테크', 'SOXL': '테크',
    'O': '배당', 'JEPI': '배당', 'JEPQ': '배당', 'SCHD': '배당', 'MAIN': '배당', 'KO': '배당',
    'PLD': '리츠', 'AMT': '리츠'
}
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
        ticker = yf.Ticker("KRW=X")
        data = ticker.history(period="1d")
        if not data.empty:
            return data['Close'].iloc[-1]
    except: pass
    return 1450.0

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
    timeline['Date'] = pd.to_datetime(timeline['Date']) # 날짜 변환
    timeline = timeline.sort_values(by=['Date', 'Order_ID']) # Date 우선 정렬
    
    current_balance = 0.0
    current_avg_rate = 0.0
    portfolio = {} 
    
    for idx, row in timeline.iterrows():
        source = row['Source']
        t_type = str(row.get('Type', '')).lower()
        
        # --- Money Log ---
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
                
            # (Note: 화면 표시용 계산이므로 여기서 DB update는 안함)

        # --- Trade Log ---
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
                # DB에 값이 없으면 현재 평단 사용 (Fill-Forward 개념)
                rate_to_use = ex_rate if ex_rate > 0 else current_avg_rate
                
                portfolio[ticker]['qty'] += qty
                portfolio[ticker]['invested_krw'] += (amount * rate_to_use)
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
# [5] Sync Logic
# -------------------------------------------------------------------
def sync_api_data(sheet_instance, df_trade, df_money):
    ws_trade = sheet_instance.worksheet("Trade_Log")
    
    # 1. API 데이터 가져오기
    max_id = max(pd.to_numeric(df_trade['Order_ID'], errors='coerce').max(), pd.to_numeric(df_money['Order_ID'], errors='coerce').max())
    next_order_id = int(max_id) + 1 if not pd.isna(max_id) else 1
    
    # [Fix] 무조건 최근 30일치 재조회 (누락 방지)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=30)
    
    start_date_str = start_dt.strftime("%Y%m%d")
    end_date_str = end_dt.strftime("%Y%m%d")
    
    with st.spinner(f"API 데이터 수신 중... (기간: {start_date_str} ~ {end_date_str})"):
        res = kis.get_trade_history(start_date_str, end_date_str)
    
    new_rows = []
    if res and res.get('output1'):
        # 중복 방지 키 생성
        keys = set()
        for _, r in df_trade.iterrows():
            d = str(r['Date']).strip()
            t = str(r['Ticker']).strip()
            q = int(safe_float(r['Qty']))
            p = float(safe_float(r['Price_USD']))
            keys.add(f"{d}_{t}_{q}_{p:.4f}")

        for item in reversed(res['output1']):
            dt = datetime.strptime(item['dt'], "%Y%m%d").strftime("%Y-%m-%d")
            tk = item['pdno']
            qty = int(item['ccld_qty'])
            # 체결단가 (avg_prvs or ft_ccld_unpr3)
            price_raw = item.get('ft_ccld_unpr3', '0')
            price = float(price_raw)
            side = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
            
            check_key = f"{dt}_{tk}_{qty}_{price:.4f}"
            
            if check_key in keys: continue
            
            new_rows.append([dt, next_order_id, tk, item['prdt_name'], side, qty, price, "", "API_Auto"])
            keys.add(check_key)
            next_order_id += 1
            
    if new_rows:
        ws_trade.append_rows(new_rows)
        df_trade = pd.DataFrame(ws_trade.get_all_records())
        df_trade.columns = df_trade.columns.str.strip()
        for c in ['Qty', 'Price_USD', 'Ex_Avg_Rate']:
            if c in df_trade.columns:
                df_trade[c] = pd.to_numeric(df_trade[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    # 2. 빈칸 채우기 (Date 정렬)
    df_money['Source'] = 'Money'
    df_trade['Source'] = 'Trade'
    
    timeline = pd.concat([df_money, df_trade], ignore_index=True)
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    timeline['Date'] = pd.to_datetime(timeline['Date'])
    timeline = timeline.sort_values(by=['Date', 'Order_ID'])
    
    cur_bal = 0.0
    cur_avg = 0.0
    
    # 순차 계산 및 업데이트
    for idx, row in timeline.iterrows():
        source = row['Source']
        t_type = str(row.get('Type', '')).lower()
        oid = row['Order_ID']
        
        if source == 'Money':
            usd = safe_float(row.get('USD_Amount'))
            krw = safe_float(row.get('KRW_Amount'))
            
            cur_bal += usd
            if cur_bal > 0.0001:
                prev_val = (cur_bal - usd) * cur_avg
                added_val = 0 if ('dividend' in t_type or '배당' in t_type) else krw
                cur_avg = (prev_val + added_val) / cur_bal
            
            if safe_float(row.get('Avg_Rate')) == 0:
                df_money.loc[df_money['Order_ID'] == oid, 'Avg_Rate'] = cur_avg
            if safe_float(row.get('Balance')) == 0:
                df_money.loc[df_money['Order_ID'] == oid, 'Balance'] = cur_bal
                
        elif source == 'Trade':
            qty = safe_float(row.get('Qty'))
            price = safe_float(row.get('Price_USD'))
            amount = qty * price
            
            if 'buy' in t_type or '매수' in t_type:
                cur_bal -= amount
                if safe_float(row.get('Ex_Avg_Rate')) == 0:
                    df_trade.loc[df_trade['Order_ID'] == oid, 'Ex_Avg_Rate'] = cur_avg
            elif 'sell' in t_type or '매도' in t_type:
                cur_bal += amount

    # 3. Google Sheet Bulk Update
    ws_money = sheet_instance.worksheet("Money_Log")
    
    if 'Date' in df_trade.columns: df_trade['Date'] = df_trade['Date'].astype(str)
    if 'Source' in df_trade.columns: df_trade = df_trade.drop(columns=['Source'])
    if 'Source' in df_money.columns: df_money = df_money.drop(columns=['Source'])
    
    ws_trade.update([df_trade.columns.values.tolist()] + df_trade.astype(str).values.tolist())
    ws_money.update([df_money.columns.values.tolist()] + df_money.astype(str).values.tolist())
    
    st.toast(f"✅ 동기화 완료 ({len(new_rows)}건 추가)")
    time.sleep(1)
    st.rerun()

# -------------------------------------------------------------------
# [6] Main App
# -------------------------------------------------------------------
def main():
    try:
        df_trade, df_money, sheet_instance = load_data()
    except:
        st.error("DB 연결 실패.")
        st.stop()
        
    u_trade, u_money, cur_bal, cur_rate, portfolio = process_timeline(df_trade, df_money)
    cur_real_rate = get_realtime_rate()
    
    tickers = list(portfolio.keys())
    prices = {}
    if tickers:
        with st.spinner("시장가 조회 중..."):
            for t in tickers:
                prices[t] = kis.get_current_price(t)
    
    # 지표 계산
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
    now = datetime.now()
    status = "🟢 Live" if (23 <= now.hour or now.hour < 6) else "🔴 Closed"
    with c1:
        st.title("🚀 Investment Command Center")
        st.caption(f"{status} | {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # ---------------------------------------------------------
    # [🩺 API 진단 키트] - 버튼 누르면 원본 데이터 확인 가능
    # ---------------------------------------------------------
    with st.expander("🩺 API 데이터 엑스레이 (디버깅용)", expanded=False):
        col_d1, col_d2 = st.columns([1, 3])
        if col_d1.button("데이터 강제 조회"):
            token = kis.get_access_token()
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {token}",
                "appkey": st.secrets["kis_api"]["APP_KEY"],
                "appsecret": st.secrets["kis_api"]["APP_SECRET"],
                "tr_id": "TTTS3012R", # 체결내역
                "custtype": "P"
            }
            # 2월 1일부터 조회
            params = {
                "CANO": st.secrets["kis_api"]["CANO"],
                "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"],
                "ORD_DT_S": "20260201",
                "ORD_DT_E": datetime.now().strftime("%Y%m%d"),
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            url = f"{st.secrets['kis_api']['URL_BASE']}/uapi/overseas-stock/v1/trading/inquire-period-ccld"
            st.write(f"Request: {url}")
            try:
                res = requests.get(url, headers=headers, params=params)
                if res.status_code == 200:
                    st.success("호출 성공")
                    st.json(res.json())
                else:
                    st.error(f"호출 실패: {res.status_code}")
                    st.text(res.text)
            except Exception as e:
                st.error(f"에러 발생: {e}")

    with c2:
        if st.button("🔄 API Sync"):
            sync_api_data(sheet_instance, u_trade, u_money)

    # KPI Cube
    kpi_html = f"""
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
            <div style="color: #FF9800; font-size: 0.9rem; margin-top: 4px;">현재환율: ₩ {cur_real_rate:,.2f}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">안전마진 (Safety Margin)</div>
            <div class="kpi-main {'txt-red' if safety_margin >= 0 else 'txt-blue'}">{safety_margin:+.2f} 원</div>
            <div class="kpi-sub">BEP: ₩ {bep_rate:,.2f}</div>
        </div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 대시보드", "📋 통합 상세", "📜 통합 로그", "🕹️ 입력 매니저"])
    
    # [Tab 1] Cards
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
                        <table class="detail-table">
                            <tr><td>보유수량</td><td class="text-right">{qty:,.0f}</td></tr>
                            <tr><td>투자원금</td><td class="text-right">₩ {invested_krw:,.0f}</td></tr>
                            <tr><td>누적실현</td><td class="text-right">₩ {data['realized_krw']:,.0f}</td></tr>
                            <tr><td>누적배당</td><td class="text-right">₩ {div_krw:,.0f}</td></tr>
                            <tr><td style="color:#AAA">안전마진</td><td class="text-right {txt_cls}">{margin_tk:+.1f} 원</td></tr>
                        </table>
                    </details>
                </div>
                """
                with cols[idx % 4]:
                    st.markdown(html, unsafe_allow_html=True)
                idx += 1

    # [Tab 2] Integrated Table
    with tab2:
        header = "<table class='int-table'><thead><tr><th>종목</th><th>평가액 (₩)</th><th>평가손익</th><th>환손익</th><th>실현+배당</th><th>총 손익 (Total)</th><th>안전마진</th></tr></thead><tbody>"
        
        all_keys = list(portfolio.keys())
        def sort_key(tk):
            if tk in SORT_ORDER_TABLE: return SORT_ORDER_TABLE.index(tk)
            return 999
        sorted_tickers = sorted(all_keys, key=sort_key)
        
        sum_eval_krw = 0; sum_eval_pl = 0; sum_realized = 0; sum_total_pl = 0
        rows_html = ""
        
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
            sum_eval_pl += price_profit
            sum_realized += realized_total
            sum_total_pl += total_pl
            
            margin_str = f"{margin_tk:+.1f}" if qty > 0 else "-"
            
            rows_html += f"<tr><td>{tk}</td><td>{eval_krw:,.0f}</td><td class='{cls_price}'>{price_profit:,.0f}</td><td class='{cls_fx}'>{fx_profit:,.0f}</td><td>{realized_total:,.0f}</td><td class='{cls_tot} {bg_cls}'><b>{total_pl:,.0f}</b></td><td>{margin_str}</td></tr>"
            
        cash_krw = cur_bal * cur_real_rate
        final_pl_calc = (sum_eval_krw + cash_krw) - total_input_principal
        cls_fin = "txt-red" if final_pl_calc >= 0 else "txt-blue"
        
        cash_row = f"<tr class='row-cash'><td>Cash (USD)</td><td>{cash_krw:,.0f}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
        total_row = f"<tr class='row-total'><td>TOTAL</td><td>{(sum_eval_krw + cash_krw):,.0f}</td><td>-</td><td>-</td><td>{sum_realized:,.0f}</td><td class='{cls_fin}'>{final_pl_calc:,.0f}</td><td>{safety_margin:+.1f}</td></tr>"
        
        full_table = header + rows_html + cash_row + total_row + "</tbody></table>"
        st.markdown(full_table, unsafe_allow_html=True)

    # [Tab 3] Log
    with tab3:
        merged_log = pd.concat([u_money, u_trade], ignore_index=True)
        merged_log['Order_ID'] = pd.to_numeric(merged_log['Order_ID']).fillna(0)
        merged_log = merged_log.sort_values(['Date', 'Order_ID'], ascending=[False, False])
        st.dataframe(merged_log.fillna(''), use_container_width=True)

    # [Tab 4] Input Manager
    with tab4:
        st.subheader("📝 입출금 및 배당 관리")
        mode = st.radio("입력 유형", ["💰 환전 (입금)", "🏦 배당 (수령)"], horizontal=True, label_visibility="collapsed")
        st.divider()
        with st.form("input_form"):
            col1, col2 = st.columns(2)
            i_date = col1.date_input("날짜", datetime.now())
            i_usd = col2.number_input("금액 (USD)", min_value=0.01, step=0.01, format="%.2f")
            
            if mode == "💰 환전 (입금)":
                i_krw = st.number_input("입금 원화 (KRW)", min_value=0, step=100)
                if i_usd > 0:
                    st.caption(f"💡 적용 환율: 1 USD = {(i_krw/i_usd):,.2f} KRW")
                i_ticker = "-"
                i_type = "KRW_to_USD"
            else:
                holding_list = list(portfolio.keys())
                if 'Cash' in holding_list: holding_list.remove('Cash')
                if holding_list:
                    selected = st.selectbox("배당 종목 선택", options=holding_list + ["(직접 입력)"])
                    i_ticker = st.text_input("종목코드") if selected == "(직접 입력)" else selected
                else:
                    i_ticker = st.text_input("종목코드 입력")
                i_krw = 0
                i_type = "Dividend"
            
            i_note = st.text_input("비고", value="수기입력")
            
            if st.form_submit_button("💾 저장하기", use_container_width=True):
                if mode == "🏦 배당 (수령)" and not i_ticker:
                    st.error("종목코드를 입력해주세요.")
                else:
                    max_id = max(pd.to_numeric(u_trade['Order_ID']).max(), pd.to_numeric(u_money['Order_ID']).max())
                    next_id = int(max_id) + 1
                    rate = i_krw / i_usd if i_type=="KRW_to_USD" and i_usd > 0 else 0
                    
                    ws_money = sheet_instance.worksheet("Money_Log")
                    ws_money.append_row([
                        i_date.strftime("%Y-%m-%d"), next_id, i_type, i_ticker,
                        i_krw, i_usd,
                        rate, "", "", i_note
                    ])
                    st.success("✅ 저장되었습니다! 상단의 [API Sync] 버튼을 눌러 반영하세요.")

if __name__ == "__main__":
    main()
