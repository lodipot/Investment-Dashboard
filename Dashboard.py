import streamlit as st
import pandas as pd
import hashlib
import re
import time
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# KIS API 매니저 임포트 (동일 폴더 내 KIS_API_Manager.py 필요)
try:
    from KIS_API_Manager import KIS_API_Manager
except ImportError:
    st.error("KIS_API_Manager.py 파일을 동일한 폴더에 위치시켜주세요.")

# ==========================================
# 0. 전역 설정 및 CSS
# ==========================================
st.set_page_config(page_title="Global Multi-Currency Reservoir", layout="wide", page_icon="🌊")

TARGET_CURRENCIES = ['KRW', 'USD', 'JPY', 'HKD']
EVENT_PRIORITY = {'Dividend': 1, 'Deposit': 2, 'Withdraw': 2, 'FX': 3, 'Trade': 4}

# 절대 불변의 원본 DB 스키마 (13개 기둥)
RAW_DB_COLUMNS = ['Date', 'PK_HASH', 'Source', 'Currency', 'Category', 'Type', 'Ticker', 'Name', 'Qty', 'Price', 'Amount_Local', 'Amount_KRW', 'Note']

THEME_CARD = "#18181A"
THEME_BORDER = "#444746"
COLOR_RED = "#FF5252"
COLOR_BLUE = "#448AFF"

