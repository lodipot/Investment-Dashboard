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
# [1] 설정 & 다크모드 (모바일 반응형 탭 포함)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="🏦")

if 'price_cache' not in st.session_state: st.session_state['price_cache'] = {}
if 'needs_fetch' not in st.session_state: st.session_state['needs_fetch'] = True # 최초 접속 시 페칭 활성화

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
    .stock-card {{ background-color: {THEME_CARD}; border-radius: 16px; padding: 20px; margin-bottom: 16px; border: 1px solid {THEME_BORDER}; border-left: 6px solid #555; }}
    .card-up {{ border-left-color: {COLOR_RED} !important; }}
    .card-down {{ border-left-color: {COLOR_BLUE} !important; }}
    .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
    .card-ticker {{ font-size: 1.4rem; font-weight: 900; color: {THEME_TEXT}; }}
    .card-price {{ font-size: 1.1rem; font-weight: 500; color: {THEME_SUB}; }}
    .card-main-val {{ font-size: 1.6rem; font-weight: 800; color: {THEME_TEXT}; text-align: right; margin-bottom: 4px; }}
    .card-sub-box {{ text-align: right; font-size: 1.0rem; font-weight: 600; }}
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
# [2] 맵핑
# -------------------------------------------------------------------
SECTOR_ORDER_LIST = { '배당': ['O', 'JEPI', 'JEPQ', 'SCHD', 'MAIN', 'KO', 'SCHD(ISA)'], '테크': ['GOOGL', 'NVDA', 'AMD', 'TSM', 'MSFT', 'AAPL', 'AMZN', 'TSLA', 'AVGO', 'SOXL'], '리츠': ['PLD', 'AMT'], '기타': [] }
SORT_ORDER_TABLE = ['O', 'JEPI', 'JEPQ', 'GOOGL', 'NVDA', 'AMD', 'TSM', 'SCHD(ISA)']
DOMESTIC_TICKER_MAP = { '458730': 'SCHD(ISA)' }

# -------------------------------------------------------------------
# [3] 로드 (캐싱으로 과부하 방지)
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

    df_trade = get_safe_df("Trade_Log", ['Date', 'Order_ID', 'Ticker', 'Name', 'Type', 'Qty', 'Price_USD', 'Ex_Avg_Rate', 'Note'])
    df_money = get_safe_df("Money_Log", ['Date', 'Order_ID', 'Type', 'Ticker', 'KRW_Amount', 'USD_Amount', 'Ex_Rate', 'Avg_Rate', 'Balance', 'Note'])
    df_domestic = get_safe_df("Domestic_Log", ['Date', 'Type', 'Ticker', 'Name', 'Qty', 'Price_KRW', 'Amount_KRW', 'Note'])

    return df_trade, df_money, df_domestic

# -------------------------------------------------------------------
# [4] 계산 엔진 (마이너스 BEP 수학적 허용 / 배당 평단가 격리)
# -------------------------------------------------------------------
def process_timeline(df_trade, df_money, df_domestic):
    df_money['Source'] = 'Money'; df_trade['Source'] = 'Trade'
    try:
        df_money['Date_Obj'] = pd.to_datetime(df_money['Date'].astype(str))
        df_trade['Date_Obj'] = pd.to_datetime(df_trade['Date'].astype(str))
    except: pass

    timeline = pd.concat([df_money, df_trade], ignore_index=True)
    if 'Order_ID' not in timeline.columns: timeline['Order_ID'] = 0
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    timeline = timeline.sort_values(by=['Date_Obj', 'Order_ID'])
    
    current_balance = 0.0; current_avg_rate = 0.0
    pure_exch_krw_sum = 0.0; pure_exch_usd_sum = 0.0
    portfolio = {} 
    
    for _, row in timeline.iterrows():
        source = row['Source']
        t_type = str(row.get('Type', '')).lower()
        
        if source == 'Money':
            usd_amt = safe_float(row.get('USD_Amount'))
            krw_amt = safe_float(row.get('KRW_Amount'))
            ticker = str(row.get('Ticker', '')).strip()
            if ticker in ('', '-', 'nan'): ticker = 'Cash'
            
            if 'dividend' in t_type or '배당' in t_type:
                if ticker != 'Cash':
                    if ticker not in portfolio: portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_usd':0, 'realized_krw':0, 'accum_div_usd':0, 'accum_div_krw':0, 'is_domestic':False, 'raw_ticker':ticker}
                    portfolio[ticker]['accum_div_usd'] += usd_amt
                # [수정] 배당은 공짜 달러이므로 평단가(current_avg_rate)를 건드리지 않고 잔고만 늘림
            else:
                if current_balance <= 0:
                    if usd_amt > 0: current_avg_rate = krw_amt / usd_amt
                else:
                    if (current_balance + usd_amt) > 0:
                        current_avg_rate = ((current_balance * current_avg_rate) + krw_amt) / (current_balance + usd_amt)
                
                pure_exch_krw_sum += krw_amt
                pure_exch_usd_sum += usd_amt
                
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

    domestic_cash = 0.0
    dom_principal_sum = 0.0
    for _, row in df_domestic.iterrows():
        t_type = str(row.get('Type', '')).lower()
        raw_ticker = str(row.get('Ticker', '')).strip()
        ticker = DOMESTIC_TICKER_MAP.get(raw_ticker, raw_ticker) 
        qty = safe_float(row.get('Qty'))
        amount_krw = safe_float(row.get('Amount_KRW'))
        
        if ticker not in portfolio and raw_ticker and raw_ticker != '-':
            portfolio[ticker] = {'qty':0, 'invested_krw':0, 'invested_usd':0, 'realized_krw':0, 'accum_div_usd':0, 'accum_div_krw':0, 'is_domestic':True, 'raw_ticker':raw_ticker}
            
        if 'buy' in t_type or '매수' in t_type:
            portfolio[ticker]['qty'] += qty; portfolio[ticker]['invested_krw'] += amount_krw; domestic_cash -= amount_krw
        elif 'sell' in t_type or '매도' in t_type:
            if portfolio[ticker]['qty'] > 0:
                unit_krw = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                portfolio[ticker]['realized_krw'] += amount_krw - (qty * unit_krw)
                portfolio[ticker]['qty'] -= qty; portfolio[ticker]['invested_krw'] -= (qty * unit_krw)
            domestic_cash += amount_krw
        elif 'dividend' in t_type or '배당' in t_type:
            if ticker in portfolio: portfolio[ticker]['accum_div_krw'] += amount_krw
            domestic_cash += amount_krw
        elif 'deposit' in t_type or '입금' in t_type:
            domestic_cash += amount_krw; dom_principal_sum += amount_krw
        elif 'withdraw' in t_type or '출금' in t_type:
            domestic_cash -= amount_krw; dom_principal_sum -= amount_krw

    pure_exch_rate = pure_exch_krw_sum / pure_exch_usd_sum if pure_exch_usd_sum > 0 else 0
    return current_balance, domestic_cash, current_avg_rate, pure_exch_rate, portfolio, pure_exch_krw_sum, dom_principal_sum

# -------------------------------------------------------------------
# [5] 텍스트 덩어리 파서 (컬럼 정확도 매칭)
# -------------------------------------------------------------------
def parse_kakaotalk_final(text, base_date):
    parsed_list = []
    base_year = base_date.year
    flat_text = text.replace('\n', ' ')
    chunks = re.split(r'(?=\[한국투자증권 체결안내\]|최원준님|외화매수환전|ETF 결산분배금)', flat_text)

    for chunk in chunks:
        if not chunk.strip(): continue
        try:
            dom_m = re.search(r'\[한국투자증권 체결안내\].*?(\d{2}:\d{2}).*?\*매매구분:현금(매수|매도)체결.*?\*종목명:.*?\(([\dA-Za-z]+)\).*?\*체결수량:([\d,]+).*?\*체결단가:([\d,]+)원', chunk)
            if dom_m:
                t_str, t_dir, t_tkr, t_qty, t_prc = dom_m.groups()
                t_dt = datetime.combine(base_date, datetime.min.time()).replace(hour=int(t_str.split(':')[0]), minute=int(t_str.split(':')[1]))
                parsed_list.append({ "Category": "Domestic_Trade", "Date": t_dt.strftime("%Y-%m-%d %H:%M:%S"), "Ticker": t_tkr, "Type": "Buy" if t_dir == "매수" else "Sell", "Qty": int(t_qty.replace(',','')), "Price": float(t_prc.replace(',','')), "Amount": 0, "Memo": f"카톡파싱_{t_str}" })
                continue
                
            tr_m = re.search(r'\[한국투자증권 체결안내\].*?(\d{2}:\d{2}).*?\*매매구분:(매수|매도).*?\*종목명:([A-Za-z0-9 ]+)(?:/|$).*?\*체결수량:([\d,]+).*?\*체결단가:USD\s*([\d.]+)', chunk)
            if tr_m:
                t_str, t_dir, t_tkr, t_qty, t_prc = tr_m.groups()
                final_dt = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=1)).strftime("%Y-%m-%d 23:30:00")
                parsed_list.append({ "Category": "Trade", "Date": final_dt, "Ticker": t_tkr.strip(), "Type": "Buy" if t_dir == "매수" else "Sell", "Qty": int(t_qty.replace(',','')), "Price": float(t_prc.replace(',','')), "Amount": 0, "Memo": f"카톡파싱_{t_str}" })
                continue

            div_m = re.search(r'최원준님\s*(\d{2}/\d{2}).*?([A-Z]+)/.*?USD\s*([\d.]+)\s*세전배당입금', chunk)
            if div_m:
                d_str, t_tkr, t_amt = div_m.groups()
                m, d = map(int, d_str.split('/'))
                parsed_list.append({ "Category": "Dividend", "Date": datetime(base_year, m, d, 15, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Ticker": t_tkr.strip(), "Type": "Dividend", "Qty": 0, "Price": float(t_amt), "Amount": 0, "Memo": "카톡파싱_배당" })
                continue

            dom_div_m = re.search(r'ETF 결산분배금 입금 안내.*?\*\s*종목명\s*:\s*(.*?)\s*\*.*?\*\s*입금액\s*:\s*([\d,]+)원.*?\*\s*입금일자\s*:\s*(\d{4})년\s*(\d{2})월\s*(\d{2})일', chunk)
            if dom_div_m:
                t_name, t_amt, y, m, d = dom_div_m.groups()
                t_tkr = {'TIGER 미국배당다우존스': '458730'}.get(t_name.strip(), t_name.strip())
                parsed_list.append({ "Category": "Domestic_Dividend", "Date": datetime(int(y), int(m), int(d), 15, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Ticker": t_tkr, "Type": "Dividend", "Qty": 0, "Price": 0, "Amount": float(t_amt.replace(',', '')), "Memo": "카톡파싱_국내배당" })
                continue

            ex_m = re.search(r'외화매수환전.*?￦([0-9,]+).*?@([0-9,.]+).*?USD\s*([0-9,.]+)', chunk)
            if ex_m:
                k_amt, ex_rt, u_amt = ex_m.groups()
                parsed_list.append({ "Category": "Exchange", "Date": datetime.combine(base_date, datetime.min.time()).replace(hour=14, minute=0).strftime("%Y-%m-%d %H:%M:%S"), "Ticker": "-", "Type": "KRW_to_USD", "Qty": 0, "Price": float(u_amt.replace(',', '')), "Amount": float(k_amt.replace(',', '')), "Memo": "카톡파싱_환전" })
        except: continue
        
    return parsed_list

# -------------------------------------------------------------------
# [6] Main UI (Optimistic UI 렌더링)
# -------------------------------------------------------------------
def main():
    try:
        df_trade, df_money, df_domestic = load_data()
    except Exception as e:
        st.error(f"🚨 DB 로딩 실패: {e}"); st.stop()
        
    cur_bal, dom_cash, cur_rate, pure_exch_rate, portfolio, total_input_principal, total_dom_principal = process_timeline(df_trade, df_money, df_domestic)
    
    # [수정] 옵티미스틱 UI 뼈대 로직
    is_skeleton = len(st.session_state['price_cache']) == 0
    prices = st.session_state.get('price_cache', {})
    cur_real_rate = st.session_state.get('fx_rate', 0.0)
    
    total_principal_all = total_input_principal + total_dom_principal
    total_stock_val_krw = 0.0
    total_realized_krw = sum(d['realized_krw'] for d in portfolio.values())
    total_div_usd = sum(d['accum_div_usd'] for d in portfolio.values())
    total_div_krw = (total_div_usd * cur_real_rate) + sum(d['accum_div_krw'] for d in portfolio.values())
    total_price_profit = 0; total_fx_profit = 0
    
    for tk, data in portfolio.items():
        if data['qty'] > 0:
            cur_p = prices.get(tk, 0)
            if data['is_domestic']:
                val_krw = data['qty'] * cur_p
                total_stock_val_krw += val_krw
                total_price_profit += (val_krw - data['invested_krw'])
            else:
                val_usd = data['qty'] * cur_p; val_krw = val_usd * cur_real_rate
                invested_krw = data['invested_krw']; invested_usd = data['invested_usd']
                avg_rate_tk = invested_krw / invested_usd if invested_usd > 0 else 0
                total_stock_val_krw += val_krw
                total_price_profit += (val_usd - invested_usd) * cur_real_rate
                total_fx_profit += invested_usd * (cur_real_rate - avg_rate_tk)

    cash_val_krw = cur_bal * cur_real_rate
    total_fx_profit += (cash_val_krw - (cur_bal * cur_rate))
    total_asset_krw = total_stock_val_krw + cash_val_krw + dom_cash
    total_pl_krw = total_asset_krw - total_principal_all
    total_pl_pct = (total_pl_krw / total_principal_all * 100) if total_principal_all > 0 else 0
    
    bep_numerator = total_input_principal - sum(d['realized_krw'] for d in portfolio.values() if not d['is_domestic']) - (total_div_usd * cur_real_rate)
    total_usd_assets = sum(d['qty'] * prices.get(tk,0) for tk, d in portfolio.items() if not d['is_domestic']) + cur_bal
    bep_rate = (bep_numerator / total_usd_assets) if total_usd_assets > 0 else 0.0
    safety_margin = cur_real_rate - bep_rate

    # 스켈레톤(최초 로딩) 상태일 때 시각적 왜곡 방지용 마스킹
    if is_skeleton:
        top_asset_str = "로딩중..."
        top_pl_str = "-"
        top_margin_str = "로딩중..."
        top_bep_str = "-"
    else:
        top_asset_str = f"₩ {total_asset_krw:,.0f}"
        is_plus = total_pl_krw >= 0
        top_pl_str = f"{'▲' if is_plus else '▼'} {abs(total_pl_krw):,.0f} ({total_pl_pct:+.2f}%)"
        top_margin_str = f"{'+' if safety_margin >= 0 else ''}{safety_margin:,.2f} 원"
        top_bep_str = f"₩ {bep_rate:,.2f}"

    c1, c2 = st.columns([3, 1])
    with c1: st.title("🚀 Investment Command Center")
    with c2:
        if st.button("🔄 시세 새로고침", use_container_width=True):
            # [수정] 캐시를 지우지 않고 페치 신호만 보냄 (기존 유효 정보 유지)
            st.session_state['needs_fetch'] = True
            st.rerun()

    kpi_cols = st.columns(3)
    with kpi_cols[0]:
        st.markdown(f"""
        <div class="stock-card {'card-up' if (not is_skeleton and total_pl_krw >= 0) else 'card-down'}">
            <div class="card-header"><span class="card-ticker">총 자산</span><span class="card-price">Total Assets</span></div>
            <div class="card-main-val">{top_asset_str}</div>
            <div class="card-sub-box {'txt-red' if (not is_skeleton and total_pl_krw >= 0) else 'txt-blue' if not is_skeleton else 'txt-sub'}">{top_pl_str}</div>
        </div>
        """, unsafe_allow_html=True)
    with kpi_cols[1]:
        st.markdown(f"""
        <div class="stock-card">
            <div class="card-header"><span class="card-ticker">달러 잔고</span><span class="card-price">USD Balance</span></div>
            <div class="card-main-val">$ {cur_bal:,.2f}</div>
            <div class="card-sub-box"><span style="color:#888;">매수평단 ₩ {cur_rate:,.2f}</span></div>
        </div>
        """, unsafe_allow_html=True)
    with kpi_cols[2]:
        st.markdown(f"""
        <div class="stock-card {'card-up' if (not is_skeleton and safety_margin >= 0) else 'card-down'}">
            <div class="card-header"><span class="card-ticker">안전마진</span><span class="card-price">Safety Margin</span></div>
            <div class="card-main-val {'txt-red' if (not is_skeleton and safety_margin >= 0) else 'txt-blue' if not is_skeleton else 'txt-sub'}">{top_margin_str}</div>
            <div class="card-sub-box"><span style="color:#888;">BEP {top_bep_str}</span></div>
        </div>
        """, unsafe_allow_html=True)

    tab_dash, tab_input, tab_detail, tab_log = st.tabs(["📊 대시보드", "🕹️ 입력 매니저", "📋 통합 상세", "📜 통합 로그"])
    
    with tab_dash:
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
                data = portfolio[tk]; qty = data['qty']; cur_p = prices.get(tk, 0)
                
                invested_krw = data['invested_krw']
                div_krw = data['accum_div_krw'] if data['is_domestic'] else data['accum_div_usd'] * cur_real_rate
                
                if is_skeleton:
                    price_display = "-"; val_krw_str = "-"; pl_str = "-"; margin_tk_str = "-"; is_p = True
                else:
                    if data['is_domestic']:
                        val_krw = qty * cur_p
                        total_pl_tk = val_krw - invested_krw + data['realized_krw'] + div_krw
                        margin_tk_str = "-"
                        price_display = f"₩ {cur_p:,.0f}"
                    else:
                        val_krw = qty * cur_p * cur_real_rate
                        total_pl_tk = val_krw - invested_krw + data['realized_krw'] + div_krw
                        bep_rate_tk = (invested_krw - data['realized_krw'] - div_krw) / (qty * cur_p) if (qty*cur_p) > 0 else 0
                        margin_tk = cur_real_rate - bep_rate_tk
                        margin_tk_str = f"{margin_tk:+.1f} 원"
                        price_display = f"${cur_p:.2f}"

                    total_ret = (total_pl_tk / invested_krw * 100) if invested_krw > 0 else 0
                    is_p = total_pl_tk >= 0
                    val_krw_str = f"₩ {val_krw:,.0f}"
                    pl_str = f"{'▲' if is_p else '▼'} {abs(total_pl_tk):,.0f} ({'+' if is_p else ''}{total_ret:.1f}%)"

                html = f"""
                <div class="stock-card {'card-up' if is_p else 'card-down'}">
                    <div class="card-header"><span class="card-ticker">{tk}</span><span class="card-price">{price_display}</span></div>
                    <div class="card-main-val">{val_krw_str}</div>
                    <div class="card-sub-box {'txt-red' if is_p else 'txt-blue' if not is_skeleton else 'txt-sub'}">{pl_str}</div>
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
                    ws_trade = sheet_instance.worksheet("Trade_Log")
                    ws_money = sheet_instance.worksheet("Money_Log")
                    ws_dom = sheet_instance.worksheet("Domestic_Log")
                    
                    max_id = max(pd.to_numeric(df_trade['Order_ID']).max(), pd.to_numeric(df_money['Order_ID']).max())
                    next_id = int(max_id) + 1 if not pd.isna(max_id) else 1
                    
                    for item in parsed_items:
                        # [버그 수정 2] 컬럼 순서 및 빈칸 패딩 완벽 일치 복원
                        if item["Category"] == "Trade":
                            ws_trade.append_row([ item["Date"], int(next_id), str(item["Ticker"]), str(item["Ticker"]), str(item["Type"]), int(item["Qty"]), float(item["Price"]), "", item["Memo"] ])
                            next_id += 1
                        elif item["Category"] == "Domestic_Trade":
                            ws_dom.append_row([ item["Date"], str(item["Type"]), str(item["Ticker"]), "-", int(item["Qty"]), float(item["Price"]), float(item["Qty"]*item["Price"]), item["Memo"] ])
                        elif item["Category"] == "Dividend":
                            ws_money.append_row([ item["Date"], int(next_id), "Dividend", str(item["Ticker"]), 0, float(item["Price"]), 0, "", "", item["Memo"] ])
                            next_id += 1
                        elif item["Category"] == "Domestic_Dividend":
                            ws_dom.append_row([ item["Date"], "Dividend", str(item["Ticker"]), "-", 0, 0, float(item["Amount"]), item["Memo"] ])
                        elif item["Category"] == "Exchange":
                            ws_money.append_row([ item["Date"], int(next_id), "KRW_to_USD", "-", float(item["Amount"]), float(item["Price"]), float(item["Amount"]/item["Price"] if item["Price"]>0 else 0), "", "", item["Memo"] ])
                            next_id += 1
                        
                    st.success(f"✅ {len(parsed_items)}건 DB 저장 완료! 시세를 재동기화합니다.")
                    st.cache_data.clear() 
                    st.session_state['needs_fetch'] = True # 저장 후 시세 업데이트 트리거
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
            if qty == 0 and data['realized_krw'] == 0 and data['accum_div_usd'] == 0 and data['accum_div_krw'] == 0: continue

            if is_skeleton:
                rows_html += f"<tr><td>{tk}</td><td>-</td><td>-</td><td>-</td><td>{data['realized_krw'] + (data['accum_div_krw'] if data['is_domestic'] else 0):,.0f}</td><td>-</td><td style='color:#ccc;'>-</td></tr>"
                continue

            if data['is_domestic']:
                eval_krw = qty * cur_p; div_krw = data['accum_div_krw']
                total_pl = eval_krw - data['invested_krw'] + data['realized_krw'] + div_krw
                price_profit = eval_krw - data['invested_krw'] if qty > 0 else 0
                fx_profit_str = "-"; margin_str = "-"
            else:
                eval_krw = qty * cur_p * cur_real_rate; div_krw = data['accum_div_usd'] * cur_real_rate
                total_pl = eval_krw - data['invested_krw'] + data['realized_krw'] + div_krw
                if qty > 0:
                    my_avg_rate_tk = data['invested_krw'] / data['invested_usd'] if data['invested_usd'] > 0 else 0
                    fx_profit_str = f"{data['invested_usd'] * (cur_real_rate - my_avg_rate_tk):,.0f}"
                    price_profit = (qty * cur_p - data['invested_usd']) * cur_real_rate
                else: price_profit = 0; fx_profit_str = "-"
                
                bep_tk = (data['invested_krw'] - (data['realized_krw'] + div_krw)) / (qty * cur_p) if (qty*cur_p) > 0 else 0.0
                margin_str = f"{cur_real_rate - bep_tk:+.1f}" if qty > 0 else "-"

            sum_eval_krw += eval_krw; sum_realized += (data['realized_krw'] + div_krw)
            cls_tot = "txt-red" if total_pl >= 0 else "txt-blue"
            rows_html += f"<tr><td>{tk}</td><td>{eval_krw:,.0f}</td><td class='{'txt-red' if price_profit >=0 else 'txt-blue'}'>{price_profit:,.0f}</td><td class='{'txt-sub' if data['is_domestic'] else ('txt-red' if float(fx_profit_str.replace(',',''))>=0 else 'txt-blue') if fx_profit_str!='-' else 'txt-sub'}'>{fx_profit_str}</td><td>{data['realized_krw'] + div_krw:,.0f}</td><td class='{cls_tot} {'bg-red' if total_pl>=0 else 'bg-blue'}'><b>{total_pl:,.0f}</b></td><td style='color:#ccc;'>{margin_str}</td></tr>"
            
        if is_skeleton:
            total_row = f"<tr class='row-total'><td>TOTAL</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
        else:
            final_pl_calc = (sum_eval_krw + cash_val_krw + dom_cash) - total_principal_all
            total_row = f"<tr class='row-total'><td>TOTAL</td><td>{(sum_eval_krw + cash_val_krw + dom_cash):,.0f}</td><td>-</td><td>-</td><td>{sum_realized:,.0f}</td><td class='{'txt-red' if final_pl_calc>=0 else 'txt-blue'}'>{final_pl_calc:,.0f}</td><td>{safety_margin:+.1f}</td></tr>"
        st.markdown(header + rows_html + total_row + "</tbody></table>", unsafe_allow_html=True)

    with tab_log:
        st.dataframe(df_trade.fillna(''), use_container_width=True)
        st.dataframe(df_money.fillna(''), use_container_width=True)
        st.dataframe(df_domestic.fillna(''), use_container_width=True)

    # Phase 3: 백그라운드 페칭 (UI가 다 그려진 후 조용히 실행)
    if st.session_state.get('needs_fetch', False):
        st.toast("📡 최신 시세를 동기화합니다...", icon="🔄")
        new_prices = {}
        for tk, data in portfolio.items():
            if data['is_domestic']:
                try: new_prices[tk] = yf.Ticker(f"{data['raw_ticker']}.KS").history(period="1d")['Close'].iloc[-1]
                except: new_prices[tk] = 0
            else: new_prices[tk] = kis.get_current_price(tk)
        
        try:
            fx_data = yf.Ticker("KRW=X").history(period="1d")
            st.session_state['fx_rate'] = fx_data['Close'].iloc[-1] if not fx_data.empty else 1450.0
        except: st.session_state['fx_rate'] = 1450.0
        
        st.session_state['price_cache'] = new_prices
        st.session_state['needs_fetch'] = False # 무한루프 방지
        st.rerun() # 데이터를 다 가져왔으니 화면을 Seamless하게 업데이트!

if __name__ == "__main__":
    main()
