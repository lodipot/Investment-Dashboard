import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import re
import hashlib
import yfinance as yf
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# [1] 설정 & 다크모드
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="🏦")

if 'price_cache' not in st.session_state: st.session_state['price_cache'] = {}
if 'needs_fetch' not in st.session_state: st.session_state['needs_fetch'] = True
if 'parsed_data' not in st.session_state: st.session_state['parsed_data'] = []

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
    header {{ visibility: hidden; }}
    .block-container {{ padding-top: 1.5rem; }}
    button {{ border-color: {THEME_BORDER} !important; }}
    ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
    ::-webkit-scrollbar-track {{ background: {THEME_BG}; }}
    ::-webkit-scrollbar-thumb {{ background: {THEME_BORDER}; border-radius: 4px; }}
    .txt-red {{ color: {COLOR_RED} !important; }}
    .txt-blue {{ color: {COLOR_BLUE} !important; }}
    .txt-sub {{ color: {THEME_SUB} !important; }}
    
    /* 404 Connection Error 등 스트림릿 모달 팝업 강제 숨김 처리 */
    div[data-testid="stModal"] {{ display: none !important; }}
    div[data-testid="stConnectionStatus"] {{ display: none !important; }}
    
    .stock-card {{ background-color: {THEME_CARD}; border-radius: 16px; padding: 20px; margin-bottom: 16px; border: 1px solid {THEME_BORDER}; border-left: 6px solid #555; }}
    .card-up {{ border-left-color: {COLOR_RED} !important; }}
    .card-down {{ border-left-color: {COLOR_BLUE} !important; }}
    .card-neutral {{ border-left-color: #555 !important; }} 
    
    .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
    .card-ticker {{ font-size: 1.4rem; font-weight: 900; color: {THEME_TEXT}; }}
    .card-price {{ font-size: 1.1rem; font-weight: 500; color: {THEME_SUB}; }}
    .card-main-val {{ font-size: 1.6rem; font-weight: 800; color: {THEME_TEXT}; text-align: right; margin-bottom: 4px; }}
    .card-sub-box {{ text-align: right; font-size: 1.0rem; font-weight: 600; line-height: 1.4; }}
    
    .int-table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; text-align: right; color: {THEME_TEXT}; }}
    .int-table th {{ background-color: #252627; color: {THEME_SUB}; padding: 14px 10px; text-align: right; border-bottom: 1px solid {THEME_BORDER}; font-weight: 600; }}
    .int-table th:first-child {{ text-align: left; }}
    .int-table td {{ padding: 12px 10px; border-bottom: 1px solid #2D2E30; }}
    .int-table td:first-child {{ text-align: left; font-weight: 700; color: #A8C7FA; }}
    .row-total {{ background-color: #2A2B2D; font-weight: 800; border-top: 2px solid {THEME_BORDER}; }}
    
    .stTabs [data-baseweb="tab-list"] {{ flex-wrap: wrap !important; gap: 8px; justify-content: space-between; border-bottom: none; }}
    .stTabs [data-baseweb="tab"] {{ flex: 1 1 calc(50% - 8px) !important; background-color: {THEME_CARD}; border-radius: 8px; color: {THEME_SUB}; padding: 10px 16px; border: 1px solid {THEME_BORDER}; text-align: center; }}
    .stTabs [aria-selected="true"] {{ background-color: #3C4043 !important; color: #A8C7FA !important; border-color: #A8C7FA !important; font-weight: bold; }}
    
    .input-card {{ background-color: #1E1E1E; padding: 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #333; }}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# [2] 맵핑
# -------------------------------------------------------------------
SECTOR_ORDER_LIST = { 
    '배당': ['O', 'JEPI', 'JEPQ', 'SCHD', 'MAIN', 'KO', 'SCHD(ISA)'], 
    '테크': ['GOOGL', 'NVDA', 'AMD', 'TSM', 'MSFT', 'AAPL', 'AMZN', 'TSLA', 'AVGO', 'SOXL'], 
    '의료': ['7733.T'],
    '리츠': ['PLD', 'AMT'], 
    '기타': [] 
}
SORT_ORDER_TABLE = ['O', 'JEPI', 'JEPQ', 'GOOGL', 'NVDA', 'AMD', 'TSM', '7733.T', 'SCHD(ISA)']
DOMESTIC_TICKER_MAP = { '458730': 'SCHD(ISA)' }

def generate_pk(date_str, ticker, t_type):
    # 중복 방지를 위한 임시 해시 식별자 생성
    raw_str = f"{date_str}_{ticker}_{t_type}_{time.time()}"
    return "K-" + hashlib.md5(raw_str.encode()).hexdigest()[:8]

# -------------------------------------------------------------------
# [3] 로드 (단일 통합 원장)
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
    
    try:
        ws = sh.worksheet("Global_Unified_Ledger")
        records = ws.get_all_records()
        if not records: 
            cols = ['Date', 'PK_Hash', 'Source', 'Currency', 'Category', 'Type', 'Ticker', 'Name', 'Qty', 'Price', 'Amount_Local', 'Amount_KRW', 'Note']
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame(records)
        df.columns = df.columns.astype(str).str.strip()
        return df
    except: 
        cols = ['Date', 'PK_Hash', 'Source', 'Currency', 'Category', 'Type', 'Ticker', 'Name', 'Qty', 'Price', 'Amount_Local', 'Amount_KRW', 'Note']
        return pd.DataFrame(columns=cols)

# -------------------------------------------------------------------
# [4] 신규 통합 엔진
# -------------------------------------------------------------------
def process_unified_ledger(df):
    cash_bal = {'USD': 0.0, 'JPY': 0.0, 'KRW': 0.0}
    avg_rate = {'USD': 0.0, 'JPY': 0.0}
    invested_krw = {'USD': 0.0, 'JPY': 0.0}
    fx_realized = {'USD': 0.0, 'JPY': 0.0}
    dom_principal_sum = 0.0
    portfolio = {}

    try: df['Date_Obj'] = pd.to_datetime(df['Date'].astype(str))
    except: df['Date_Obj'] = pd.NaT
    df = df.sort_values(by=['Date_Obj']).fillna('')

    for _, row in df.iterrows():
        curr = str(row.get('Currency', '')).upper()
        cat = str(row.get('Category', ''))
        t_type = str(row.get('Type', '')).lower()
        ticker = str(row.get('Ticker', '')).strip()
        name = str(row.get('Name', '')).strip()
        qty = safe_float(row.get('Qty'))
        price = safe_float(row.get('Price'))
        amt_local = safe_float(row.get('Amount_Local'))
        amt_krw = safe_float(row.get('Amount_KRW'))

        if ticker in ('', '-', 'nan'): ticker = 'Cash'

        if ticker != 'Cash' and ticker not in portfolio:
            portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_for':0, 'realized_krw':0, 'accum_div_for':0, 'accum_div_krw':0, 'currency':curr, 'raw_ticker':ticker, 'name': name}

        if cat == 'Money':
            if 'deposit' in t_type:
                cash_bal['KRW'] += amt_krw
                dom_principal_sum += amt_krw
            elif 'withdraw' in t_type:
                cash_bal['KRW'] -= amt_krw
                dom_principal_sum -= amt_krw
            elif 'dividend' in t_type or '배당' in t_type:
                if curr == 'KRW':
                    cash_bal['KRW'] += amt_krw
                    if ticker != 'Cash': portfolio[ticker]['accum_div_krw'] += amt_krw
                else:
                    cash_bal[curr] += amt_local
                    if ticker != 'Cash': portfolio[ticker]['accum_div_for'] += amt_local
            elif 'krw_to_' in t_type:  # 외화 매수환전
                if cash_bal[curr] <= 0:
                    if amt_local > 0: avg_rate[curr] = amt_krw / amt_local
                else:
                    if (cash_bal[curr] + amt_local) > 0:
                        avg_rate[curr] = ((cash_bal[curr] * avg_rate[curr]) + amt_krw) / (cash_bal[curr] + amt_local)
                cash_bal[curr] += amt_local
                invested_krw[curr] += amt_krw
                cash_bal['KRW'] -= amt_krw
            elif '_to_krw' in t_type:  # 외화 매도환전
                if amt_local > 0:
                    fx_profit = amt_krw - (amt_local * avg_rate[curr])
                    fx_realized[curr] += fx_profit
                    cash_bal[curr] -= amt_local
                    invested_krw[curr] -= amt_krw
                    cash_bal['KRW'] += amt_krw

        elif cat == 'Trade':
            if 'buy' in t_type or '매수' in t_type:
                if curr == 'KRW':
                    cash_bal['KRW'] -= amt_krw
                    portfolio[ticker]['invested_krw'] += amt_krw
                    portfolio[ticker]['qty'] += qty
                else:
                    cash_bal[curr] -= amt_local
                    krw_cost = amt_local * avg_rate[curr]
                    portfolio[ticker]['invested_krw'] += krw_cost
                    portfolio[ticker]['invested_for'] += amt_local
                    portfolio[ticker]['qty'] += qty
            elif 'sell' in t_type or '매도' in t_type:
                if curr == 'KRW':
                    cash_bal['KRW'] += amt_krw
                    if portfolio[ticker]['qty'] > 0:
                        unit_k = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                        portfolio[ticker]['realized_krw'] += amt_krw - (qty * unit_k)
                        portfolio[ticker]['invested_krw'] -= (qty * unit_k)
                        portfolio[ticker]['qty'] -= qty
                else:
                    cash_bal[curr] += amt_local
                    if portfolio[ticker]['qty'] > 0:
                        unit_k = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                        unit_f = portfolio[ticker]['invested_for'] / portfolio[ticker]['qty']
                        portfolio[ticker]['realized_krw'] += (amt_local * avg_rate[curr]) - (qty * unit_k)
                        portfolio[ticker]['invested_krw'] -= (qty * unit_k)
                        portfolio[ticker]['invested_for'] -= (qty * unit_f)
                        portfolio[ticker]['qty'] -= qty

    return cash_bal, avg_rate, invested_krw, fx_realized, dom_principal_sum, portfolio

# -------------------------------------------------------------------
# [5] 카톡 파서 (통합원장 스키마 반환)
# -------------------------------------------------------------------
def parse_kakaotalk_final(text, base_date):
    parsed_list = []
    base_year = base_date.year
    flat_text = text.replace('\n', ' ')
    chunks = re.split(r'(?=\[한국투자증권 체결안내\]|최원준님|\[한국투자증권\]\s*\d{2}:\d{2}.*?외화매수환전|외화매도환전|ETF 결산분배금)', flat_text)

    for chunk in chunks:
        if not chunk.strip(): continue
        try:
            dom_m = re.search(r'\[한국투자증권 체결안내\].*?(\d{2}:\d{2}).*?\*매매구분:현금(매수|매도)체결.*?\*종목명:(.*?)\(([\dA-Za-z]+)\).*?\*체결수량:([\d,]+).*?\*체결단가:([\d,]+)원', chunk)
            if dom_m:
                t_str, t_dir, t_name, t_tkr, t_qty, t_prc = dom_m.groups()
                dt_str = datetime.combine(base_date, datetime.min.time()).replace(hour=int(t_str.split(':')[0]), minute=int(t_str.split(':')[1])).strftime("%Y-%m-%d %H:%M:%S")
                amt_k = int(t_qty.replace(',','')) * float(t_prc.replace(',',''))
                parsed_list.append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, t_tkr, t_dir), "Source": "Kakao", "Currency": "KRW", "Category": "Trade", "Type": "Buy" if t_dir == "매수" else "Sell", "Ticker": t_tkr, "Name": t_name.strip(), "Qty": int(t_qty.replace(',','')), "Price": float(t_prc.replace(',','')), "Amount_Local": 0, "Amount_KRW": amt_k, "Note": f"카톡파싱_{t_str}" })
                continue
                
            jpy_tr_m = re.search(r'\[한국투자증권 체결안내\].*?(\d{2}:\d{2}).*?\*매매구분:(매수|매도).*?\*종목명:([A-Za-z0-9.]+)/(.*?)\s*\*체결수량:([\d,]+).*?\*체결단가:JPY\s*([\d.,]+)', chunk)
            if jpy_tr_m:
                t_str, t_dir, t_code, t_name, t_qty, t_prc = jpy_tr_m.groups()
                dt_str = datetime.combine(base_date, datetime.min.time()).replace(hour=int(t_str.split(':')[0]), minute=int(t_str.split(':')[1])).strftime("%Y-%m-%d %H:%M:%S")
                tkr_formatted = t_code.strip() + ".T"
                amt_l = int(t_qty.replace(',','')) * float(t_prc.replace(',',''))
                parsed_list.append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, tkr_formatted, t_dir), "Source": "Kakao", "Currency": "JPY", "Category": "Trade", "Type": "Buy" if t_dir == "매수" else "Sell", "Ticker": tkr_formatted, "Name": t_name.strip(), "Qty": int(t_qty.replace(',','')), "Price": float(t_prc.replace(',','')), "Amount_Local": amt_l, "Amount_KRW": 0, "Note": f"카톡파싱_{t_str}" })
                continue

            usd_tr_m = re.search(r'\[한국투자증권 체결안내\].*?(\d{2}:\d{2}).*?\*매매구분:(매수|매도).*?\*종목명:([A-Za-z0-9]+)(?:/(.*?))?\s*\*체결수량:([\d,]+).*?\*체결단가:USD\s*([\d.,]+)', chunk)
            if usd_tr_m:
                t_str, t_dir, t_code, t_name, t_qty, t_prc = usd_tr_m.groups()
                dt_str = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=1)).strftime("%Y-%m-%d 23:30:00")
                name_val = t_name.strip() if t_name else t_code.strip()
                amt_l = int(t_qty.replace(',','')) * float(t_prc.replace(',',''))
                parsed_list.append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, t_code.strip(), t_dir), "Source": "Kakao", "Currency": "USD", "Category": "Trade", "Type": "Buy" if t_dir == "매수" else "Sell", "Ticker": t_code.strip(), "Name": name_val, "Qty": int(t_qty.replace(',','')), "Price": float(t_prc.replace(',','')), "Amount_Local": amt_l, "Amount_KRW": 0, "Note": f"카톡파싱_{t_str}" })
                continue

            jpy_div_m = re.search(r'최원준님\s*(\d{2}/\d{2}).*?([A-Z0-9.]+)/.*?JPY\s*([\d.]+)\s*세전배당입금', chunk)
            if jpy_div_m:
                d_str, t_tkr, t_amt = jpy_div_m.groups(); m, d = map(int, d_str.split('/'))
                dt_str = datetime(base_year, m, d, 15, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
                amt_val = round(float(t_amt) * (1 - 0.15315), 2) # 세금추정 자동화
                parsed_list.append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, t_tkr.strip(), "Div"), "Source": "Kakao", "Currency": "JPY", "Category": "Money", "Type": "Dividend", "Ticker": t_tkr.strip(), "Name": "-", "Qty": 0, "Price": 0, "Amount_Local": amt_val, "Amount_KRW": 0, "Note": "카톡파싱_배당(15.3%추정)" })
                continue

            usd_div_m = re.search(r'최원준님\s*(\d{2}/\d{2}).*?([A-Z]+)/.*?USD\s*([\d.]+)\s*세전배당입금', chunk)
            if usd_div_m:
                d_str, t_tkr, t_amt = usd_div_m.groups(); m, d = map(int, d_str.split('/'))
                dt_str = datetime(base_year, m, d, 15, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
                amt_val = round(float(t_amt) * 0.85, 2)
                parsed_list.append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, t_tkr.strip(), "Div"), "Source": "Kakao", "Currency": "USD", "Category": "Money", "Type": "Dividend", "Ticker": t_tkr.strip(), "Name": "-", "Qty": 0, "Price": 0, "Amount_Local": amt_val, "Amount_KRW": 0, "Note": "카톡파싱_배당(15%추정)" })
                continue

            dom_div_m = re.search(r'ETF 결산분배금 입금 안내.*?\*\s*종목명\s*:\s*(.*?)\s*\*.*?\*\s*입금액\s*:\s*([\d,]+)원.*?\*\s*입금일자\s*:\s*(\d{4})년\s*(\d{2})월\s*(\d{2})일', chunk)
            if dom_div_m:
                t_name, t_amt, y, m, d = dom_div_m.groups()
                t_tkr = {'TIGER 미국배당다우존스': '458730'}.get(t_name.strip(), t_name.strip())
                dt_str = datetime(int(y), int(m), int(d), 15, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
                parsed_list.append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, t_tkr, "Div"), "Source": "Kakao", "Currency": "KRW", "Category": "Money", "Type": "Dividend", "Ticker": t_tkr, "Name": t_name.strip(), "Qty": 0, "Price": 0, "Amount_Local": 0, "Amount_KRW": float(t_amt.replace(',', '')), "Note": "카톡파싱_국내배당" })
                continue

            buy_ex_m = re.search(r'외화매수환전.*?￦([0-9,]+).*?@([0-9,.]+).*?(JPY|USD)\s*([0-9,.]+)', chunk)
            if buy_ex_m:
                k_amt, ex_rt, currency, u_amt = buy_ex_m.groups()
                dt_str = datetime.combine(base_date, datetime.min.time()).replace(hour=14, minute=0).strftime("%Y-%m-%d %H:%M:%S")
                parsed_list.append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, "-", "ExB"), "Source": "Kakao", "Currency": currency, "Category": "Money", "Type": f"KRW_to_{currency}", "Ticker": "-", "Name": "-", "Qty": 0, "Price": float(ex_rt.replace(',','')), "Amount_Local": float(u_amt.replace(',', '')), "Amount_KRW": float(k_amt.replace(',', '')), "Note": "카톡파싱_매수환전" })
                continue
                
            sell_ex_m = re.search(r'외화매도환전.*?(JPY|USD)\s*([0-9,.]+).*?@([0-9,.]+).*?￦([0-9,]+)', chunk)
            if sell_ex_m:
                currency, u_amt, ex_rt, k_amt = sell_ex_m.groups()
                dt_str = datetime.combine(base_date, datetime.min.time()).replace(hour=14, minute=0).strftime("%Y-%m-%d %H:%M:%S")
                parsed_list.append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, "-", "ExS"), "Source": "Kakao", "Currency": currency, "Category": "Money", "Type": f"{currency}_to_KRW", "Ticker": "-", "Name": "-", "Qty": 0, "Price": float(ex_rt.replace(',','')), "Amount_Local": float(u_amt.replace(',', '')), "Amount_KRW": float(k_amt.replace(',', '')), "Note": "카톡파싱_매도환전" })
                continue
        except: continue
        
    return parsed_list