st.markdown(f"""
    <style>
    .stException {{ display: none; }}
    .item-card {{ background:{THEME_CARD}; padding:15px; border-radius:8px; height: 165px; margin-bottom: 15px; }}
    .cube-card {{ background:{THEME_CARD}; padding:20px; border-radius:10px; border:1px solid {THEME_BORDER}; text-align:center; }}
    /* 탭 디자인 커스텀 */
    .stTabs [data-baseweb="tab-list"] {{ gap: 24px; }}
    .stTabs [data-baseweb="tab"] {{ height: 50px; white-space: pre-wrap; background-color: transparent; border-radius: 4px 4px 0px 0px; gap: 1px; padding-top: 10px; padding-bottom: 10px; }}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 데이터베이스 I/O (Google Sheets) & 코어 엔진
# ==========================================
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def load_ledger():
    """구글 스프레드시트에서 데이터를 불러옵니다."""
    try:
        client = get_sheet_client()
        sh = client.open("Investment_Dashboard_DB")
        ws = sh.worksheet("Unified_Ledger")
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame(columns=RAW_DB_COLUMNS)
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"DB 로드 실패: {e}")
        return pd.DataFrame(columns=RAW_DB_COLUMNS)

def save_ledger(df):
    """구글 스프레드시트에 파생 변수를 제거하고 순수 데이터만 덮어씁니다."""
    for col in RAW_DB_COLUMNS:
        if col not in df.columns:
            df[col] = ''
            
    # 파생 더미 열(Cash_KRW 등)을 날려버리고 순수 원시 데이터만 추출
    df_to_save = df[RAW_DB_COLUMNS].copy()
    
    try:
        client = get_sheet_client()
        sh = client.open("Investment_Dashboard_DB")
        ws = sh.worksheet("Unified_Ledger")
        ws.clear()
        ws.update([df_to_save.columns.values.tolist()] + df_to_save.fillna("").values.tolist())
        
        # 메모리(세션)에는 다시 파생 변수를 계산해서 띄워줌
        st.session_state.processed_ledger = calculate_reservoir_engine(df_to_save)
    except Exception as e:
        st.error(f"DB 저장 실패: {e}")

def generate_trade_hash(row):
    date_str = pd.to_datetime(row['Date']).strftime('%Y-%m-%d')
    raw_str = f"{date_str}_{row['Ticker']}_{row['Type']}_{row['Qty']}_{row['Price']}"
    return hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

def sort_ledger_events(df):
    if df.empty: return df
    df['Priority'] = df['Category'].map(EVENT_PRIORITY).fillna(99)
    df['Date'] = pd.to_datetime(df['Date'])
    df_sorted = df.sort_values(by=['Date', 'Priority'], ascending=[True, True]).reset_index(drop=True)
    # Date를 다시 문자열 포맷으로 변환 (Google Sheets 저장 최적화)
    df_sorted['Date'] = df_sorted['Date'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return df_sorted.drop(columns=['Priority'])

def calculate_reservoir_engine(df):
    if df.empty: return df
    
    cash_pool = {c: 0.0 for c in TARGET_CURRENCIES}
    invested_krw_pool = {c: 0.0 for c in TARGET_CURRENCIES}
    avg_fx_rate = {c: 0.0 for c in TARGET_CURRENCIES}
    
    res_krw, res_usd, res_jpy, res_hkd = [], [], [], []
    res_avg_rate, res_attached_rate = [], []

    for row in df.itertuples():
        cat, type_, curr = row.Category, row.Type, row.Currency
        amt_local = (row.Qty * row.Price) if cat == 'Trade' else getattr(row, 'Amount_Local', 0.0)
        amt_krw = getattr(row, 'Amount_KRW', 0.0)
        
        attached_rate = 0.0
        current_avg_rate = avg_fx_rate.get(curr, 0.0)

        if cat == 'Money':
            if type_ == 'Deposit' and curr == 'KRW': cash_pool['KRW'] += amt_krw
            elif type_ == 'Withdraw' and curr == 'KRW': cash_pool['KRW'] -= amt_krw
            elif type_ == 'FX':
                if amt_local > 0: 
                    cash_pool['KRW'] -= amt_krw
                    cash_pool[curr] += amt_local
                    invested_krw_pool[curr] += amt_krw
                else: 
                    cash_pool['KRW'] += amt_krw
                    cash_pool[curr] += amt_local 
                    invested_krw_pool[curr] += amt_local * current_avg_rate
                if cash_pool[curr] > 0: avg_fx_rate[curr] = invested_krw_pool[curr] / cash_pool[curr]
            
            elif type_ == 'Dividend': 
                cash_pool[curr] += amt_local
                if cash_pool[curr] > 0: avg_fx_rate[curr] = invested_krw_pool[curr] / cash_pool[curr]

        elif cat == 'Trade':
            if type_ == 'Buy':
                cash_pool[curr] -= amt_local
                attached_rate = avg_fx_rate[curr]
                invested_krw_pool[curr] -= amt_local * attached_rate
            elif type_ == 'Sell':
                cash_pool[curr] += amt_local
                attached_rate = avg_fx_rate[curr]
                invested_krw_pool[curr] += amt_local * attached_rate

        res_krw.append(cash_pool['KRW'])
        res_usd.append(cash_pool['USD'])
        res_jpy.append(cash_pool['JPY'])
        res_hkd.append(cash_pool['HKD'])
        res_avg_rate.append(avg_fx_rate.get(curr, 0.0) if curr in TARGET_CURRENCIES else 0.0)
        res_attached_rate.append(attached_rate)

    df_calc = df.copy()
    df_calc['Cash_KRW'], df_calc['Cash_USD'], df_calc['Cash_JPY'], df_calc['Cash_HKD'] = res_krw, res_usd, res_jpy, res_hkd
    df_calc['Current_Pool_Rate'] = res_avg_rate
    df_calc['Attached_FX_Rate'] = res_attached_rate
    return df_calc

# ==========================================
# 2. 파싱 및 API 동기화 엔진
# ==========================================
def parse_kakao_money_events(text):
    events = []
    
    # 시간 변환 헬퍼 함수 (오전/오후 H:MM -> 24시간제 HH:MM:SS)
    def convert_time(y, m, d, ampm, h, mnt):
        h_int = int(h)
        if ampm == '오후' and h_int < 12:
            h_int += 12
        elif ampm == '오전' and h_int == 12:
            h_int = 0
        return f"{y}-{m.zfill(2)}-{d.zfill(2)} {str(h_int).zfill(2)}:{mnt.zfill(2)}:00"

    # 1. 외화 환전 (매수/매도) 추출 정규식
    # 변경점: 반드시 ', 한국투자증권 :' 이 포함된 개별 메시지 헤더만 인식하도록 강제
    fx_pattern = re.compile(
        r"(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일\s*(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2}):(?P<minute>\d{1,2}),\s*한국투자증권\s*:.*?\n"
        r"(?:.*?\n){0,4}?" # 헤더 이후 최대 4줄 이내에서만 검색 (다른 메시지로 넘어가는 것 방지)
        r"외화(?P<fx_type>매수|매도)환전\s*\n"
        r"(?P<sym1>￦|[A-Z]{3})\s*(?P<val1>[\d,.]+)\s*\n"
        r"@(?P<rate>[\d,.]+)\s*\n"
        r"(?P<sym2>[A-Z]{3}|￦)\s*(?P<val2>[\d,.]+)"
    )
    for match in fx_pattern.finditer(text):
        dt_str = convert_time(match.group('year'), match.group('month'), match.group('day'), 
                              match.group('ampm'), match.group('hour'), match.group('minute'))
        
        sym1, val1, val2 = match.group('sym1'), float(match.group('val1').replace(',', '')), float(match.group('val2').replace(',', ''))
        krw_amt, curr, local_amt = (val1, match.group('sym2'), val2) if sym1 == '￦' else (val2, sym1, -val1)
        
        events.append({
            'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao', 
            'Currency': curr, 'Category': 'Money', 'Type': 'FX',
            'Ticker': '', 'Name': f"외화{match.group('fx_type')}환전", 'Qty': 0.0, 
            'Price': float(match.group('rate').replace(',', '')),
            'Amount_Local': local_amt, 'Amount_KRW': krw_amt, 'Note': ''
        })

    # 2. 해외주식 배당금 추출 정규식
    div_pattern = re.compile(
        r"(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일\s*(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2}):(?P<minute>\d{1,2}),\s*한국투자증권\s*:.*?\n"
        r"(?:.*?\n){0,3}?"
        r"(?P<ticker>[A-Z0-9]+)[^\n]*\n"
        r"(?P<curr>[A-Z]{3})\s*(?P<amt>[\d,.]+)\s*\n"
        r"세전배당입금"
    )
    for match in div_pattern.finditer(text):
        dt_str = convert_time(match.group('year'), match.group('month'), match.group('day'), 
                              match.group('ampm'), match.group('hour'), match.group('minute'))
                              
        events.append({
            'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao', 
            'Currency': match.group('curr'), 'Category': 'Money', 'Type': 'Dividend',
            'Ticker': match.group('ticker'), 'Name': '해외 배당금', 'Qty': 0.0, 'Price': 0.0,
            'Amount_Local': round(float(match.group('amt').replace(',', '')) * 0.85, 2), 
            'Amount_KRW': 0.0, 'Note': ''
        })

    # 3. 국내 ETF 결산분배금 추출 정규식
    etf_pattern = re.compile(
        r"(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일\s*(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2}):(?P<minute>\d{1,2}),\s*한국투자증권\s*:.*?\n"
        r"(?:.*?\n){0,4}?"
        r"ETF 결산분배금 입금 안내\s*\n"
        r"\*\s*종목명\s*:\s*(?P<name>[^\n]+)\s*\n"
        r"(?:.*?\n){0,2}?"
        r"\*\s*입금액\s*:\s*(?P<amt>[\d,]+)원"
    )
    for match in etf_pattern.finditer(text):
        dt_str = convert_time(match.group('year'), match.group('month'), match.group('day'), 
                              match.group('ampm'), match.group('hour'), match.group('minute'))
                              
        amt = float(match.group('amt').replace(',', ''))
        events.append({
            'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao', 
            'Currency': 'KRW', 'Category': 'Money', 'Type': 'Dividend',
            'Ticker': 'ETF', 'Name': match.group('name').strip(), 'Qty': 0.0, 'Price': 0.0,
            'Amount_Local': amt, 'Amount_KRW': amt, 'Note': ''
        })

    return events



def sync_api_data():
    st.toast("📡 KIS API와 통신을 시작합니다...", icon="🔄")
    try:
        app_key = st.secrets["kis_api"]["APP_KEY"]
        app_secret = st.secrets["kis_api"]["APP_SECRET"]
        account_no = st.secrets["kis_api"]["CANO"] + st.secrets["kis_api"]["ACNT_PRDT_CD"]
    except Exception:
        st.error("secrets.toml 파일에 KIS API 정보가 설정되어 있지 않습니다.")
        return

    api_manager = KIS_API_Manager(app_key, app_secret, account_no)
    if not api_manager.token: return

    ledger_df = load_ledger()
    if not ledger_df.empty and 'Trade' in ledger_df['Category'].values:
        trade_dates = pd.to_datetime(ledger_df[ledger_df['Category'] == 'Trade']['Date'])
        # 마지막 거래일로부터 일주일 전부터 안전하게 스위핑
        start_date = (trade_dates.max() - timedelta(days=7)).strftime('%Y%m%d')
    else:
        # 최초 동기화 시 넉넉하게 1년 치(365일)를 요청 (매니저가 알아서 30일씩 쪼개서 요청함)
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
        
    end_date = datetime.now().strftime('%Y%m%d')
    
    # 🔴 CTOS4001R 규격에 맞춘 숫자 시장 코드 (01: 미국 전체, 04: 일본 전체, 02: 홍콩)
    target_markets = ["01", "04", "02"] 
    
    fetched_dfs = []
    for market in target_markets:
        df_market = api_manager.fetch_trade_history(start_date, end_date, market)
        if not df_market.empty:
            fetched_dfs.append(df_market)
    
    if fetched_dfs:
        api_df = pd.concat(fetched_dfs, ignore_index=True)
        api_df['PK_HASH'] = api_df.apply(generate_trade_hash, axis=1)
        
        if 'PK_HASH' not in ledger_df.columns:
            ledger_df['PK_HASH'] = ledger_df.apply(lambda x: generate_trade_hash(x) if x['Category'] == 'Trade' else '', axis=1)
            
        existing_hashes = ledger_df['PK_HASH'].dropna().tolist()
        unique_new = api_df[~api_df['PK_HASH'].isin(existing_hashes)]
        
        if not unique_new.empty:
            updated_ledger = sort_ledger_events(pd.concat([ledger_df, unique_new], ignore_index=True))
            save_ledger(updated_ledger)
            st.toast(f"✅ 신규 체결 {len(unique_new)}건이 DB에 병합되었습니다.", icon="✅")
        else:
            st.toast("새로 업데이트할 체결 내역이 없습니다.", icon="ℹ️")
    else:
        st.toast("해당 기간에 발생한 체결 내역이 없습니다.", icon="ℹ️")
        
    st.session_state.processed_ledger = calculate_reservoir_engine(load_ledger())
    st.session_state.initialized = True



# ==========================================
# 3. UI 렌더링 및 포트폴리오
# ==========================================
def build_portfolio(df):
    portfolio = {}
    if df.empty or 'Trade' not in df['Category'].values: return portfolio

    for row in df[df['Category'] == 'Trade'].itertuples():
        tk = row.Ticker
        if tk not in portfolio:
            portfolio[tk] = {'Name': row.Name, 'Currency': row.Currency, 'Qty': 0.0, 'Total_Cost_Local': 0.0, 'Total_Cost_KRW': 0.0}
        
        if row.Type == 'Buy':
            portfolio[tk]['Qty'] += row.Qty
            portfolio[tk]['Total_Cost_Local'] += row.Qty * row.Price
            portfolio[tk]['Total_Cost_KRW'] += (row.Qty * row.Price) * row.Attached_FX_Rate
        elif row.Type == 'Sell' and portfolio[tk]['Qty'] > 0:
            ratio = row.Qty / portfolio[tk]['Qty']
            portfolio[tk]['Total_Cost_Local'] -= portfolio[tk]['Total_Cost_Local'] * ratio
            portfolio[tk]['Total_Cost_KRW'] -= portfolio[tk]['Total_Cost_KRW'] * ratio
            portfolio[tk]['Qty'] -= row.Qty

    active_portfolio = {}
    for tk, data in portfolio.items():
        if data['Qty'] > 0.0001: 
            data['Avg_Price'] = data['Total_Cost_Local'] / data['Qty']
            data['Attached_FX_Rate'] = data['Total_Cost_KRW'] / data['Total_Cost_Local'] if data['Total_Cost_Local'] > 0 else 0
            active_portfolio[tk] = data
    return active_portfolio

def render_dashboard_ui():
    df = st.session_state.get('processed_ledger', pd.DataFrame())
    if df.empty:
        st.info("데이터가 없습니다. API 동기화 또는 입력 매니저를 통해 원장을 구성해주세요.")
        return

    latest = df.iloc[-1]
    portfolio = build_portfolio(df)
    
    current_prices = {tk: data['Avg_Price'] * 1.05 for tk, data in portfolio.items()} 
    live_fx = {'USD': 1380.0, 'JPY': 9.0, 'HKD': 175.0, 'KRW': 1.0}

    st.markdown("### 🌐 Global Assets Overview")
    cube_cols = st.columns(len(TARGET_CURRENCIES) + 1)
    
    currency_assets = {'KRW': latest['Cash_KRW']}
    total_krw = latest['Cash_KRW']
    
    for curr in ['USD', 'JPY', 'HKD']:
        cash_krw = latest[f'Cash_{curr}'] * live_fx[curr]
        stock_krw = sum([data['Qty'] * current_prices[tk] * live_fx[curr] for tk, data in portfolio.items() if data['Currency'] == curr])
        currency_assets[curr] = cash_krw + stock_krw
        total_krw += currency_assets[curr]

    titles = ["총 자산 (KRW)", "미국 자산 (USD)", "일본 자산 (JPY)", "한국 자산 (KRW)", "홍콩 자산 (HKD)"]
    vals = [total_krw, currency_assets['USD'], currency_assets['JPY'], currency_assets['KRW'], currency_assets.get('HKD', 0)]
    
    for i, col in enumerate(cube_cols):
        with col:
            st.markdown(f"""<div class="cube-card">
                <div style="color:#AAA; font-size:1.1rem; margin-bottom:5px;">{titles[i]}</div>
                <div style="color:#FFF; font-size:1.5rem; font-weight:bold;">₩ {vals[i]:,.0f}</div>
            </div>""", unsafe_allow_html=True)
    st.divider()

    for curr in TARGET_CURRENCIES:
        st.markdown(f"### {curr} Market")
        curr_stocks = {tk: data for tk, data in portfolio.items() if data['Currency'] == curr}
        cols = st.columns(4)
        
        pool_rate = df[df['Currency'] == curr].iloc[-1]['Current_Pool_Rate'] if not df[df['Currency'] == curr].empty else 0.0
        with cols[0]:
            st.markdown(f"""<div class="item-card" style="border-left:5px solid #FFCA28;">
                <h5 style="margin-top:0;">💵 {curr} 예수금</h5>
                <div style="font-size:1.8rem; font-weight:bold; color:#FFF;">{latest[f'Cash_{curr}']:,.2f}</div>
                <div style="color:#AAA; font-size:0.9rem; margin-top:10px;">
                    이동평균 환율: <br><strong style="color:#FFF;">{pool_rate:,.2f} KRW</strong>
                </div>
            </div>""", unsafe_allow_html=True)

        col_idx = 1
        for tk, data in curr_stocks.items():
            if col_idx > 3:
                cols = st.columns(4)
                col_idx = 0
            
            cur_p = current_prices[tk]
            avg_p = data['Avg_Price']
            yield_pct = ((cur_p - avg_p) / avg_p) * 100 if avg_p > 0 else 0
            color = COLOR_RED if yield_pct >= 0 else COLOR_BLUE
            
            with cols[col_idx]:
                st.markdown(f"""<div class="item-card" style="border-left:5px solid {color};">
                    <div style="display:flex; justify-content:space-between;">
                        <h5 style="margin:0;">{tk}</h5>
                        <span style="color:{color}; font-weight:bold;">{yield_pct:+.2f}%</span>
                    </div>
                    <div style="color:#AAA; font-size:0.85rem; margin-bottom:10px;">{data['Name'][:12]}</div>
                    <div style="display:flex; justify-content:space-between; font-size:0.9rem;">
                        <span>현재가</span><strong style="color:#FFF;">{cur_p:,.2f}</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:0.9rem;">
                        <span>평단가</span><strong style="color:#FFF;">{avg_p:,.2f}</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:0.85rem; margin-top:8px; color:#888;">
                        <span>📦 {data['Qty']:,.4g} 주</span><span>🏷️ 환율 {data['Attached_FX_Rate']:,.1f}</span>
                    </div>
                </div>""", unsafe_allow_html=True)
            col_idx += 1
        st.write("")

# ==========================================
# 4. 입력 매니저 (UX 개선: 텍스트 입력 및 초기화)
# ==========================================
def render_input_manager():
    st.info("💡 카카오톡 복사 내역 파싱 및 순수 원화 입출금을 기록합니다.")
    tab_manual, tab_kakao = st.tabs(["✍️ 순수 KRW 입출금", "💬 카카오톡 파싱 (배당/환전)"])
    
    with tab_manual:
        # 상태 관리: 날짜는 유지하고 시간은 제출 후 초기화되도록 설정
        if 'ui_input_date' not in st.session_state:
            st.session_state.ui_input_date = datetime.now().strftime("%Y%m%d")
        if 'ui_input_time' not in st.session_state:
            st.session_state.ui_input_time = ""
            
        with st.form("manual_krw_form", clear_on_submit=False):
            col1, col2, col3 = st.columns([1.5, 1, 1.5])
            with col1:
                raw_date = st.text_input("날짜 (YYYYMMDD)", value=st.session_state.ui_input_date)
                raw_time = st.text_input("시간 (HHMMSS)", value=st.session_state.ui_input_time, placeholder="예: 143000")
            with col2:
                inout_type = st.radio("구분", ["Deposit (입금)", "Withdraw (출금)"])
            with col3:
                krw_amount = st.number_input("금액 (KRW)", min_value=0, step=10000)
                note = st.text_input("메모")
                
            submitted = st.form_submit_button("원장 추가")
            
            if submitted:
                if len(raw_date) == 8 and len(raw_time) == 6 and krw_amount > 0:
                    try:
                        # 포맷팅 변환
                        fmt_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
                        fmt_time = f"{raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:]}"
                        dt_str = f"{fmt_date} {fmt_time}"
                        
                        new_row = {
                            'Date': dt_str, 'PK_HASH': '', 'Source': 'Manual_UI', 
                            'Currency': 'KRW', 'Category': 'Money', 
                            'Type': "Deposit" if "Deposit" in inout_type else "Withdraw",
                            'Ticker': '', 'Name': '', 'Qty': 0.0, 'Price': 0.0,
                            'Amount_Local': float(krw_amount), 'Amount_KRW': float(krw_amount), 'Note': note
                        }
                        
                        save_ledger(sort_ledger_events(pd.concat([load_ledger(), pd.DataFrame([new_row])], ignore_index=True)))
                        
                        # 날짜는 킵하고 시간 칸만 초기화
                        st.session_state.ui_input_date = raw_date
                        st.session_state.ui_input_time = ""
                        st.success(f"✅ {dt_str} 데이터가 구글 DB에 영구 저장되었습니다.")
                        time.sleep(0.8) # 사용자에게 저장 완료 메시지 인지시킴
                        st.rerun()      # 폼 초기화를 위한 리런
                    except ValueError:
                        st.error("숫자로만 날짜 8자리, 시간 6자리를 정확히 입력해주세요.")
                else:
                    st.error("날짜 8자리, 시간 6자리 입력 및 금액 0원 이상을 확인해주세요.")

    with tab_kakao:
        kakao_text = st.text_area("카톡 텍스트 입력", height=150)
        if 'parsed_df_draft' not in st.session_state: st.session_state.parsed_df_draft = pd.DataFrame()

        if st.button("🚀 파싱 (초안 생성)") and kakao_text:
            draft_events = parse_kakao_money_events(kakao_text)
            if draft_events:
                st.session_state.parsed_df_draft = pd.DataFrame(draft_events)
                st.success(f"{len(draft_events)}건 추출 완료. 아래 표를 검수하세요.")
            else:
                st.warning("추출 가능한 데이터가 없습니다.")
                
        if not st.session_state.parsed_df_draft.empty:
            edited_df = st.data_editor(st.session_state.parsed_df_draft, num_rows="dynamic", use_container_width=True)
            if st.button("💾 검수 완료 및 구글 DB 병합"):
                save_ledger(sort_ledger_events(pd.concat([load_ledger(), edited_df], ignore_index=True)))
                st.success("✅ 구글 DB에 안전하게 병합되었습니다!")
                st.session_state.parsed_df_draft = pd.DataFrame()
                time.sleep(0.8)
                st.rerun()

# ==========================================
# 5. 앱 메인 루프
# ==========================================
def main():
    if 'initialized' not in st.session_state:
        st.session_state.processed_ledger = calculate_reservoir_engine(load_ledger())
        st.session_state.initialized = True
        
    col_title, col_btn = st.columns([8, 2])
    with col_title: 
        st.title("🌊 Global Multi-Currency Reservoir")
    with col_btn:
        st.write("")
        if st.button("🔄 최신 매매내역 동기화", use_container_width=True):
            sync_api_data()
            st.rerun()

    st.write("")

    # 메인 화면 탭 구성 (사이드바 폐기)
    tab_view, tab_input = st.tabs(["📊 대시보드 뷰어", "📥 원장 관리 (자본 흐름 입력)"])

    with tab_view:
        render_dashboard_ui()

    with tab_input:
        render_input_manager()
        
    # 하단 통합 테이블 검증 뷰
    st.divider()
    with st.expander("🔍 통합 원장 데이터베이스 (Unified Ledger - Calculated)"):
        st.dataframe(st.session_state.get('processed_ledger', pd.DataFrame()), use_container_width=True)

if __name__ == "__main__":
    main()
