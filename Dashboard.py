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
# [1] 설정 & 다크모드 (Neutral 테마 보존)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="🏦")

if 'price_cache' not in st.session_state: st.session_state['price_cache'] = {}
if 'needs_fetch' not in st.session_state: st.session_state['needs_fetch'] = True

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
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# [2] 맵핑 (올림푸스 '의료' 섹터 추가)
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

# -------------------------------------------------------------------
# [3] 로드 (분리된 시트 반영)
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
            if not records: return pd.DataFrame(columns=default_columns)
            df = pd.DataFrame(records)
            df.columns = df.columns.astype(str).str.strip()
            return df
        except: return pd.DataFrame(columns=default_columns)

    df_usd_trade = get_safe_df("USD_Trade_Log", ['Date', 'Order_ID', 'Ticker', 'Name', 'Type', 'Qty', 'Price_USD', 'Ex_Avg_Rate', 'Note'])
    df_usd_money = get_safe_df("USD_Money_Log", ['Date', 'Order_ID', 'Type', 'Ticker', 'KRW-USD_Amount', 'USD_Amount', 'Ex_Rate', 'Avg_Rate', 'Balance', 'Note'])
    df_jpy_trade = get_safe_df("JPY_Trade_Log", ['Date', 'Order_ID', 'Ticker', 'Name', 'Type', 'Qty', 'Price_JPY', 'Ex_Avg_Rate', 'Note'])
    df_jpy_money = get_safe_df("JPY_Money_Log", ['Date', 'Order_ID', 'Type', 'Ticker', 'KRW-JPY_Amount', 'JPY_Amount', 'Ex_Rate', 'Avg_Rate', 'Balance', 'Note'])
    df_domestic = get_safe_df("Domestic_Log", ['Date', 'Type', 'Ticker', 'Name', 'Qty', 'Price_KRW', 'Amount_KRW', 'Note'])

    return df_usd_trade, df_usd_money, df_jpy_trade, df_jpy_money, df_domestic