# -------------------------------------------------------------------
# [6] Main UI
# -------------------------------------------------------------------
def main():
    try:
        df_ledger = load_data()
    except Exception as e:
        st.error(f"🚨 DB 로딩 실패: {e}"); st.stop()
        
    cash_bal, avg_rate, invested_krw_dict, fx_realized, dom_principal_sum, portfolio = process_unified_ledger(df_ledger)
    
    usd_bal = cash_bal.get('USD', 0)
    jpy_bal = cash_bal.get('JPY', 0)
    dom_cash = cash_bal.get('KRW', 0)
    usd_rate = avg_rate.get('USD', 0)
    jpy_rate = avg_rate.get('JPY', 0)
    usd_krw_sum = invested_krw_dict.get('USD', 0)
    jpy_krw_sum = invested_krw_dict.get('JPY', 0)
    usd_fx_real = fx_realized.get('USD', 0)
    jpy_fx_real = fx_realized.get('JPY', 0)
    
    prices = st.session_state.get('price_cache', {})
    cur_usd_rate = st.session_state.get('fx_rate_usd', 0.0)
    cur_jpy_rate = st.session_state.get('fx_rate_jpy', 0.0)
    
    has_valid_prices = sum(prices.values()) > 0 if prices else False
    is_skeleton = not has_valid_prices
    
    total_principal_all = usd_krw_sum + jpy_krw_sum + dom_principal_sum
    total_stock_val_krw = 0.0
    usd_div_total_for = 0.0
    jpy_div_total_for = 0.0
    us_stock_val_krw = 0.0
    jp_stock_val_krw = 0.0
    
    for tk, data in portfolio.items():
        if data['currency'] == 'USD': usd_div_total_for += data['accum_div_for']
        elif data['currency'] == 'JPY': jpy_div_total_for += data['accum_div_for']

        if data['qty'] > 0:
            cur_p = prices.get(tk, 0)
            if data['currency'] == 'KRW': 
                total_stock_val_krw += data['qty'] * cur_p
            elif data['currency'] == 'USD': 
                val_krw = data['qty'] * cur_p * cur_usd_rate
                total_stock_val_krw += val_krw
                us_stock_val_krw += val_krw
            elif data['currency'] == 'JPY': 
                val_krw = data['qty'] * cur_p * cur_jpy_rate
                total_stock_val_krw += val_krw
                jp_stock_val_krw += val_krw

    cash_val_krw = (usd_bal * cur_usd_rate) + (jpy_bal * cur_jpy_rate) + dom_cash
    total_asset_krw = total_stock_val_krw + cash_val_krw
    total_pl_krw = total_asset_krw - total_principal_all
    total_pl_pct = (total_pl_krw / total_principal_all * 100) if total_principal_all > 0 else 0
    total_is_plus = total_pl_krw >= 0

    total_realized_sum = sum(d['realized_krw'] for d in portfolio.values())
    total_div_sum_krw = sum(d['accum_div_krw'] if d['currency']=='KRW' else d['accum_div_for']*(cur_usd_rate if d['currency']=='USD' else cur_jpy_rate) for d in portfolio.values())
    total_real_div_fx = total_realized_sum + total_div_sum_krw + usd_fx_real + jpy_fx_real

    us_asset_krw = us_stock_val_krw + (usd_bal * cur_usd_rate)
    us_pl_krw = us_asset_krw - usd_krw_sum
    us_pl_pct = (us_pl_krw / usd_krw_sum * 100) if usd_krw_sum > 0 else 0
    us_is_plus = us_pl_krw >= 0
    us_realized_sum = sum(d['realized_krw'] for d in portfolio.values() if d['currency'] == 'USD') + (usd_div_total_for * cur_usd_rate) + usd_fx_real
    
    usd_bep_num = usd_krw_sum - sum(d['realized_krw'] for d in portfolio.values() if d['currency'] == 'USD') - (usd_div_total_for * cur_usd_rate)
    usd_assets = sum(d['qty'] * prices.get(tk,0) for tk, d in portfolio.items() if d['currency'] == 'USD') + usd_bal
    usd_bep = (usd_bep_num / usd_assets) if usd_assets > 0 else 0.0
    usd_margin = cur_usd_rate - usd_bep

    jp_asset_krw = jp_stock_val_krw + (jpy_bal * cur_jpy_rate)
    jp_pl_krw = jp_asset_krw - jpy_krw_sum
    jp_pl_pct = (jp_pl_krw / jpy_krw_sum * 100) if jpy_krw_sum > 0 else 0
    jp_is_plus = jp_pl_krw >= 0
    jp_realized_sum = sum(d['realized_krw'] for d in portfolio.values() if d['currency'] == 'JPY') + (jpy_div_total_for * cur_jpy_rate) + jpy_fx_real

    jpy_bep_num = jpy_krw_sum - sum(d['realized_krw'] for d in portfolio.values() if d['currency'] == 'JPY') - (jpy_div_total_for * cur_jpy_rate)
    jpy_assets = sum(d['qty'] * prices.get(tk,0) for tk, d in portfolio.items() if d['currency'] == 'JPY') + jpy_bal
    jpy_bep = (jpy_bep_num / jpy_assets) if jpy_assets > 0 else 0.0
    jpy_margin = cur_jpy_rate - jpy_bep

    if is_skeleton:
        top_asset_str = "로딩중..." if st.session_state.get('needs_fetch') else "시세 API 점검중"
        top_pl_str = "-"; us_pl_str = "-"; jp_pl_str = "-"
        top_usd_margin_str = "-"; top_usd_bep_str = "-"; top_jpy_margin_str = "-"; top_jpy_bep_str = "-"
        card_cls_tot = "stock-card card-neutral"; card_cls_us = "stock-card card-neutral"; card_cls_jp = "stock-card card-neutral"
        txt_cls_tot = "txt-sub"; txt_cls_us = "txt-sub"; txt_cls_jp = "txt-sub"
    else:
        top_asset_str = f"₩ {total_asset_krw:,.0f}"
        top_pl_str = f"{'▲' if total_is_plus else '▼'} {abs(total_pl_krw):,.0f} ({'+' if total_is_plus else ''}{total_pl_pct:.2f}%)"
        us_pl_str = f"{'▲' if us_is_plus else '▼'} {abs(us_pl_krw):,.0f} ({'+' if us_is_plus else ''}{us_pl_pct:.2f}%)"
        jp_pl_str = f"{'▲' if jp_is_plus else '▼'} {abs(jp_pl_krw):,.0f} ({'+' if jp_is_plus else ''}{jp_pl_pct:.2f}%)"
        
        top_usd_margin_str = f"{'+' if usd_margin >= 0 else ''}{usd_margin:,.2f} 원" if usd_assets > 0 else "-"
        top_usd_bep_str = f"₩ {usd_bep:,.2f}" if usd_assets > 0 else "-"
        
        # 1엔 단위 4자리 표기
        top_jpy_margin_str = f"{'+' if jpy_margin >= 0 else ''}{jpy_margin:,.4f} 원" if jpy_assets > 0 else "-"
        top_jpy_bep_str = f"₩ {jpy_bep:,.4f}" if jpy_assets > 0 else "-"

        card_cls_tot = f"stock-card {'card-up' if total_is_plus else 'card-down'}"
        card_cls_us = f"stock-card {'card-up' if us_is_plus else 'card-down'}" if (us_asset_krw > 0 or us_realized_sum != 0) else "stock-card card-neutral"
        card_cls_jp = f"stock-card {'card-up' if jp_is_plus else 'card-down'}" if (jp_asset_krw > 0 or jp_realized_sum != 0) else "stock-card card-neutral"
        
        txt_cls_tot = "txt-red" if total_is_plus else "txt-blue"
        txt_cls_us = "txt-red" if us_is_plus else "txt-blue"
        txt_cls_jp = "txt-red" if jp_is_plus else "txt-blue"

    c1, c2 = st.columns([3, 1])
    with c1: st.title("🚀 Investment Command Center")
    with c2:
        if st.button("🔄 시세 새로고침", use_container_width=True):
            st.session_state['needs_fetch'] = True
            st.rerun()

    # -------------------------------------------------------------------
    # [KPI: 자산급 5대 큐브 전환 (현재 US, JP, KRW 기반 구현)]
    # -------------------------------------------------------------------
    kpi_cols = st.columns(3)
    with kpi_cols[0]:
        st.markdown(f"""
        <div class="{card_cls_tot}">
            <div class="card-header"><span class="card-ticker">총 자산</span><span class="card-price">Total Assets</span></div>
            <div class="card-main-val">{top_asset_str}</div>
            <div class="card-sub-box {txt_cls_tot}">{top_pl_str}</div>
            <details><summary style="text-align:right; font-size:0.8rem; color:#888; cursor:pointer;">상세 (DB)</summary>
                <table style="width:100%; font-size:0.8rem; color:#ccc;">
                    <tr><td>총 투입 원금</td><td style="text-align:right;">₩ {total_principal_all:,.0f}</td></tr>
                    <tr><td>주식 평가액</td><td style="text-align:right;">₩ {total_stock_val_krw:,.0f}</td></tr>
                    <tr><td>예수금 총액</td><td style="text-align:right;">₩ {cash_val_krw:,.0f}</td></tr>
                    <tr><td style="color:#A8C7FA">누적 실현/배당</td><td style="text-align:right;">₩ {total_real_div_fx:,.0f}</td></tr>
                </table>
            </details>
        </div>
        """, unsafe_allow_html=True)
        
    if us_asset_krw > 0 or us_realized_sum != 0:
        with kpi_cols[1]:
            st.markdown(f"""
            <div class="{card_cls_us}">
                <div class="card-header"><span class="card-ticker">미국 자산</span><span class="card-price">US Assets</span></div>
                <div class="card-main-val">₩ {us_asset_krw:,.0f}</div>
                <div class="card-sub-box {txt_cls_us}">{us_pl_str}</div>
                <details><summary style="text-align:right; font-size:0.8rem; color:#888; cursor:pointer;">상세 (DB)</summary>
                    <table style="width:100%; font-size:0.8rem; color:#ccc;">
                        <tr><td>투입 원금</td><td style="text-align:right;">₩ {usd_krw_sum:,.0f}</td></tr>
                        <tr><td style="color:#A8C7FA">누적 실현/배당</td><td style="text-align:right;">₩ {us_realized_sum:,.0f}</td></tr>
                        <tr><td>BEP 환율</td><td style="text-align:right;">{top_usd_bep_str}</td></tr>
                        <tr><td style="color:#AAA">안전마진</td><td style="text-align:right;">{top_usd_margin_str}</td></tr>
                    </table>
                </details>
            </div>
            """, unsafe_allow_html=True)
            
    if jp_asset_krw > 0 or jp_realized_sum != 0:
        with kpi_cols[2]:
            st.markdown(f"""
            <div class="{card_cls_jp}">
                <div class="card-header"><span class="card-ticker">일본 자산</span><span class="card-price">JP Assets</span></div>
                <div class="card-main-val">₩ {jp_asset_krw:,.0f}</div>
                <div class="card-sub-box {txt_cls_jp}">{jp_pl_str}</div>
                <details><summary style="text-align:right; font-size:0.8rem; color:#888; cursor:pointer;">상세 (DB)</summary>
                    <table style="width:100%; font-size:0.8rem; color:#ccc;">
                        <tr><td>투입 원금</td><td style="text-align:right;">₩ {jpy_krw_sum:,.0f}</td></tr>
                        <tr><td style="color:#A8C7FA">누적 실현/배당</td><td style="text-align:right;">₩ {jp_realized_sum:,.0f}</td></tr>
                        <tr><td>BEP 환율</td><td style="text-align:right;">{top_jpy_bep_str}</td></tr>
                        <tr><td style="color:#AAA">안전마진</td><td style="text-align:right;">{top_jpy_margin_str}</td></tr>
                    </table>
                </details>
            </div>
            """, unsafe_allow_html=True)

    tab_dash, tab_input, tab_detail, tab_log = st.tabs(["📊 대시보드", "🕹️ 입력 매니저", "📋 통합 상세", "📜 통합 로그"])
    
    with tab_dash:
        # -------------------------------------------------------------------
        # [예수금 큐브의 대시보드 상단 배치]
        # -------------------------------------------------------------------
        st.caption("**🏦 예수금 (Cash)** Sector")
        cash_cols = st.columns(3)
        with cash_cols[0]:
            st.markdown(f"""
            <div class="stock-card {'card-up' if usd_margin >= 0 else 'card-down'}" style="margin-bottom: 0;">
                <div class="card-header"><span class="card-ticker">달러 잔고</span><span class="card-price">USD Cash</span></div>
                <div class="card-main-val">$ {usd_bal:,.2f}</div>
                <div class="card-sub-box">
                    <span style="color:#888; font-weight:400;">매수평단 ₩ {usd_rate:,.2f}</span><br>
                    <span style="color:#888; font-weight:400;">BEP {top_usd_bep_str}</span><br>
                    <span class="{'txt-red' if usd_margin >= 0 else 'txt-blue'}">마진 {top_usd_margin_str}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with cash_cols[1]:
            st.markdown(f"""
            <div class="stock-card {'card-up' if jpy_margin >= 0 else 'card-down'}" style="margin-bottom: 0;">
                <div class="card-header"><span class="card-ticker">엔화 잔고</span><span class="card-price">JPY Cash</span></div>
                <div class="card-main-val">¥ {jpy_bal:,.0f}</div>
                <div class="card-sub-box">
                    <span style="color:#888; font-weight:400;">매수평단 ₩ {jpy_rate:,.4f}</span><br>
                    <span style="color:#888; font-weight:400;">BEP {top_jpy_bep_str}</span><br>
                    <span class="{'txt-red' if jpy_margin >= 0 else 'txt-blue'}">마진 {top_jpy_margin_str}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with cash_cols[2]:
            st.markdown(f"""
            <div class="stock-card card-neutral" style="margin-bottom: 0;">
                <div class="card-header"><span class="card-ticker">원화 잔고</span><span class="card-price">KRW Cash</span></div>
                <div class="card-main-val">₩ {dom_cash:,.0f}</div>
                <div class="card-sub-box">
                    <br><br>
                    <span class="txt-sub">-</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("<hr style='margin: 10px 0 25px 0; border-color: #333;'>", unsafe_allow_html=True)

        for sec in ['배당', '테크', '의료', '리츠', '기타']:
            target_list = SECTOR_ORDER_LIST.get(sec, [])
            if sec == '기타':
                all_defined = [t for lst in SECTOR_ORDER_LIST.values() for t in lst]
                target_list = [t for t in portfolio.keys() if t not in all_defined and portfolio[t]['qty'] > 0]
            valid_tickers = [t for t in target_list if t in portfolio and portfolio[t]['qty'] > 0]
            if not valid_tickers: continue
            
            st.caption(f"**{sec}** Sector")
            cols = st.columns(4)
            for idx, tk in enumerate(valid_tickers):
                data = portfolio[tk]; qty = data['qty']; cur_p = prices.get(tk, 0)
                
                display_name = tk
                if data['currency'] == 'JPY':
                    n = data.get('name', '')
                    base_tk = tk.replace('.T', '')
                    if n and n != tk and n != base_tk and n != '-': display_name = f"{n}({base_tk})"
                    else: display_name = base_tk

                invested_krw = data['invested_krw']
                div_krw = data['accum_div_krw'] if data['currency'] == 'KRW' else data['accum_div_for'] * (cur_usd_rate if data['currency'] == 'USD' else cur_jpy_rate)
                
                if is_skeleton:
                    price_display = "로딩중..." if st.session_state.get('needs_fetch') else "API 확인요망"
                    val_krw_str = "-"; pl_str = "-"; margin_tk_str = "-"
                    card_cls_tk = "stock-card card-neutral"
                    txt_cls_tk = "txt-sub"
                else:
                    if data['currency'] == 'KRW':
                        val_krw = qty * cur_p
                        total_pl_tk = val_krw - invested_krw + data['realized_krw'] + div_krw
                        margin_tk_str = "-"
                        price_display = f"₩ {cur_p:,.0f}"
                    else:
                        fx = cur_usd_rate if data['currency'] == 'USD' else cur_jpy_rate
                        val_krw = qty * cur_p * fx
                        total_pl_tk = val_krw - invested_krw + data['realized_krw'] + div_krw
                        bep_rate_tk = (invested_krw - data['realized_krw'] - div_krw) / (qty * cur_p) if (qty*cur_p) > 0 else 0
                        margin_tk = fx - bep_rate_tk
                        margin_tk_str = f"{margin_tk:+.4f} 원" if data['currency'] == 'JPY' else f"{margin_tk:+.2f} 원"
                        price_display = f"${cur_p:.2f}" if data['currency'] == 'USD' else f"¥ {cur_p:,.0f}"

                    total_ret = (total_pl_tk / invested_krw * 100) if invested_krw > 0 else 0
                    is_p = total_pl_tk >= 0
                    val_krw_str = f"₩ {val_krw:,.0f}"
                    pl_str = f"{'▲' if is_p else '▼'} {abs(total_pl_tk):,.0f} ({'+' if is_p else ''}{total_ret:.1f}%)"
                    card_cls_tk = f"stock-card {'card-up' if is_p else 'card-down'}"
                    txt_cls_tk = "txt-red" if is_p else "txt-blue"

                html = f"""
                <div class="{card_cls_tk}">
                    <div class="card-header"><span class="card-ticker">{display_name}</span><span class="card-price">{price_display}</span></div>
                    <div class="card-main-val">{val_krw_str}</div>
                    <div class="card-sub-box {txt_cls_tk}">{pl_str}</div>
                    <details><summary style="text-align:right; font-size:0.8rem; color:#888; cursor:pointer;">상세 (DB)</summary>
                        <table style="width:100%; font-size:0.8rem; color:#ccc;">
                            <tr><td>보유량</td><td style="text-align:right;">{qty:,.0f} 주</td></tr>
                            <tr><td>원금</td><td style="text-align:right;">₩ {invested_krw:,.0f}</td></tr>
                            <tr><td>배당</td><td style="text-align:right;">₩ {div_krw:,.0f}</td></tr>
                            <tr><td style="color:#AAA">안전마진</td><td style="text-align:right;">{margin_tk_str}</td></tr>
                        </table>
                    </details>
                </div>
                """
                cols[idx % 4].markdown(html, unsafe_allow_html=True)

    # -------------------------------------------------------------------
    # [입력 매니저: 임시 카드 UI (환전 입력창 분리 완벽 적용)]
    # -------------------------------------------------------------------
    with tab_input:
        st.info("💡 카톡 메시지 분석 또는 수동 입력을 통해 임시 카드를 생성하고 검수 후 DB(통합원장)로 전송합니다.")
        c1, c2 = st.columns([1, 2])
        with c1: 
            ref_date = st.date_input("기준 날짜", datetime.now())
            if st.button("💰 원화 입출금 (수동추가)", use_container_width=True):
                dt_str = datetime.combine(ref_date, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S")
                st.session_state['parsed_data'].append({ "Date": dt_str, "PK_Hash": generate_pk(dt_str, "-", "Dep"), "Source": "Manual", "Currency": "KRW", "Category": "Money", "Type": "Deposit", "Ticker": "-", "Name": "-", "Qty": 0, "Price": 0, "Amount_Local": 0, "Amount_KRW": 0, "Note": "수동_입금" })
                st.rerun()
        with c2: 
            raw_text = st.text_area("카톡 내용 붙여넣기", height=120, placeholder="[한국투자증권 체결안내]08:05...")
            if st.button("🚀 카톡 데이터 분석", type="primary", use_container_width=True):
                if raw_text:
                    parsed_items = parse_kakaotalk_final(raw_text, ref_date)
                    if parsed_items:
                        st.session_state['parsed_data'].extend(parsed_items)
                        st.rerun()
                    else: st.warning("⚠️ 분석할 내역을 찾지 못했습니다.")

        if st.session_state['parsed_data']:
            st.markdown("---")
            cc1, cc2 = st.columns([3, 1])
            with cc1: st.subheader("📝 검수 대기열 (수정 가능)")
            with cc2:
                if st.button("🗑️ 전체 취소", use_container_width=True):
                    st.session_state['parsed_data'] = []
                    st.rerun()

            for i, item in enumerate(st.session_state['parsed_data']):
                with st.container():
                    st.markdown("<div class='input-card'>", unsafe_allow_html=True)
                    cols = st.columns([2, 1, 1.5, 2, 1])
                    
                    with cols[0]:
                        tk_disp = item.get('Name') or item['Ticker']
                        st.markdown(f"**[{item['Currency']}] {item['Category']}** <span style='color:#888; font-size:0.9em;'>({item['Date']})</span><br><span style='color:#A8C7FA; font-weight:bold;'>{tk_disp}</span> ({item['Type']})", unsafe_allow_html=True)
                    with cols[1]:
                        item['Qty'] = st.number_input("수량(Qty)", value=float(item['Qty']), key=f"qty_{i}")
                    with cols[2]:
                        if 'Exchange' in item['Type'] or 'to_' in item['Type']:
                            item['Amount_Local'] = st.number_input("외화액", value=float(item['Amount_Local']), key=f"f_{i}")
                            item['Amount_KRW'] = st.number_input("원화액", value=float(item['Amount_KRW']), key=f"k_{i}")
                        elif item['Category'] == 'Money' and item['Currency'] == 'KRW':
                            item['Amount_KRW'] = st.number_input("원화(₩)", value=float(item['Amount_KRW']), key=f"k_{i}")
                        elif item['Category'] == 'Money' and item['Currency'] != 'KRW':
                            item['Amount_Local'] = st.number_input("외화 배당", value=float(item['Amount_Local']), key=f"l_{i}", step=0.01)
                        else:
                            item['Price'] = st.number_input("단가", value=float(item['Price']), key=f"p_{i}", step=0.01)
                    with cols[3]:
                        item['Note'] = st.text_input("메모", value=item['Note'], key=f"note_{i}")
                    with cols[4]:
                        btn_c1, btn_c2, btn_c3 = st.columns(3)
                        if btn_c1.button("⬆️", key=f"up_{i}") and i > 0:
                            st.session_state['parsed_data'][i], st.session_state['parsed_data'][i-1] = st.session_state['parsed_data'][i-1], st.session_state['parsed_data'][i]
                            st.rerun()
                        if btn_c2.button("⬇️", key=f"dw_{i}") and i < len(st.session_state['parsed_data'])-1:
                            st.session_state['parsed_data'][i], st.session_state['parsed_data'][i+1] = st.session_state['parsed_data'][i+1], st.session_state['parsed_data'][i]
                            st.rerun()
                        if btn_c3.button("❌", key=f"del_{i}"):
                            st.session_state['parsed_data'].pop(i)
                            st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)

            if st.button("💾 검수 완료 및 통합원장(DB) 저장", type="primary", use_container_width=True):
                client = get_gsheet_client()
                sh = client.open("Investment_Dashboard_DB")
                ws_ledger = sh.worksheet("Global_Unified_Ledger")
                
                rows_to_append = []
                for item in st.session_state['parsed_data']:
                    # 만약 Trade면서 금액이 안적혀있으면 단가*수량으로 채워줌
                    if item['Category'] == 'Trade':
                        if item['Currency'] == 'KRW' and item['Amount_KRW'] == 0:
                            item['Amount_KRW'] = item['Qty'] * item['Price']
                        elif item['Currency'] != 'KRW' and item['Amount_Local'] == 0:
                            item['Amount_Local'] = item['Qty'] * item['Price']

                    rows_to_append.append([
                        item['Date'], item['PK_Hash'], item['Source'], item['Currency'], 
                        item['Category'], item['Type'], item['Ticker'], item['Name'], 
                        item['Qty'], item['Price'], item['Amount_Local'], item['Amount_KRW'], item['Note']
                    ])
                    
                ws_ledger.append_rows(rows_to_append)
                st.success(f"✅ {len(rows_to_append)}건 DB 저장 완료! 시세를 재동기화합니다.")
                st.session_state['parsed_data'] = [] 
                st.cache_data.clear() 
                st.session_state['needs_fetch'] = True 
                time.sleep(1.5)
                st.rerun()

    # -------------------------------------------------------------------
    # [통합 상세 테이블: 실현+배당 열에 FX 환차익 이관 유지]
    # -------------------------------------------------------------------
    with tab_detail:
        header = "<table class='int-table'><thead><tr><th>종목</th><th>평가액 (₩)</th><th>평가손익</th><th>환손익</th><th>실현+배당</th><th>총 손익 (Total)</th><th>안전마진</th></tr></thead><tbody>"
        rows_html = ""; sum_eval_krw = 0; sum_realized = 0
        sorted_tickers = sorted(list(portfolio.keys()), key=lambda x: SORT_ORDER_TABLE.index(x) if x in SORT_ORDER_TABLE else 999)
        
        for tk in sorted_tickers:
            if tk == 'Cash': continue
            data = portfolio[tk]; qty = data['qty']; cur_p = prices.get(tk, 0)
            if qty == 0 and data['realized_krw'] == 0 and data['accum_div_for'] == 0 and data['accum_div_krw'] == 0: continue

            display_name = tk
            if data['currency'] == 'JPY':
                n = data.get('name', '')
                base_tk = tk.replace('.T', '')
                if n and n != tk and n != base_tk and n != '-': display_name = f"{n}({base_tk})"
                else: display_name = base_tk

            if is_skeleton:
                rows_html += f"<tr><td>{display_name}</td><td>-</td><td>-</td><td>-</td><td>{data['realized_krw'] + (data['accum_div_krw'] if data['currency']=='KRW' else 0):,.0f}</td><td>-</td><td style='color:#ccc;'>-</td></tr>"
                continue

            if data['currency'] == 'KRW':
                eval_krw = qty * cur_p; div_krw = data['accum_div_krw']
                total_pl = eval_krw - data['invested_krw'] + data['realized_krw'] + div_krw
                price_profit = eval_krw - data['invested_krw'] if qty > 0 else 0
                fx_profit_str = "-"; margin_str = "-"
            else:
                fx = cur_usd_rate if data['currency'] == 'USD' else cur_jpy_rate
                eval_krw = qty * cur_p * fx; div_krw = data['accum_div_for'] * fx
                total_pl = eval_krw - data['invested_krw'] + data['realized_krw'] + div_krw
                if qty > 0:
                    my_avg_rate_tk = data['invested_krw'] / data['invested_for'] if data['invested_for'] > 0 else 0
                    fx_profit_str = f"{data['invested_for'] * (fx - my_avg_rate_tk):,.0f}"
                    price_profit = (qty * cur_p - data['invested_for']) * fx
                else: price_profit = 0; fx_profit_str = "-"
                
                bep_tk = (data['invested_krw'] - (data['realized_krw'] + div_krw)) / (qty * cur_p) if (qty*cur_p) > 0 else 0.0
                margin_str = f"{fx - bep_tk:+.4f}" if qty > 0 else "-"

            sum_eval_krw += eval_krw; sum_realized += (data['realized_krw'] + div_krw)
            cls_tot = "txt-red" if total_pl >= 0 else "txt-blue"
            rows_html += f"<tr><td>{display_name}</td><td>{eval_krw:,.0f}</td><td class='{'txt-red' if price_profit >=0 else 'txt-blue'}'>{price_profit:,.0f}</td><td class='{'txt-sub' if data['currency']=='KRW' else ('txt-red' if float(fx_profit_str.replace(',',''))>=0 else 'txt-blue') if fx_profit_str!='-' else 'txt-sub'}'>{fx_profit_str}</td><td>{data['realized_krw'] + div_krw:,.0f}</td><td class='{cls_tot} {'bg-red' if total_pl>=0 else 'bg-blue'}'><b>{total_pl:,.0f}</b></td><td style='color:#ccc;'>{margin_str}</td></tr>"
            
        # 외화 예수금 행 추가 (잔고가 있거나, 환전 실현손익이 존재할 경우에만 표시)
        if not is_skeleton:
            if usd_bal > 0 or usd_fx_real != 0:
                usd_cash_eval = usd_bal * cur_usd_rate
                usd_cash_fx = usd_cash_eval - (usd_bal * usd_rate)
                cls_usd = "txt-red" if usd_cash_fx >= 0 else "txt-blue"
                usd_cash_total_pl = usd_cash_fx + usd_fx_real
                cls_usd_tot = "txt-red" if usd_cash_total_pl >= 0 else "txt-blue"
                rows_html += f"<tr style='background-color:#1c1d1f; color:#999; font-style:italic;'><td>💵 USD 예수금</td><td>{usd_cash_eval:,.0f}</td><td>-</td><td class='{cls_usd}'>{usd_cash_fx:,.0f}</td><td class='{'txt-red' if usd_fx_real>=0 else 'txt-blue' if usd_fx_real<0 else 'txt-sub'}'>{usd_fx_real:,.0f}</td><td class='{cls_usd_tot}'><b>{usd_cash_total_pl:,.0f}</b></td><td>-</td></tr>"
            
            if jpy_bal > 0 or jpy_fx_real != 0:
                jpy_cash_eval = jpy_bal * cur_jpy_rate
                jpy_cash_fx = jpy_cash_eval - (jpy_bal * jpy_rate)
                cls_jpy = "txt-red" if jpy_cash_fx >= 0 else "txt-blue"
                jpy_cash_total_pl = jpy_cash_fx + jpy_fx_real
                cls_jpy_tot = "txt-red" if jpy_cash_total_pl >= 0 else "txt-blue"
                rows_html += f"<tr style='background-color:#1c1d1f; color:#999; font-style:italic;'><td>💴 JPY 예수금</td><td>{jpy_cash_eval:,.0f}</td><td>-</td><td class='{cls_jpy}'>{jpy_cash_fx:,.0f}</td><td class='{'txt-red' if jpy_fx_real>=0 else 'txt-blue' if jpy_fx_real<0 else 'txt-sub'}'>{jpy_fx_real:,.0f}</td><td class='{cls_jpy_tot}'><b>{jpy_cash_total_pl:,.0f}</b></td><td>-</td></tr>"

            if dom_cash > 0:
                rows_html += f"<tr style='background-color:#1c1d1f; color:#999; font-style:italic;'><td>🇰🇷 KRW 예수금</td><td>{dom_cash:,.0f}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"

        if is_skeleton:
            total_row = f"<tr class='row-total'><td>TOTAL</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
        else:
            total_assets = sum_eval_krw + (usd_bal * cur_usd_rate) + (jpy_bal * cur_jpy_rate) + dom_cash
            final_pl_calc = total_assets - total_principal_all
            total_realized_sum_table = sum_realized + usd_fx_real + jpy_fx_real
            total_row = f"<tr class='row-total'><td>TOTAL</td><td>{total_assets:,.0f}</td><td>-</td><td>-</td><td>{total_realized_sum_table:,.0f}</td><td class='{'txt-red' if final_pl_calc>=0 else 'txt-blue'}'>{final_pl_calc:,.0f}</td><td>-</td></tr>"
            
        st.markdown(header + rows_html + total_row + "</tbody></table>", unsafe_allow_html=True)

    with tab_log:
        st.caption("📂 단일 통합 원장 (Global Unified Ledger)")
        try: st.dataframe(df_ledger.fillna(''), use_container_width=True)
        except: st.info("아직 데이터가 없습니다.")

    # Phase 3: 백그라운드 페칭
    if st.session_state.get('needs_fetch', False):
        st.toast("📡 최신 시세를 동기화합니다...", icon="🔄")
        new_prices = {}
        old_prices = st.session_state.get('price_cache', {})
        
        for tk, data in portfolio.items():
            p = 0
            if data['currency'] == 'KRW':
                try: p = yf.Ticker(f"{data['raw_ticker']}.KS").history(period="1d")['Close'].iloc[-1]
                except: p = 0
            elif data['currency'] == 'JPY':
                try: p = yf.Ticker(data['raw_ticker']).history(period="1d")['Close'].iloc[-1]
                except: p = 0
            else: 
                p = kis.get_current_price(tk)
            
            if p <= 0 and tk in old_prices and old_prices[tk] > 0: p = old_prices[tk]
            new_prices[tk] = p
        
        try:
            usd_data = yf.Ticker("KRW=X").history(period="1d")
            new_usd = usd_data['Close'].iloc[-1] if not usd_data.empty else 1450.0
        except: new_usd = 1450.0

        try:
            jpy_data = yf.Ticker("JPYKRW=X").history(period="1d")
            new_jpy = jpy_data['Close'].iloc[-1] if not jpy_data.empty else 9.5
        except: new_jpy = 9.5
        
        st.session_state['fx_rate_usd'] = new_usd
        st.session_state['fx_rate_jpy'] = new_jpy
        st.session_state['price_cache'] = new_prices
        st.session_state['needs_fetch'] = False 
        st.rerun() 

if __name__ == "__main__":
    main()
