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

if 'price_cache' not in st.session_state: st.session_state['price_cache'] = {}
if 'last_update' not in st.session_state: st.session_state['last_update'] = None

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
    .txt-red {{ color: {COLOR_RED} !important; }}
    .txt-blue {{ color: {COLOR_BLUE} !important; }}
    .txt-orange {{ color: #FF9800 !important; }}
    .bg-red {{ background-color: {COLOR_BG_RED} !important; }}
    .bg-blue {{ background-color: {COLOR_BG_BLUE} !important; }}
    .stock-card {{ background-color: {THEME_CARD}; border-radius: 16px; padding: 20px; margin-bottom: 16px; border: 1px solid {THEME_BORDER}; border-left: 6px solid #555; transition: transform 0.2s, box-shadow 0.2s; }}
    .stock-card:hover {{ transform: translateY(-4px); box-shadow: 0 6px 12px rgba(0,0,0,0.4); }}
    .card-up {{ border-left-color: {COLOR_RED} !important; }}
    .card-down {{ border-left-color: {COLOR_BLUE} !important; }}
    .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
    .card-ticker {{ font-size: 1.4rem; font-weight: 900; color: {THEME_TEXT}; }}
    .card-price {{ font-size: 1.1rem; font-weight: 500; color: {THEME_SUB}; }}
    .card-main-val {{ font-size: 1.6rem; font-weight: 800; color: {THEME_TEXT}; text-align: right; margin-bottom: 4px; letter-spacing: -0.5px; }}
    .card-sub-box {{ text-align: right; font-size: 1.0rem; font-weight: 600; }}
    .int-table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; text-align: right; color: {THEME_TEXT}; }}
    .int-table th {{ background-color: #252627; color: {THEME_SUB}; padding: 14px 10px; text-align: right; border-bottom: 1px solid {THEME_BORDER}; font-weight: 600; }}
    .int-table th:first-child {{ text-align: left; }}
    .int-table td {{ padding: 12px 10px; border-bottom: 1px solid #2D2E30; }}
    .int-table td:first-child {{ text-align: left; font-weight: 700; color: #A8C7FA; }}
    .row-total {{ background-color: #2A2B2D; font-weight: 800; border-top: 2px solid {THEME_BORDER}; }}
    .row-cash {{ background-color: {THEME_BG}; font-style: italic; color: {THEME_SUB}; }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 8px; }}
    .stTabs [data-baseweb="tab"] {{ background-color: {THEME_CARD}; border-radius: 8px; color: {THEME_SUB}; padding: 6px 16px; border: 1px solid {THEME_BORDER}; }}
    .stTabs [aria-selected="true"] {{ background-color: #3C4043 !important; color: #A8C7FA !important; border-color: #A8C7FA !important; }}
    [data-testid="stForm"] {{ background-color: {THEME_CARD}; border: 1px solid {THEME_BORDER}; border-radius: 16px; padding: 24px; }}
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"], .stTextArea textarea {{ color: {THEME_TEXT} !important; background-color: #252627 !important; border-color: {THEME_BORDER} !important; }}
    .stTextInput label, .stNumberInput label, .stSelectbox label, .stRadio label, .stTextArea label {{ color: {THEME_SUB} !important; }}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# [2] 상수 및 데이터 정의 (국내주식 맵핑 추가)
# -------------------------------------------------------------------
SECTOR_ORDER_LIST = {
    '배당': ['O', 'JEPI', 'JEPQ', 'SCHD', 'MAIN', 'KO', 'SCHD(ISA)'], 
    '테크': ['GOOGL', 'NVDA', 'AMD', 'TSM', 'MSFT', 'AAPL', 'AMZN', 'TSLA', 'AVGO', 'SOXL'],
    '리츠': ['PLD', 'AMT'],
    '기타': [] 
}
SORT_ORDER_TABLE = ['O', 'JEPI', 'JEPQ', 'GOOGL', 'NVDA', 'AMD', 'TSM', 'SCHD(ISA)']

# 종목코드 <-> UI 티커 맵핑
DOMESTIC_TICKER_MAP = {
    '458730': 'SCHD(ISA)'
}

# -------------------------------------------------------------------
# [3] 유틸리티 & 데이터 로드 (0건 에러 방지 포함)
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

@st.cache_data
def load_data():
    client = get_gsheet_client()
    sh = client.open("Investment_Dashboard_DB")
    
    def get_safe_df(sheet_name, default_columns):
        try:
            ws = sh.worksheet(sheet_name)
            records = ws.get_all_records()
            if not records:
                return pd.DataFrame(columns=default_columns)
            df = pd.DataFrame(records)
            df.columns = df.columns.astype(str).str.strip()
            return df
        except Exception:
            return pd.DataFrame(columns=default_columns)

    df_trade = get_safe_df("Trade_Log", ['Date', 'Order_ID', 'Ticker', 'Name', 'Type', 'Qty', 'Price_USD', 'Ex_Avg_Rate', 'Note', 'Source'])
    df_money = get_safe_df("Money_Log", ['Date', 'Order_ID', 'Type', 'Ticker', 'KRW_Amount', 'USD_Amount', 'Ex_Rate', 'Avg_Rate', 'Balance', 'Note', 'Source'])
    df_domestic = get_safe_df("Domestic_Log", ['Date', 'Type', 'Ticker', 'Name', 'Qty', 'Price_KRW', 'Amount_KRW', 'Note'])

    cols_money = ['KRW_Amount', 'USD_Amount', 'Ex_Rate', 'Avg_Rate', 'Balance']
    for c in cols_money:
        if c in df_money.columns: 
            df_money[c] = pd.to_numeric(df_money[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
    cols_trade = ['Qty', 'Price_USD', 'Ex_Avg_Rate']
    for c in cols_trade:
        if c in df_trade.columns: 
            df_trade[c] = pd.to_numeric(df_trade[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    cols_dom = ['Qty', 'Price_KRW', 'Amount_KRW']
    for c in cols_dom:
        if c in df_domestic.columns: 
            df_domestic[c] = pd.to_numeric(df_domestic[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    return df_trade, df_money, df_domestic

def get_realtime_rate():
    try:
        if 'fx_rate' not in st.session_state:
            data = yf.Ticker("KRW=X").history(period="1d")
            st.session_state['fx_rate'] = data['Close'].iloc[-1] if not data.empty else 1450.0
        return st.session_state['fx_rate']
    except: return 1450.0

# -------------------------------------------------------------------
# [4] 엔진: 달러 저수지 & 원화 자산 통합 프로세싱
# -------------------------------------------------------------------
def process_timeline(df_trade, df_money, df_domestic):
    # 1. 달러 저수지 처리
    df_money['Source'] = 'Money'
    df_trade['Source'] = 'Trade'
    
    try:
        df_money['Date_Obj'] = pd.to_datetime(df_money['Date'].astype(str))
        df_trade['Date_Obj'] = pd.to_datetime(df_trade['Date'].astype(str))
    except: pass

    timeline = pd.concat([df_money, df_trade], ignore_index=True)
    if 'Order_ID' not in timeline.columns: timeline['Order_ID'] = 0
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    timeline = timeline.sort_values(by=['Date_Obj', 'Order_ID'])
    
    current_balance = 0.0
    current_avg_rate = 0.0
    pure_exch_krw_sum = 0.0
    pure_exch_usd_sum = 0.0
    
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
                    if ticker not in portfolio: portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_usd':0, 'realized_krw':0, 'accum_div_usd':0, 'accum_div_krw':0, 'is_domestic':False, 'raw_ticker':ticker}
                    portfolio[ticker]['accum_div_usd'] += usd_amt
                if current_balance + usd_amt > 0: current_avg_rate = (current_balance * current_avg_rate) / (current_balance + usd_amt)
            else:
                if current_balance + usd_amt > 0: current_avg_rate = ((current_balance * current_avg_rate) + krw_amt) / (current_balance + usd_amt)
                if 'krw_to_usd' in t_type or '환전' in t_type:
                    pure_exch_krw_sum += krw_amt; pure_exch_usd_sum += usd_amt
            current_balance += usd_amt

        elif source == 'Trade':
            qty = safe_float(row.get('Qty'))
            price = safe_float(row.get('Price_USD'))
            amount = qty * price
            ticker = str(row.get('Ticker', '')).strip()
            
            if ticker not in portfolio: portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_usd':0, 'realized_krw':0, 'accum_div_usd':0, 'accum_div_krw':0, 'is_domestic':False, 'raw_ticker':ticker}
            
            if 'buy' in t_type or '매수' in t_type:
                current_balance -= amount
                ex_rate_db = safe_float(row.get('Ex_Avg_Rate'))
                rate_to_use = ex_rate_db if ex_rate_db > 0 else current_avg_rate
                portfolio[ticker]['qty'] += qty
                portfolio[ticker]['invested_krw'] += (amount * rate_to_use)
                portfolio[ticker]['invested_usd'] += amount 
                
            elif 'sell' in t_type or '매도' in t_type:
                current_balance += amount
                if portfolio[ticker]['qty'] > 0:
                    unit_krw = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                    unit_usd = portfolio[ticker]['invested_usd'] / portfolio[ticker]['qty']
                    portfolio[ticker]['realized_krw'] += (amount * current_avg_rate) - (qty * unit_krw)
                    portfolio[ticker]['qty'] -= qty
                    portfolio[ticker]['invested_krw'] -= (qty * unit_krw)
                    portfolio[ticker]['invested_usd'] -= (qty * unit_usd)

    # 2. 원화 자산(Domestic_Log) 처리
    domestic_cash = 0.0
    for idx, row in df_domestic.iterrows():
        t_type = str(row.get('Type', '')).lower()
        raw_ticker = str(row.get('Ticker', '')).strip()
        ticker = DOMESTIC_TICKER_MAP.get(raw_ticker, raw_ticker) 
        
        qty = safe_float(row.get('Qty'))
        amount_krw = safe_float(row.get('Amount_KRW'))
        
        if ticker not in portfolio and raw_ticker and raw_ticker != '-':
            portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_usd':0, 'realized_krw':0, 'accum_div_usd':0, 'accum_div_krw':0, 'is_domestic':True, 'raw_ticker':raw_ticker}
            
        if 'buy' in t_type or '매수' in t_type:
            portfolio[ticker]['qty'] += qty
            portfolio[ticker]['invested_krw'] += amount_krw
            domestic_cash -= amount_krw
        elif 'sell' in t_type or '매도' in t_type:
            if portfolio[ticker]['qty'] > 0:
                unit_krw = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                portfolio[ticker]['realized_krw'] += amount_krw - (qty * unit_krw)
                portfolio[ticker]['qty'] -= qty
                portfolio[ticker]['invested_krw'] -= (qty * unit_krw)
            domestic_cash += amount_krw
        elif 'dividend' in t_type or '배당' in t_type:
            if ticker in portfolio:
                portfolio[ticker]['accum_div_krw'] += amount_krw
            domestic_cash += amount_krw
        elif 'deposit' in t_type or '입금' in t_type:
            domestic_cash += amount_krw
        elif 'withdraw' in t_type or '출금' in t_type:
            domestic_cash -= amount_krw

    pure_exch_rate = pure_exch_krw_sum / pure_exch_usd_sum if pure_exch_usd_sum > 0 else 0
    return df_trade, df_money, current_balance, domestic_cash, current_avg_rate, pure_exch_rate, portfolio

# -------------------------------------------------------------------
# [5] Helper: 카톡 파싱 (국내 주식 분기 및 K-ETF 배당 추가)
# -------------------------------------------------------------------
def parse_kakaotalk_final(text, base_date):
    parsed_list = []
    base_year = base_date.year
    lines = text.split('\n')
    full_text = "\n".join([l.strip() for l in lines if l.strip()])

    # 1. 매매 파싱 (해외/국내 분기)
    blocks = re.split(r'\[한국투자증권 체결안내\]', full_text)
    for block in blocks:
        if not block: continue
        try:
            time_match = re.match(r'(\d{2}:\d{2})', block.strip())
            time_str = time_match.group(1) if time_match else "00:00"
            
            # K-ETF(국내) 매수 패턴
            dom_buy = re.search(r'\*매매구분:현금(매수|매도)체결', block)
            dom_name = re.search(r'\*종목명:.*?\(([\dA-Za-z]+)\)', block)
            dom_qty = re.search(r'\*체결수량:([\d,]+)', block)
            dom_price = re.search(r'\*체결단가:([\d,]+)원', block)
            
            if dom_buy and dom_name and dom_qty and dom_price:
                t_dt = datetime.combine(base_date, datetime.min.time()).replace(hour=int(time_str.split(':')[0]), minute=int(time_str.split(':')[1]))
                t_type = "Buy" if dom_buy.group(1) == "매수" else "Sell"
                parsed_list.append({
                    "Category": "Domestic_Trade", "Date": t_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "Ticker": dom_name.group(1), "Name": "-", "Type": t_type,
                    "Qty": int(dom_qty.group(1).replace(',','')), "Price": float(dom_price.group(1).replace(',','')), "Amount": 0, "Memo": f"카톡파싱_{time_str}"
                })
                continue 
            
            # 해외 매수 패턴
            type_m = re.search(r'\*매매구분:(매수|매도)', block)
            name_m = re.search(r'\*종목명:([A-Za-z0-9 ]+)(?:/|$)', block)
            qty_m = re.search(r'\*체결수량:([\d,]+)', block)
            price_m = re.search(r'\*체결단가:USD\s*([\d.]+)', block)
            
            if type_m and name_m and qty_m and price_m:
                trade_dt = datetime.combine(base_date, datetime.min.time()) - timedelta(days=1)
                final_dt = trade_dt.strftime("%Y-%m-%d 23:30:00")
                parsed_list.append({
                    "Category": "Trade", "Date": final_dt,
                    "Ticker": name_m.group(1).strip(), "Type": "Buy" if type_m.group(1) == "매수" else "Sell",
                    "Qty": int(qty_m.group(1).replace(',','')), "Price": float(price_m.group(1).replace(',','')), "Amount": 0, "Memo": f"카톡파싱_{time_str}"
                })
        except: continue

    # 2. 해외 배당 파싱
    div_pattern = re.compile(r'최원준님\s*(\d{2}/\d{2}).*?([A-Z]+)/.*?USD\s*([\d.]+)\s*세전배당입금', re.DOTALL)
    for match in div_pattern.finditer(full_text):
        try:
            date_part, ticker, amount = match.groups()
            m, d = map(int, date_part.split('/'))
            div_dt = datetime(base_year, m, d, 15, 0, 0)
            parsed_list.append({
                "Category": "Dividend", "Date": div_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Ticker": ticker.strip(), "Type": "Dividend",
                "Qty": 0, "Price": float(amount), "Amount": 0, "Memo": "카톡파싱_배당"
            })
        except: continue

    # [NEW] 2.5 국내 ETF 배당 파싱
    dom_div_pattern = re.compile(
        r'ETF 결산분배금 입금 안내.*?'
        r'\*\s*종목명\s*:\s*(.*?)\s*\*'
        r'.*?'
        r'\*\s*입금액\s*:\s*([\d,]+)원.*?'
        r'\*\s*입금일자\s*:\s*(\d{4})년\s*(\d{2})월\s*(\d{2})일', 
        re.DOTALL
    )
    
    # 한국 이름 -> 종목코드 변환 사전
    K_ETF_NAME_TO_CODE = {
        "TIGER 미국배당다우존스": "458730"
        # 나중에 다른 종목이 생기면 여기에 "이름": "코드" 추가
    }

    for match in dom_div_pattern.finditer(full_text):
        try:
            name, amount_str, year, month, day = match.groups()
            name = name.strip()
            amount = float(amount_str.replace(',', ''))
            
            # 카톡에 찍힌 입금일자 오후 3시로 픽스
            div_dt = datetime(int(year), int(month), int(day), 15, 0, 0)
            
            # 사전에서 코드를 찾고, 없으면 일단 이름 자체를 넣음
            ticker = K_ETF_NAME_TO_CODE.get(name, name)
            
            parsed_list.append({
                "Category": "Domestic_Dividend", 
                "Date": div_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Ticker": ticker, 
                "Type": "Dividend",
                "Qty": 0, 
                "Price": 0, 
                "Amount": amount, 
                "Memo": "카톡파싱_국내배당"
            })
        except: continue

    # 3. 환전 파싱
    exch_pattern = re.compile(r'외화매수환전.*?￦([0-9,]+).*?@([0-9,.]+).*?USD\s*([0-9,.]+)', re.DOTALL)
    for match in exch_pattern.finditer(full_text):
        try:
            krw_str, rate_str, usd_str = match.groups()
            exch_dt = datetime.combine(base_date, datetime.min.time()).replace(hour=14, minute=0)
            parsed_list.append({
                "Category": "Exchange", "Date": exch_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Ticker": "-", "Type": "KRW_to_USD",
                "Qty": 0, "Price": float(usd_str.replace(',', '')), 
                "Amount": float(krw_str.replace(',', '')), "Memo": "카톡파싱_환전"
            })
        except: continue
        
    return parsed_list

# -------------------------------------------------------------------
# [6] Main App
# -------------------------------------------------------------------
def main():
    try:
        df_trade, df_money, df_domestic = load_data()
        
        # 시트 저장용 인스턴스는 여기서 따로 불러오기
        client = get_gsheet_client()
        sheet_instance = client.open("Investment_Dashboard_DB")
    except Exception as e:
        st.error(f"🚨 DB 연결/로딩 실패 상세 원인: {e}")
        st.info("💡 팁: 구글 시트의 탭 이름(Money_Log, Trade_Log, Domestic_Log)이 일치하는지 확인하세요.")
        st.stop()
        
    u_trade, u_money, cur_bal, dom_cash, cur_rate, pure_exch_rate, portfolio = process_timeline(df_trade, df_money, df_domestic)
    cur_real_rate = get_realtime_rate()
    
    # [시세 조회 캐싱]
    tickers = list(portfolio.keys())
    if tickers:
        uncached = [t for t in tickers if t not in st.session_state['price_cache']]
        if uncached:
            with st.spinner("최신 시세 조회 중..."):
                for tk in uncached:
                    data = portfolio[tk]
                    if data['is_domestic']:
                        try:
                            st.session_state['price_cache'][tk] = yf.Ticker(f"{data['raw_ticker']}.KS").history(period="1d")['Close'].iloc[-1]
                        except: st.session_state['price_cache'][tk] = 0
                    else:
                        st.session_state['price_cache'][tk] = kis.get_current_price(tk)
        prices = st.session_state['price_cache']
    else:
        prices = {}
    
    # --- KPI Logic Aggregation ---
    total_stock_val_krw = 0.0
    total_input_principal = df_money[df_money['Type'] == 'KRW_to_USD']['KRW_Amount'].apply(safe_float).sum()
    total_dom_principal = df_domestic[df_domestic['Type'].isin(['Deposit', '입금'])]['Amount_KRW'].apply(safe_float).sum()
    total_principal_all = total_input_principal + total_dom_principal
    
    total_realized_krw = sum(d['realized_krw'] for d in portfolio.values())
    total_div_usd = sum(d['accum_div_usd'] for d in portfolio.values())
    total_div_krw = (total_div_usd * cur_real_rate) + sum(d['accum_div_krw'] for d in portfolio.values())
    
    total_price_profit = 0
    total_fx_profit = 0
    
    for tk, data in portfolio.items():
        if data['qty'] > 0:
            cur_p = prices.get(tk, 0)
            if data['is_domestic']:
                val_krw = data['qty'] * cur_p
                total_stock_val_krw += val_krw
                total_price_profit += (val_krw - data['invested_krw'])
            else:
                val_usd = data['qty'] * cur_p
                val_krw = val_usd * cur_real_rate
                invested_krw = data['invested_krw']
                invested_usd = data['invested_usd']
                
                avg_rate_tk = invested_krw / invested_usd if invested_usd > 0 else 0
                fx_p = invested_usd * (cur_real_rate - avg_rate_tk)
                price_p = (val_usd - invested_usd) * cur_real_rate
                
                total_stock_val_krw += val_krw
                total_price_profit += price_p
                total_fx_profit += fx_p

    cash_val_krw = cur_bal * cur_real_rate
    cash_invested_krw = cur_bal * cur_rate 
    total_fx_profit += (cash_val_krw - cash_invested_krw)

    total_asset_krw = total_stock_val_krw + cash_val_krw + dom_cash
    total_pl_krw = total_asset_krw - total_principal_all
    total_pl_pct = (total_pl_krw / total_principal_all * 100) if total_principal_all > 0 else 0
    
    # BEP 
    bep_numerator = total_input_principal - sum(d['realized_krw'] for d in portfolio.values() if not d['is_domestic']) - (total_div_usd * cur_real_rate)
    total_usd_assets = sum(d['qty'] * prices.get(tk,0) for tk, d in portfolio.items() if not d['is_domestic']) + cur_bal
    bep_rate = bep_numerator / total_usd_assets if total_usd_assets > 0 else 0
    safety_margin = cur_real_rate - bep_rate

    # Header
    c1, c2 = st.columns([3, 1])
    with c1: st.title("🚀 Investment Command Center")
    with c2:
        if st.button("🔄 시세/데이터 새로고침"):
            st.session_state['price_cache'] = {}
            if 'fx_rate' in st.session_state: del st.session_state['fx_rate']
            st.cache_data.clear()
            st.rerun()

    # ------------------------------------------------------------------
    # [KPI Section]
    # ------------------------------------------------------------------
    kpi_cols = st.columns(3)
    with kpi_cols[0]:
        is_plus = total_pl_krw >= 0
        cls = "card-up" if is_plus else "card-down"
        txt = "txt-red" if is_plus else "txt-blue"
        arrow = "▲" if is_plus else "▼"
        st.markdown(f"""
        <div class="stock-card {cls}">
            <div class="card-header"><span class="card-ticker">총 자산</span><span class="card-price">Total Assets</span></div>
            <div class="card-main-val">₩ {total_asset_krw:,.0f}</div>
            <div class="card-sub-box {txt}">{arrow} {abs(total_pl_krw):,.0f} ({total_pl_pct:+.2f}%)</div>
            <details>
                <summary style="text-align:right; font-size:0.8rem; color:#888; cursor:pointer; margin-top:5px;">상세 손익 내역</summary>
                <table class="detail-table" style="width:100%; font-size:0.85rem; color:#ccc;">
                    <tr><td>평가손익</td><td style="text-align:right;">₩ {total_price_profit:,.0f}</td></tr>
                    <tr><td>환차익</td><td style="text-align:right;">₩ {total_fx_profit:,.0f}</td></tr>
                    <tr><td>실현손익</td><td style="text-align:right;">₩ {total_realized_krw:,.0f}</td></tr>
                    <tr><td>배당수익</td><td style="text-align:right;">₩ {total_div_krw:,.0f}</td></tr>
                </table>
            </details>
        </div>
        """, unsafe_allow_html=True)

    with kpi_cols[1]:
        st.markdown(f"""
        <div class="stock-card">
            <div class="card-header"><span class="card-ticker">달러 잔고</span><span class="card-price">USD Balance</span></div>
            <div class="card-main-val">$ {cur_bal:,.2f}</div>
            <div class="card-sub-box"><span style="font-size:0.9rem; color:#888;">매수평단 ₩ {cur_rate:,.2f}</span></div>
            <div style="text-align:right; margin-top:4px;"><span style="font-size:0.8rem; color:#666;">(순수환전 ₩ {pure_exch_rate:,.2f})</span></div>
        </div>
        """, unsafe_allow_html=True)

    with kpi_cols[2]:
        margin_cls = "txt-red" if safety_margin >= 0 else "txt-blue"
        margin_arrow = "+" if safety_margin >= 0 else ""
        st.markdown(f"""
        <div class="stock-card {cls if safety_margin >= 0 else 'card-down'}">
            <div class="card-header"><span class="card-ticker">안전마진</span><span class="card-price">Safety Margin</span></div>
            <div class="card-main-val {margin_cls}">{margin_arrow}{safety_margin:,.2f} 원</div>
            <div class="card-sub-box"><span style="font-size:0.9rem; color:#888;">BEP ₩ {bep_rate:,.2f}</span></div>
            <div style="text-align:right; margin-top:4px;"><span style="font-size:0.8rem; color:#FF9800;">시장환율 ₩ {cur_real_rate:,.2f}</span></div>
        </div>
        """, unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["📊 대시보드", "📋 통합 상세", "📜 통합 로그", "🕹️ 입력 매니저"])
    
    # [Tab 1] Dashboard
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
                
                is_dom = data['is_domestic']
                if is_dom:
                    val_krw = qty * cur_p
                    invested_krw = data['invested_krw']
                    div_krw = data['accum_div_krw']
                    total_pl_tk = val_krw - invested_krw + data['realized_krw'] + div_krw
                    margin_tk_str = "-"
                    price_display = f"₩ {cur_p:,.0f}"
                else:
                    val_krw = qty * cur_p * cur_real_rate
                    invested_krw = data['invested_krw']
                    div_krw = data['accum_div_usd'] * cur_real_rate
                    total_pl_tk = val_krw - invested_krw + data['realized_krw'] + div_krw
                    bep_rate_tk = (invested_krw - data['realized_krw'] - div_krw) / (qty * cur_p) if (qty*cur_p) > 0 else 0
                    margin_tk = cur_real_rate - bep_rate_tk
                    margin_tk_str = f"{margin_tk:+.1f} 원"
                    price_display = f"${cur_p:.2f}"

                total_ret = (total_pl_tk / invested_krw * 100) if invested_krw > 0 else 0
                is_plus = total_pl_tk >= 0
                color_cls = "card-up" if is_plus else "card-down"
                txt_cls = "txt-red" if is_plus else "txt-blue"
                arrow = "▲" if is_plus else "▼"
                sign = "+" if is_plus else ""
                
                html = f"""
                <div class="stock-card {color_cls}">
                    <div class="card-header"><span class="card-ticker">{tk}</span><span class="card-price">{price_display}</span></div>
                    <div class="card-main-val">₩ {val_krw:,.0f}</div>
                    <div class="card-sub-box {txt_cls}"><span class="pl-amt">{arrow} {abs(total_pl_tk):,.0f}</span> <span class="pl-pct">{sign}{total_ret:.1f}%</span></div>
                    <details>
                        <summary style="text-align:right; font-size:0.8rem; color:#888; cursor:pointer; margin-top:5px;">상세 내역</summary>
                        <table class="detail-table" style="width:100%; font-size:0.85rem; color:#ccc;">
                            <tr><td>보유수량</td><td style="text-align:right;">{qty:,.0f}</td></tr>
                            <tr><td>투자원금</td><td style="text-align:right;">₩ {invested_krw:,.0f}</td></tr>
                            <tr><td>누적실현</td><td style="text-align:right;">₩ {data['realized_krw']:,.0f}</td></tr>
                            <tr><td>누적배당</td><td style="text-align:right;">₩ {div_krw:,.0f}</td></tr>
                            <tr><td style="color:#AAA">안전마진</td><td style="text-align:right; color:{COLOR_RED if is_plus else COLOR_BLUE}">{margin_tk_str}</td></tr>
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
        def sort_key(tk): return SORT_ORDER_TABLE.index(tk) if tk in SORT_ORDER_TABLE else 999
        sorted_tickers = sorted(all_keys, key=sort_key)
        
        sum_eval_krw = 0; sum_realized = 0;
        
        for tk in sorted_tickers:
            if tk == 'Cash': continue
            data = portfolio[tk]
            qty = data['qty']
            cur_p = prices.get(tk, 0)
            
            if qty == 0 and data['realized_krw'] == 0 and data['accum_div_usd'] == 0 and data['accum_div_krw'] == 0: continue

            is_dom = data['is_domestic']
            invested_krw = data['invested_krw']
            
            if is_dom:
                eval_krw = qty * cur_p
                div_krw = data['accum_div_krw']
                total_pl = eval_krw - invested_krw + data['realized_krw'] + div_krw
                price_profit = eval_krw - invested_krw if qty > 0 else 0
                fx_profit_str = "-"
                margin_str = "-"
            else:
                eval_krw = qty * cur_p * cur_real_rate
                invested_usd = data['invested_usd']
                div_krw = data['accum_div_usd'] * cur_real_rate
                total_pl = eval_krw - invested_krw + data['realized_krw'] + div_krw
                
                if qty > 0:
                    my_avg_rate_tk = invested_krw / invested_usd if invested_usd > 0 else 0
                    fx_profit = invested_usd * (cur_real_rate - my_avg_rate_tk)
                    val_usd = qty * cur_p
                    price_profit = (val_usd - invested_usd) * cur_real_rate
                    fx_profit_str = f"{fx_profit:,.0f}"
                else:
                    fx_profit = 0; price_profit = 0; fx_profit_str = "-"
                
                bep_tk = (invested_krw - (data['realized_krw'] + div_krw)) / (qty * cur_p) if (qty*cur_p) > 0 else 0
                margin_str = f"{cur_real_rate - bep_tk:+.1f}" if qty > 0 else "-"

            realized_total = data['realized_krw'] + div_krw
            sum_eval_krw += eval_krw
            sum_realized += realized_total
            
            cls_price = "txt-red" if price_profit >= 0 else "txt-blue"
            cls_fx = "txt-red" if (is_dom or fx_profit >= 0) else "txt-blue"
            cls_tot = "txt-red" if total_pl >= 0 else "txt-blue"
            bg_cls = "bg-red" if total_pl >= 0 else "bg-blue"
            
            if is_dom: cls_fx = "txt-sub" 
            
            rows_html += f"<tr><td>{tk}</td><td>{eval_krw:,.0f}</td><td class='{cls_price}'>{price_profit:,.0f}</td><td class='{cls_fx}'>{fx_profit_str}</td><td>{realized_total:,.0f}</td><td class='{cls_tot} {bg_cls}'><b>{total_pl:,.0f}</b></td><td>{margin_str}</td></tr>"
            
        cash_krw = cur_bal * cur_real_rate
        final_pl_calc = (sum_eval_krw + cash_krw + dom_cash) - total_principal_all
        cls_fin = "txt-red" if final_pl_calc >= 0 else "txt-blue"
        
        cash_row = f"<tr class='row-cash'><td>Cash (USD/KRW)</td><td>{cash_krw+dom_cash:,.0f}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
        total_row = f"<tr class='row-total'><td>TOTAL</td><td>{(sum_eval_krw + cash_krw + dom_cash):,.0f}</td><td>-</td><td>-</td><td>{sum_realized:,.0f}</td><td class='{cls_fin}'>{final_pl_calc:,.0f}</td><td>{safety_margin:+.1f}</td></tr>"
        
        full_table = header + rows_html + cash_row + total_row + "</tbody></table>"
        st.markdown(full_table, unsafe_allow_html=True)

    with tab3:
        st.dataframe(df_trade[['Date', 'Ticker', 'Type', 'Qty', 'Price_USD', 'Note']].fillna(''), use_container_width=True)
        st.dataframe(df_money[['Date', 'Type', 'USD_Amount', 'KRW_Amount', 'Note']].fillna(''), use_container_width=True)
        st.dataframe(df_domestic[['Date', 'Type', 'Ticker', 'Qty', 'Price_KRW', 'Amount_KRW', 'Note']].fillna(''), use_container_width=True)

    # ---------------------------------------------------------
    # [Tab 4] Input Manager
    # ---------------------------------------------------------
    with tab4:
        st.subheader("📝 입출금 및 배당 관리")
        mode = st.radio("입력 모드", ["💬 카카오톡 파싱 (추천)", "✍️ 수기 입력"], horizontal=True)
        st.divider()
        
        if mode == "💬 카카오톡 파싱 (추천)":
            c1, c2 = st.columns([1, 2])
            with c1: ref_date = st.date_input("📅 기준 날짜 (카톡 수신일)", datetime.now())
            with c2: st.info("카톡 내용을 복사해서 아래에 붙여넣으세요. '저장하기' 버튼을 누르면 즉시 DB에 저장됩니다.")
            
            raw_text = st.text_area("카톡 내용 붙여넣기", height=200, placeholder="[한국투자증권 체결안내]08:05\n...")
            
            if st.button("🚀 저장하기 (분석 및 DB전송)", type="primary"):
                if raw_text:
                    parsed_items = parse_kakaotalk_final(raw_text, ref_date)
                    count = 0
                    if parsed_items:
                        ws_trade = sheet_instance.worksheet("Trade_Log")
                        ws_money = sheet_instance.worksheet("Money_Log")
                        ws_dom = sheet_instance.worksheet("Domestic_Log")
                        
                        max_id = max(pd.to_numeric(df_trade['Order_ID']).max(), pd.to_numeric(df_money['Order_ID']).max())
                        next_id = int(max_id) + 1 if not pd.isna(max_id) else 1
                        
                        for item in parsed_items:
                            if item["Category"] == "Trade":
                                ws_trade.append_row([ item["Date"], int(next_id), str(item["Ticker"]), str(item["Ticker"]), str(item["Type"]), int(item["Qty"]), float(item["Price"]), "", item["Memo"] ])
                                next_id += 1
                            elif item["Category"] == "Domestic_Trade":
                                ws_dom.append_row([ item["Date"], str(item["Type"]), str(item["Ticker"]), "-", int(item["Qty"]), float(item["Price"]), float(item["Qty"]*item["Price"]), item["Memo"] ])
                            elif item["Category"] == "Dividend":
                                ws_money.append_row([ item["Date"], int(next_id), "Dividend", str(item["Ticker"]), 0, float(item["Price"]), 0, "", "", item["Memo"] ])
                                next_id += 1
                            
                            # [NEW] 국내 ETF 배당 저장 로직 추가
                            elif item["Category"] == "Domestic_Dividend":
                                ws_dom.append_row([ item["Date"], "Dividend", str(item["Ticker"]), "-", 0, 0, float(item["Amount"]), item["Memo"] ])
                                
                            elif item["Category"] == "Exchange":
                                ws_money.append_row([ item["Date"], int(next_id), "KRW_to_USD", "-", float(item["Amount"]), float(item["Price"]), float(item["Amount"]/item["Price"] if item["Price"]>0 else 0), "", "", item["Memo"] ])
                                next_id += 1
                            count += 1
                            
                        st.success(f"✅ {count}건 저장 완료! (캐시 초기화됨)")
                        st.session_state['price_cache'] = {}
                        st.cache_data.clear()
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
                    max_id = max(pd.to_numeric(df_trade['Order_ID']).max(), pd.to_numeric(df_money['Order_ID']).max())
                    next_id = int(max_id) + 1 if not pd.isna(max_id) else 1
                    rate = i_krw / i_usd if i_type=="KRW_to_USD" and i_usd > 0 else 0
                    
                    sheet_instance.worksheet("Money_Log").append_row([
                        i_date.strftime("%Y-%m-%d"), int(next_id), i_type, i_ticker,
                        int(i_krw), float(i_usd), float(rate), "", "", i_note
                    ])
                    st.success("저장 완료!")
                    st.session_state['price_cache'] = {}
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()

if __name__ == "__main__":
    main()