# -------------------------------------------------------------------
# [4] 계산 엔진 (외화 범용화 모듈)
# -------------------------------------------------------------------
def process_foreign_currency(df_t_raw, df_m_raw, curr_label):
    df_t = df_t_raw.copy()
    df_m = df_m_raw.copy()
    
    if f'Price_{curr_label}' in df_t.columns: df_t.rename(columns={f'Price_{curr_label}': 'Price'}, inplace=True)
    if f'KRW-{curr_label}_Amount' in df_m.columns: df_m.rename(columns={f'KRW-{curr_label}_Amount': 'KRW_Amount'}, inplace=True)
    if f'{curr_label}_Amount' in df_m.columns: df_m.rename(columns={f'{curr_label}_Amount': 'For_Amount'}, inplace=True)
    
    df_m['Source'] = 'Money'; df_t['Source'] = 'Trade'
    try:
        df_m['Date_Obj'] = pd.to_datetime(df_m['Date'].astype(str))
        df_t['Date_Obj'] = pd.to_datetime(df_t['Date'].astype(str))
    except: pass

    timeline = pd.concat([df_m, df_t], ignore_index=True)
    if 'Order_ID' not in timeline.columns: timeline['Order_ID'] = 0
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    timeline = timeline.sort_values(by=['Date_Obj', 'Order_ID'])
    
    balance = 0.0; avg_rate = 0.0
    krw_sum = 0.0
    port = {} 
    
    for _, row in timeline.iterrows():
        source = row['Source']
        t_type = str(row.get('Type', '')).lower()
        
        if source == 'Money':
            for_amt = safe_float(row.get('For_Amount'))
            krw_amt = safe_float(row.get('KRW_Amount'))
            ticker = str(row.get('Ticker', '')).strip()
            if ticker in ('', '-', 'nan'): ticker = 'Cash'
            
            if 'dividend' in t_type or '배당' in t_type:
                if ticker != 'Cash':
                    if ticker not in port: port[ticker] = {'qty':0, 'invested_krw':0, 'invested_for':0, 'realized_krw':0, 'accum_div_for':0, 'accum_div_krw':0, 'currency':curr_label, 'raw_ticker':ticker}
                    port[ticker]['accum_div_for'] += for_amt
            else:
                if balance <= 0:
                    if for_amt > 0: avg_rate = krw_amt / for_amt
                else:
                    if (balance + for_amt) > 0:
                        avg_rate = ((balance * avg_rate) + krw_amt) / (balance + for_amt)
                
                krw_sum += krw_amt
                
            balance += for_amt

        elif source == 'Trade':
            qty = safe_float(row.get('Qty'))
            price = safe_float(row.get('Price'))
            amount = qty * price
            ticker = str(row.get('Ticker', '')).strip()
            
            if ticker not in port: port[ticker] = {'qty':0, 'invested_krw':0, 'invested_for':0, 'realized_krw':0, 'accum_div_for':0, 'accum_div_krw':0, 'currency':curr_label, 'raw_ticker':ticker}
            
            if 'buy' in t_type or '매수' in t_type:
                balance -= amount
                ex_rate_db = safe_float(row.get('Ex_Avg_Rate'))
                rate_to_use = ex_rate_db if ex_rate_db > 0 else avg_rate
                
                port[ticker]['qty'] += qty
                port[ticker]['invested_krw'] += (amount * rate_to_use)
                port[ticker]['invested_for'] += amount 
                
            elif 'sell' in t_type or '매도' in t_type:
                balance += amount
                if port[ticker]['qty'] > 0:
                    unit_krw = port[ticker]['invested_krw'] / port[ticker]['qty']
                    unit_for = port[ticker]['invested_for'] / port[ticker]['qty']
                    port[ticker]['realized_krw'] += (amount * avg_rate) - (qty * unit_krw)
                    port[ticker]['qty'] -= qty
                    port[ticker]['invested_krw'] -= (qty * unit_krw)
                    port[ticker]['invested_for'] -= (qty * unit_for)

    return balance, avg_rate, krw_sum, port

def process_timeline(df_usd_trade, df_usd_money, df_jpy_trade, df_jpy_money, df_domestic):
    usd_bal, usd_rate, usd_krw_sum, usd_port = process_foreign_currency(df_usd_trade, df_usd_money, 'USD')
    jpy_bal, jpy_rate, jpy_krw_sum, jpy_port = process_foreign_currency(df_jpy_trade, df_jpy_money, 'JPY')
    
    portfolio = {**usd_port, **jpy_port}

    dom_cash = 0.0
    dom_principal_sum = 0.0
    for _, row in df_domestic.iterrows():
        t_type = str(row.get('Type', '')).lower()
        raw_ticker = str(row.get('Ticker', '')).strip()
        ticker = DOMESTIC_TICKER_MAP.get(raw_ticker, raw_ticker) 
        qty = safe_float(row.get('Qty'))
        amount_krw = safe_float(row.get('Amount_KRW'))
        
        if ticker not in portfolio and raw_ticker and raw_ticker != '-':
            portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_for':0, 'realized_krw':0, 'accum_div_for':0, 'accum_div_krw':0, 'currency':'KRW', 'raw_ticker':raw_ticker}
            
        if 'buy' in t_type or '매수' in t_type:
            portfolio[ticker]['qty'] += qty; portfolio[ticker]['invested_krw'] += amount_krw; dom_cash -= amount_krw
        elif 'sell' in t_type or '매도' in t_type:
            if portfolio[ticker]['qty'] > 0:
                unit_krw = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                portfolio[ticker]['realized_krw'] += amount_krw - (qty * unit_krw)
                portfolio[ticker]['qty'] -= qty; portfolio[ticker]['invested_krw'] -= (qty * unit_krw)
            dom_cash += amount_krw
        elif 'dividend' in t_type or '배당' in t_type:
            if ticker in portfolio: portfolio[ticker]['accum_div_krw'] += amount_krw
            dom_cash += amount_krw
        elif 'deposit' in t_type or '입금' in t_type:
            dom_cash += amount_krw; dom_principal_sum += amount_krw
        elif 'withdraw' in t_type or '출금' in t_type:
            dom_cash -= amount_krw; dom_principal_sum -= amount_krw

    return usd_bal, usd_rate, usd_krw_sum, jpy_bal, jpy_rate, jpy_krw_sum, dom_cash, dom_principal_sum, portfolio

