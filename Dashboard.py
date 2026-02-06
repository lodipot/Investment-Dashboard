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
# [1] 설정 & 스타일
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

st.markdown(f"""
<style>
    .stApp {{ background-color: {THEME_BG} !important; color: {THEME_TEXT} !important; }}
    /* KPI */
    .kpi-container {{ display: grid; grid-template-columns: 2fr 1.5fr 1.5fr; gap: 16px; margin-bottom: 24px; }}
    .kpi-card {{ background-color: {THEME_CARD}; padding: 24px; border-radius: 16px; border: 1px solid {THEME_BORDER}; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.2); }}
    .kpi-title {{ font-size: 0.95rem; color: {THEME_SUB}; margin-bottom: 8px; font-weight: 500; }}
    .kpi-main {{ font-size: 2.2rem; font-weight: 800; color: {THEME_TEXT}; letter-spacing: -0.5px; }}
    .kpi-sub {{ font-size: 1.1rem; margin-top: 8px; font-weight: 600; color: {THEME_SUB}; }}
    
    /* Utilities */
    .txt-red {{ color: {COLOR_RED} !important; }}
    .txt-blue {{ color: {COLOR_BLUE} !important; }}
    
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
    
    # Date를 Datetime 객체로 변환하여 시간까지 정렬
    df_money['Date_Obj'] = pd.to_datetime(df_money['Date'])
    df_trade['Date_Obj'] = pd.to_datetime(df_trade['Date'])

    timeline = pd.concat([df_money, df_trade], ignore_index=True)
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    timeline = timeline.sort_values(by=['Date_Obj', 'Order_ID'])
    
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
# [5] Helper: 카톡 파싱 함수 (개선된 버전)
# -------------------------------------------------------------------
def parse_kakaotalk_v2(text, base_date):
    """
    단순 복사 텍스트 처리 최적화
    text: 카톡 복사 내용
    base_date: UI에서 선택한 기준 날짜 (datetime.date 객체)
    """
    parsed_data = []
    base_year = base_date.year
    
    # 텍스트 전처리 (줄바꿈 단위 분리)
    lines = text.split('\n')
    full_text = "\n".join(lines) # 다시 합쳐서 정규식 검색 용이하게

    # 1. 매수/매도 파싱
    # 패턴: [한국투자증권 체결안내]08:05 ... *매매구분:매도 ...
    # 구분자를 "체결안내"로 자릅니다.
    
    trade_blocks = full_text.split("체결안내")
    
    # 첫 번째 블록은 "체결안내" 전의 내용일 수 있으므로, 인덱스 1부터 보거나, 
    # split 결과에 키워드가 있는지 확인
    
    # 차라리 블록 단위 split 말고 전체에서 반복 매칭을 찾습니다.
    # 각 체결안내 블록은 "*계좌번호" 로 시작해서 "*제비용" 으로 끝나는 패턴을 가집니다.
    
    # 정규식으로 블록 추출 (체결안내 헤더 시간 포함)
    # 예: [한국투자증권 체결안내]08:05
    header_pattern = re.compile(r'\[한국투자증권 체결안내\](\d{2}:\d{2})')
    
    # 텍스트를 위에서부터 스캔하며 블록을 찾습니다.
    pos = 0
    while True:
        match = header_pattern.search(full_text, pos)
        if not match:
            break
        
        time_str = match.group(1) # 08:05
        start_idx = match.end()
        
        # 다음 헤더가 나오기 전까지, 혹은 텍스트 끝까지가 내용
        next_match = header_pattern.search(full_text, start_idx)
        if next_match:
            block_content = full_text[start_idx:next_match.start()]
            pos = next_match.start() # 다음 검색 위치 (현재 매치 시작점, 루프 돌면서 처리)
        else:
            block_content = full_text[start_idx:]
            pos = len(full_text)
            
        # 블록 내용 파싱
        try:
            type_m = re.search(r'\*매매구분:(매수|매도)', block_content)
            name_m = re.search(r'\*종목명:([A-Za-z0-9 ]+)(?:/|$)', block_content)
            qty_m = re.search(r'\*체결수량:(\d+)', block_content)
            price_m = re.search(r'\*체결단가:USD\s*([\d.]+)', block_content)
            
            if type_m and name_m and qty_m and price_m:
                # 시간 로직: 카톡 수신 시간(08:05)은 한국 아침 -> 미국장 기준 '전날' 23:30으로 설정
                # base_date가 '오늘(수신일)'이라고 가정
                trade_dt = datetime.combine(base_date, datetime.min.time()) - timedelta(days=1)
                final_dt = trade_dt.strftime("%Y-%m-%d 23:30:00") # 전날 미국장 개장시간
                
                parsed_data.append({
                    "Category": "Trade",
                    "Date": final_dt,
                    "Ticker": name_m.group(1).strip(),
                    "Type": "Buy" if type_m.group(1) == "매수" else "Sell",
                    "Qty": int(qty_m.group(1)),
                    "Price": float(price_m.group(1)),
                    "Amount_KRW": 0,
                    "Memo": f"체결알림 {time_str}"
                })
        except: pass
        
        if pos >= len(full_text): break

    # 2. 배당 파싱 (최원준님 02/05 ...)
    div_pattern = re.compile(r'최원준님\s*(\d{2}/\d{2}).*?([A-Z]+)/.*?USD\s*([\d.]+)\s*세전배당입금', re.DOTALL)
    for match in div_pattern.finditer(full_text):
        date_part, ticker, amount = match.groups()
        # 월/일만 있음 -> base_date의 연도와 결합
        # 시간은 알 수 없으므로 15:00 (오후) 가정
        m, d = map(int, date_part.split('/'))
        div_dt = datetime(base_year, m, d, 15, 0, 0)
        
        parsed_data.append({
            "Category": "Dividend",
            "Date": div_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "Ticker": ticker.strip(),
            "Type": "Dividend",
            "Qty": 0,
            "Price": float(amount),
            "Amount_KRW": 0,
            "Memo": "배당금"
        })

    # 3. 환전 파싱 (외화매수환전)
    exch_pattern = re.compile(r'외화매수환전.*?￦([0-9,]+).*?@([0-9,.]+).*?USD\s*([0-9,.]+)', re.DOTALL)
    for match in exch_pattern.finditer(full_text):
        krw_str, rate_str, usd_str = match.groups()
        
        # 환전 시간은 보통 메시지 헤더가 없으면 알기 어려움.
        # 사용자가 입력한 base_date의 14:00으로 가정 (장중)
        exch_dt = datetime.combine(base_date, datetime.min.time()).replace(hour=14, minute=0)
        
        parsed_data.append({
            "Category": "Exchange",
            "Date": exch_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "Ticker": "-",
            "Type": "KRW_to_USD",
            "Qty": 0,
            "Price": float(usd_str.replace(',', '')), # USD Amount
            "Amount_KRW": float(krw_str.replace(',', '')),
            "Memo": "환전"
        })

    return pd.DataFrame(parsed_data)

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
        if st.button("🔄 Data Reload"):
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
                
                is_plus = total_pl_tk >= 0
                color_cls = "card-up" if is_plus else "card-down"
                txt_cls = "txt-red" if is_plus else "txt-blue"
                arrow = "▲" if is_plus else "▼"
                
                html = f"""
                <div class="stock-card {color_cls}">
                    <div class="card-header">
                        <span class="card-ticker">{tk}</span>
                        <span class="card-price">${cur_p:.2f}</span>
                    </div>
                    <div class="card-main-val">₩ {val_krw:,.0f}</div>
                    <div class="card-sub-box {txt_cls}">
                        <span class="pl-amt">{arrow} {abs(total_pl_tk):,.0f}</span>
                        <span class="pl-pct">{total_ret:.1f}%</span>
                    </div>
                </div>
                """
                with cols[idx % 4]:
                    st.markdown(html, unsafe_allow_html=True)

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
        st.dataframe(u_trade[['Date', 'Ticker', 'Type', 'Qty', 'Price_USD']].fillna(''), use_container_width=True)
        st.dataframe(u_money[['Date', 'Type', 'USD_Amount', 'KRW_Amount', 'Ex_Rate']].fillna(''), use_container_width=True)

    # ---------------------------------------------------------
    # [Tab 4] Input Manager (Improved)
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
                st.info("카톡 내용을 복사해서 아래에 붙여넣으세요. 날짜 정보가 없으면 왼쪽의 '기준 날짜'를 사용합니다.")
            
            raw_text = st.text_area("카톡 내용 붙여넣기", height=200, placeholder="[한국투자증권 체결안내]08:05\n...")
            
            if st.button("🚀 분석하기"):
                if raw_text:
                    df_parsed = parse_kakaotalk_v2(raw_text, ref_date)
                    
                    if not df_parsed.empty:
                        st.success(f"{len(df_parsed)}건의 데이터를 찾았습니다! 내용을 확인하고 저장하세요.")
                        # 날짜/시간 등 수정 가능하도록 Editor 제공
                        edited_df = st.data_editor(df_parsed, use_container_width=True, num_rows="dynamic")
                        
                        if st.button("💾 DB에 저장하기"):
                            ws_trade = sheet_instance.worksheet("Trade_Log")
                            ws_money = sheet_instance.worksheet("Money_Log")
                            
                            max_id = max(pd.to_numeric(u_trade['Order_ID']).max(), pd.to_numeric(u_money['Order_ID']).max())
                            next_id = int(max_id) + 1
                            
                            count = 0
                            for _, row in edited_df.iterrows():
                                if row['Category'] == 'Trade':
                                    ws_trade.append_row([
                                        str(row['Date']),
                                        next_id,
                                        row['Ticker'],
                                        row['Ticker'],
                                        row['Type'],
                                        row['Qty'],
                                        row['Price'],
                                        "", "카톡파싱"
                                    ])
                                elif row['Category'] in ['Dividend', 'Exchange']:
                                    rate = row['Amount_KRW'] / row['Price'] if row['Amount_KRW'] > 0 else 0
                                    ws_money.append_row([
                                        str(row['Date']),
                                        next_id,
                                        row['Type'],
                                        row['Ticker'],
                                        row['Amount_KRW'],
                                        row['Price'],
                                        rate, "", "", row['Memo']
                                    ])
                                next_id += 1
                                count += 1
                                
                            st.success(f"✅ {count}건 저장 완료! 대시보드를 새로고침하세요.")
                            time.sleep(2)
                            st.rerun()
                    else:
                        st.warning("⚠️ 분석 가능한 내역이 없습니다. 텍스트 형식을 확인해주세요.")

        else:
            with st.form("input_form"):
                col1, col2 = st.columns(2)
                i_date = col1.date_input("날짜", datetime.now())
                i_usd = col2.number_input("금액 (USD)", min_value=0.01, step=0.01, format="%.2f")
                
                # ... (기존 수기 입력 로직 동일)
                # 여기는 이전 코드와 동일하게 유지
                i_krw = st.number_input("입금 원화 (KRW)", min_value=0, step=100)
                i_ticker = st.text_input("종목코드 (배당 시)")
                i_type = st.selectbox("유형", ["KRW_to_USD", "Dividend", "Withdraw"])
                i_note = st.text_input("비고", value="수기입력")
                
                if st.form_submit_button("💾 저장하기"):
                    max_id = max(pd.to_numeric(u_trade['Order_ID']).max(), pd.to_numeric(u_money['Order_ID']).max())
                    next_id = int(max_id) + 1
                    rate = i_krw / i_usd if i_type=="KRW_to_USD" and i_usd > 0 else 0
                    
                    sheet_instance.worksheet("Money_Log").append_row([
                        i_date.strftime("%Y-%m-%d"), next_id, i_type, i_ticker,
                        i_krw, i_usd, rate, "", "", i_note
                    ])
                    st.success("저장 완료!")
                    time.sleep(1)
                    st.rerun()

if __name__ == "__main__":
    main()