# -------------------------------------------------------------------
# [5] 카톡 파서 (임시 JPY 감지 로직 추가)
# -------------------------------------------------------------------
def parse_kakaotalk_final(text, base_date):
    parsed_list = []
    base_year = base_date.year
    flat_text = text.replace('\n', ' ')
    chunks = re.split(r'(?=\[한국투자증권 체결안내\]|최원준님|외화매수환전|ETF 결산분배금)', flat_text)

    for chunk in chunks:
        if not chunk.strip(): continue
        try:
            # 국내
            dom_m = re.search(r'\[한국투자증권 체결안내\].*?(\d{2}:\d{2}).*?\*매매구분:현금(매수|매도)체결.*?\*종목명:.*?\(([\dA-Za-z]+)\).*?\*체결수량:([\d,]+).*?\*체결단가:([\d,]+)원', chunk)
            if dom_m:
                t_str, t_dir, t_tkr, t_qty, t_prc = dom_m.groups()
                t_dt = datetime.combine(base_date, datetime.min.time()).replace(hour=int(t_str.split(':')[0]), minute=int(t_str.split(':')[1]))
                parsed_list.append({ "Category": "Domestic_Trade", "Date": t_dt.strftime("%Y-%m-%d %H:%M:%S"), "Ticker": t_tkr, "Type": "Buy" if t_dir == "매수" else "Sell", "Qty": int(t_qty.replace(',','')), "Price": float(t_prc.replace(',','')), "Amount": 0, "Memo": f"카톡파싱_{t_str}" })
                continue
                
            # 일본 거래 (임시)
            jpy_tr_m = re.search(r'\[한국투자증권 체결안내\].*?(\d{2}:\d{2}).*?\*매매구분:(매수|매도).*?\*종목명:([A-Za-z0-9 .]+)(?:/|$).*?\*체결수량:([\d,]+).*?\*체결단가:JPY\s*([\d.]+)', chunk)
            if jpy_tr_m:
                t_str, t_dir, t_tkr, t_qty, t_prc = jpy_tr_m.groups()
                final_dt = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=1)).strftime("%Y-%m-%d 23:30:00")
                parsed_list.append({ "Category": "Japan_Trade", "Date": final_dt, "Ticker": t_tkr.strip(), "Type": "Buy" if t_dir == "매수" else "Sell", "Qty": int(t_qty.replace(',','')), "Price": float(t_prc.replace(',','')), "Amount": 0, "Memo": f"카톡파싱_{t_str}" })
                continue

            # 미국 거래
            usd_tr_m = re.search(r'\[한국투자증권 체결안내\].*?(\d{2}:\d{2}).*?\*매매구분:(매수|매도).*?\*종목명:([A-Za-z0-9 ]+)(?:/|$).*?\*체결수량:([\d,]+).*?\*체결단가:USD\s*([\d.]+)', chunk)
            if usd_tr_m:
                t_str, t_dir, t_tkr, t_qty, t_prc = usd_tr_m.groups()
                final_dt = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=1)).strftime("%Y-%m-%d 23:30:00")
                parsed_list.append({ "Category": "USD_Trade", "Date": final_dt, "Ticker": t_tkr.strip(), "Type": "Buy" if t_dir == "매수" else "Sell", "Qty": int(t_qty.replace(',','')), "Price": float(t_prc.replace(',','')), "Amount": 0, "Memo": f"카톡파싱_{t_str}" })
                continue

            # 일본 배당 (임시)
            jpy_div_m = re.search(r'최원준님\s*(\d{2}/\d{2}).*?([A-Z0-9.]+)/.*?JPY\s*([\d.]+)\s*세전배당입금', chunk)
            if jpy_div_m:
                d_str, t_tkr, t_amt = jpy_div_m.groups()
                m, d = map(int, d_str.split('/'))
                parsed_list.append({ "Category": "Japan_Dividend", "Date": datetime(base_year, m, d, 15, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Ticker": t_tkr.strip(), "Type": "Dividend", "Qty": 0, "Price": float(t_amt), "Amount": 0, "Memo": "카톡파싱_배당" })
                continue

            # 미국 배당
            usd_div_m = re.search(r'최원준님\s*(\d{2}/\d{2}).*?([A-Z]+)/.*?USD\s*([\d.]+)\s*세전배당입금', chunk)
            if usd_div_m:
                d_str, t_tkr, t_amt = usd_div_m.groups()
                m, d = map(int, d_str.split('/'))
                parsed_list.append({ "Category": "USD_Dividend", "Date": datetime(base_year, m, d, 15, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Ticker": t_tkr.strip(), "Type": "Dividend", "Qty": 0, "Price": float(t_amt), "Amount": 0, "Memo": "카톡파싱_배당" })
                continue

            # 국내 배당
            dom_div_m = re.search(r'ETF 결산분배금 입금 안내.*?\*\s*종목명\s*:\s*(.*?)\s*\*.*?\*\s*입금액\s*:\s*([\d,]+)원.*?\*\s*입금일자\s*:\s*(\d{4})년\s*(\d{2})월\s*(\d{2})일', chunk)
            if dom_div_m:
                t_name, t_amt, y, m, d = dom_div_m.groups()
                t_tkr = {'TIGER 미국배당다우존스': '458730'}.get(t_name.strip(), t_name.strip())
                parsed_list.append({ "Category": "Domestic_Dividend", "Date": datetime(int(y), int(m), int(d), 15, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Ticker": t_tkr, "Type": "Dividend", "Qty": 0, "Price": 0, "Amount": float(t_amt.replace(',', '')), "Memo": "카톡파싱_국내배당" })
                continue

            # 일본 환전 (임시)
            jpy_ex_m = re.search(r'외화매수환전.*?￦([0-9,]+).*?@([0-9,.]+).*?JPY\s*([0-9,.]+)', chunk)
            if jpy_ex_m:
                k_amt, ex_rt, u_amt = jpy_ex_m.groups()
                parsed_list.append({ "Category": "Japan_Exchange", "Date": datetime.combine(base_date, datetime.min.time()).replace(hour=14, minute=0).strftime("%Y-%m-%d %H:%M:%S"), "Ticker": "-", "Type": "KRW_to_JPY", "Qty": 0, "Price": float(u_amt.replace(',', '')), "Amount": float(k_amt.replace(',', '')), "Memo": "카톡파싱_환전" })
                continue

            # 미국 환전
            usd_ex_m = re.search(r'외화매수환전.*?￦([0-9,]+).*?@([0-9,.]+).*?USD\s*([0-9,.]+)', chunk)
            if usd_ex_m:
                k_amt, ex_rt, u_amt = usd_ex_m.groups()
                parsed_list.append({ "Category": "USD_Exchange", "Date": datetime.combine(base_date, datetime.min.time()).replace(hour=14, minute=0).strftime("%Y-%m-%d %H:%M:%S"), "Ticker": "-", "Type": "KRW_to_USD", "Qty": 0, "Price": float(u_amt.replace(',', '')), "Amount": float(k_amt.replace(',', '')), "Memo": "카톡파싱_환전" })
        except: continue
        
    return parsed_list

# -------------------------------------------------------------------
# [6] Main UI (3대 통합 KPI 큐브 + Optimistic UI)
# -------------------------------------------------------------------
def main():
    try:
        dfs = load_data()
        df_usd_trade, df_usd_money, df_jpy_trade, df_jpy_money, df_domestic = dfs
    except Exception as e:
        st.error(f"🚨 DB 로딩 실패: {e}"); st.stop()
        
    usd_bal, usd_rate, usd_krw_sum, jpy_bal, jpy_rate, jpy_krw_sum, dom_cash, dom_principal_sum, portfolio = process_timeline(*dfs)
    
    prices = st.session_state.get('price_cache', {})
    cur_usd_rate = st.session_state.get('fx_rate_usd', 0.0)
    cur_jpy_rate = st.session_state.get('fx_rate_jpy', 0.0)
    
    has_valid_prices = sum(prices.values()) > 0 if prices else False
    is_skeleton = not has_valid_prices
    
    total_principal_all = usd_krw_sum + jpy_krw_sum + dom_principal_sum
    total_stock_val_krw = 0.0
    usd_div_total_for = 0.0
    jpy_div_total_for = 0.0
    
    for tk, data in portfolio.items():
        if data['currency'] == 'USD': usd_div_total_for += data['accum_div_for']
        elif data['currency'] == 'JPY': jpy_div_total_for += data['accum_div_for']

        if data['qty'] > 0:
            cur_p = prices.get(tk, 0)
            if data['currency'] == 'KRW':
                total_stock_val_krw += data['qty'] * cur_p
            elif data['currency'] == 'USD':
                total_stock_val_krw += data['qty'] * cur_p * cur_usd_rate
            elif data['currency'] == 'JPY':
                total_stock_val_krw += data['qty'] * cur_p * cur_jpy_rate

    cash_val_krw = (usd_bal * cur_usd_rate) + (jpy_bal * cur_jpy_rate) + dom_cash
    total_asset_krw = total_stock_val_krw + cash_val_krw
    total_pl_krw = total_asset_krw - total_principal_all
    total_pl_pct = (total_pl_krw / total_principal_all * 100) if total_principal_all > 0 else 0
    
    # [수정됨] dict.values() -> dict.items() 로 언패킹 에러 완벽 해결
    # USD 큐브 마진 계산
    usd_bep_num = usd_krw_sum - sum(d['realized_krw'] for d in portfolio.values() if d['currency'] == 'USD') - (usd_div_total_for * cur_usd_rate)
    usd_assets = sum(d['qty'] * prices.get(tk,0) for tk, d in portfolio.items() if d['currency'] == 'USD') + usd_bal
    usd_bep = (usd_bep_num / usd_assets) if usd_assets > 0 else 0.0
    usd_margin = cur_usd_rate - usd_bep

    # JPY 큐브 마진 계산
    jpy_bep_num = jpy_krw_sum - sum(d['realized_krw'] for d in portfolio.values() if d['currency'] == 'JPY') - (jpy_div_total_for * cur_jpy_rate)
    jpy_assets = sum(d['qty'] * prices.get(tk,0) for tk, d in portfolio.items() if d['currency'] == 'JPY') + jpy_bal
    jpy_bep = (jpy_bep_num / jpy_assets) if jpy_assets > 0 else 0.0
    jpy_margin = cur_jpy_rate - jpy_bep

    # 스켈레톤 마스킹
    if is_skeleton:
        top_asset_str = "로딩중..." if st.session_state.get('needs_fetch') else "시세 API 점검중"
        top_pl_str = "-"
        top_usd_margin_str = "-"
        top_usd_bep_str = "-"
        top_jpy_margin_str = "-"
        top_jpy_bep_str = "-"
        
        card_cls_main = "stock-card card-neutral"
        usd_card_cls = "stock-card card-neutral"
        jpy_card_cls = "stock-card card-neutral"
        txt_cls = "txt-sub"
        usd_txt_cls = "txt-sub"
        jpy_txt_cls = "txt-sub"
    else:
        top_asset_str = f"₩ {total_asset_krw:,.0f}"
        is_plus = total_pl_krw >= 0
        top_pl_str = f"{'▲' if is_plus else '▼'} {abs(total_pl_krw):,.0f} ({total_pl_pct:+.2f}%)"
        
        top_usd_margin_str = f"{'+' if usd_margin >= 0 else ''}{usd_margin:,.2f} 원"
        top_usd_bep_str = f"₩ {usd_bep:,.2f}"
        top_jpy_margin_str = f"{'+' if jpy_margin >= 0 else ''}{jpy_margin:,.2f} 원"
        top_jpy_bep_str = f"₩ {jpy_bep:,.2f}"

        card_cls_main = f"stock-card {'card-up' if is_plus else 'card-down'}"
        usd_card_cls = f"stock-card {'card-up' if usd_margin >= 0 else 'card-down'}"
        jpy_card_cls = f"stock-card {'card-up' if jpy_margin >= 0 else 'card-down'}"
        
        txt_cls = "txt-red" if is_plus else "txt-blue"
        usd_txt_cls = "txt-red" if usd_margin >= 0 else "txt-blue"
        jpy_txt_cls = "txt-red" if jpy_margin >= 0 else "txt-blue"

    c1, c2 = st.columns([3, 1])
    with c1: st.title("🚀 Investment Command Center")
    with c2:
        if st.button("🔄 시세 새로고침", use_container_width=True):
            st.session_state['needs_fetch'] = True
            st.rerun()

    # --- 3대 KPI 큐브 통합 ---
    kpi_cols = st.columns(3)
    with kpi_cols[0]:
        st.markdown(f"""
        <div class="{card_cls_main}">
            <div class="card-header"><span class="card-ticker">총 자산</span><span class="card-price">Total Assets</span></div>
            <div class="card-main-val">{top_asset_str}</div>
            <div class="card-sub-box {txt_cls}">{top_pl_str}</div>
        </div>
        """, unsafe_allow_html=True)
    with kpi_cols[1]:
        st.markdown(f"""
        <div class="{usd_card_cls}">
            <div class="card-header"><span class="card-ticker">달러 잔고</span><span class="card-price">USD Command</span></div>
            <div class="card-main-val">$ {usd_bal:,.2f}</div>
            <div class="card-sub-box">
                <span style="color:#888; font-weight:400;">매수평단 ₩ {usd_rate:,.2f}</span><br>
                <span style="color:#888; font-weight:400;">BEP {top_usd_bep_str}</span><br>
                <span class="{usd_txt_cls}">마진 {top_usd_margin_str}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with kpi_cols[2]:
        st.markdown(f"""
        <div class="{jpy_card_cls}">
            <div class="card-header"><span class="card-ticker">엔화 잔고</span><span class="card-price">JPY Command</span></div>
            <div class="card-main-val">¥ {jpy_bal:,.0f}</div>
            <div class="card-sub-box">
                <span style="color:#888; font-weight:400;">매수평단 ₩ {jpy_rate:,.2f}</span><br>
                <span style="color:#888; font-weight:400;">BEP {top_jpy_bep_str}</span><br>
                <span class="{jpy_txt_cls}">마진 {top_jpy_margin_str}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    tab_dash, tab_input, tab_detail, tab_log = st.tabs(["📊 대시보드", "🕹️ 입력 매니저", "📋 통합 상세", "📜 통합 로그"])
    
    with tab_dash:
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
                        margin_tk_str = f"{margin_tk:+.1f} 원"
                        price_display = f"${cur_p:.2f}" if data['currency'] == 'USD' else f"¥ {cur_p:,.0f}"

                    total_ret = (total_pl_tk / invested_krw * 100) if invested_krw > 0 else 0
                    is_p = total_pl_tk >= 0
                    val_krw_str = f"₩ {val_krw:,.0f}"
                    pl_str = f"{'▲' if is_p else '▼'} {abs(total_pl_tk):,.0f} ({'+' if is_p else ''}{total_ret:.1f}%)"
                    card_cls_tk = f"stock-card {'card-up' if is_p else 'card-down'}"
                    txt_cls_tk = "txt-red" if is_p else "txt-blue"

                html = f"""
                <div class="{card_cls_tk}">
                    <div class="card-header"><span class="card-ticker">{tk}</span><span class="card-price">{price_display}</span></div>
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

    with tab_input:
        st.info("💡 팁: 여러 개의 카톡 메시지를 한 번에 쏟아부어도 인공지능이 엔터 없이 전부 분리해 저장합니다.")
        c1, c2 = st.columns([1, 2])
        with c1: ref_date = st.date_input("기준 날짜 (카톡 수신일)", datetime.now())
        with c2: raw_text = st.text_area("카톡 내용 붙여넣기", height=150, placeholder="[한국투자증권 체결안내]08:05...")
        
        if st.button("🚀 대기열 전체 분석 및 DB 저장", type="primary", use_container_width=True):
            if raw_text:
                parsed_items = parse_kakaotalk_final(raw_text, ref_date)
                if parsed_items:
                    client = get_gsheet_client()
                    sheet_instance = client.open("Investment_Dashboard_DB")
                    ws_usd_trade = sheet_instance.worksheet("USD_Trade_Log")
                    ws_usd_money = sheet_instance.worksheet("USD_Money_Log")
                    ws_jpy_trade = sheet_instance.worksheet("JPY_Trade_Log")
                    ws_jpy_money = sheet_instance.worksheet("JPY_Money_Log")
                    ws_dom = sheet_instance.worksheet("Domestic_Log")
                    
                    max_id = max(pd.to_numeric(df_usd_trade['Order_ID']).max(), pd.to_numeric(df_usd_money['Order_ID']).max(), pd.to_numeric(df_jpy_trade['Order_ID']).max(), pd.to_numeric(df_jpy_money['Order_ID']).max())
                    next_id = int(max_id) + 1 if not pd.isna(max_id) else 1
                    
                    for item in parsed_items:
                        if item["Category"] == "USD_Trade":
                            ws_usd_trade.append_row([ item["Date"], int(next_id), str(item["Ticker"]), str(item["Ticker"]), str(item["Type"]), int(item["Qty"]), float(item["Price"]), "", item["Memo"] ])
                            next_id += 1
                        elif item["Category"] == "USD_Dividend":
                            ws_usd_money.append_row([ item["Date"], int(next_id), "Dividend", str(item["Ticker"]), 0, float(item["Price"]), 0, "", "", item["Memo"] ])
                            next_id += 1
                        elif item["Category"] == "USD_Exchange":
                            ws_usd_money.append_row([ item["Date"], int(next_id), "KRW_to_USD", "-", float(item["Amount"]), float(item["Price"]), float(item["Amount"]/item["Price"] if item["Price"]>0 else 0), "", "", item["Memo"] ])
                            next_id += 1
                        elif item["Category"] == "Japan_Trade":
                            ws_jpy_trade.append_row([ item["Date"], int(next_id), str(item["Ticker"]), str(item["Ticker"]), str(item["Type"]), int(item["Qty"]), float(item["Price"]), "", item["Memo"] ])
                            next_id += 1
                        elif item["Category"] == "Japan_Dividend":
                            ws_jpy_money.append_row([ item["Date"], int(next_id), "Dividend", str(item["Ticker"]), 0, float(item["Price"]), 0, "", "", item["Memo"] ])
                            next_id += 1
                        elif item["Category"] == "Japan_Exchange":
                            ws_jpy_money.append_row([ item["Date"], int(next_id), "KRW_to_JPY", "-", float(item["Amount"]), float(item["Price"]), float(item["Amount"]/item["Price"] if item["Price"]>0 else 0), "", "", item["Memo"] ])
                            next_id += 1
                        elif item["Category"] == "Domestic_Trade":
                            ws_dom.append_row([ item["Date"], str(item["Type"]), str(item["Ticker"]), "-", int(item["Qty"]), float(item["Price"]), float(item["Qty"]*item["Price"]), item["Memo"] ])
                        elif item["Category"] == "Domestic_Dividend":
                            ws_dom.append_row([ item["Date"], "Dividend", str(item["Ticker"]), "-", 0, 0, float(item["Amount"]), item["Memo"] ])
                        
                    st.success(f"✅ {len(parsed_items)}건 DB 저장 완료! 시세를 재동기화합니다.")
                    st.cache_data.clear() 
                    st.session_state['needs_fetch'] = True 
                    time.sleep(1.5); st.rerun()
                else:
                    st.warning("⚠️ 저장할 내역을 찾지 못했습니다.")

    with tab_detail:
        header = "<table class='int-table'><thead><tr><th>종목</th><th>평가액 (₩)</th><th>평가손익</th><th>환손익</th><th>실현+배당</th><th>총 손익 (Total)</th><th>안전마진</th></tr></thead><tbody>"
        rows_html = ""; sum_eval_krw = 0; sum_realized = 0
        sorted_tickers = sorted(list(portfolio.keys()), key=lambda x: SORT_ORDER_TABLE.index(x) if x in SORT_ORDER_TABLE else 999)
        
        for tk in sorted_tickers:
            if tk == 'Cash': continue
            data = portfolio[tk]; qty = data['qty']; cur_p = prices.get(tk, 0)
            if qty == 0 and data['realized_krw'] == 0 and data['accum_div_for'] == 0 and data['accum_div_krw'] == 0: continue

            if is_skeleton:
                rows_html += f"<tr><td>{tk}</td><td>-</td><td>-</td><td>-</td><td>{data['realized_krw'] + (data['accum_div_krw'] if data['currency']=='KRW' else 0):,.0f}</td><td>-</td><td style='color:#ccc;'>-</td></tr>"
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
                margin_str = f"{fx - bep_tk:+.1f}" if qty > 0 else "-"

            sum_eval_krw += eval_krw; sum_realized += (data['realized_krw'] + div_krw)
            cls_tot = "txt-red" if total_pl >= 0 else "txt-blue"
            rows_html += f"<tr><td>{tk}</td><td>{eval_krw:,.0f}</td><td class='{'txt-red' if price_profit >=0 else 'txt-blue'}'>{price_profit:,.0f}</td><td class='{'txt-sub' if data['currency']=='KRW' else ('txt-red' if float(fx_profit_str.replace(',',''))>=0 else 'txt-blue') if fx_profit_str!='-' else 'txt-sub'}'>{fx_profit_str}</td><td>{data['realized_krw'] + div_krw:,.0f}</td><td class='{cls_tot} {'bg-red' if total_pl>=0 else 'bg-blue'}'><b>{total_pl:,.0f}</b></td><td style='color:#ccc;'>{margin_str}</td></tr>"
            
        if is_skeleton:
            total_row = f"<tr class='row-total'><td>TOTAL</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
        else:
            final_pl_calc = (sum_eval_krw + cash_val_krw + dom_cash) - total_principal_all
            total_row = f"<tr class='row-total'><td>TOTAL</td><td>{(sum_eval_krw + cash_val_krw + dom_cash):,.0f}</td><td>-</td><td>-</td><td>{sum_realized:,.0f}</td><td class='{'txt-red' if final_pl_calc>=0 else 'txt-blue'}'>{final_pl_calc:,.0f}</td><td>-</td></tr>"
        st.markdown(header + rows_html + total_row + "</tbody></table>", unsafe_allow_html=True)

    with tab_log:
        st.caption("🇺🇸 달러 자산 로그 (Trade / Money)")
        st.dataframe(df_usd_trade.fillna(''), use_container_width=True)
        st.dataframe(df_usd_money.fillna(''), use_container_width=True)
        st.caption("🇯🇵 엔화 자산 로그 (Trade / Money)")
        st.dataframe(df_jpy_trade.fillna(''), use_container_width=True)
        st.dataframe(df_jpy_money.fillna(''), use_container_width=True)
        st.caption("🇰🇷 국내 자산 로그")
        st.dataframe(df_domestic.fillna(''), use_container_width=True)

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
            
            if p <= 0 and tk in old_prices and old_prices[tk] > 0:
                p = old_prices[tk]
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
