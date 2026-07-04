import streamlit as st
import pandas as pd
import hashlib
import re
import time
import requests
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

try:
    from KIS_API_Manager import KIS_API_Manager
except ImportError:
    st.error("KIS_API_Manager.py 파일을 동일한 폴더에 위치시켜주세요.")

# ==========================================
# 0. 전역 설정 및 스키마 정의
# ==========================================
st.set_page_config(page_title="Global Multi-Currency Reservoir", layout="wide", page_icon="🌊")

TARGET_CURRENCIES = ['KRW', 'USD', 'JPY', 'HKD']
EVENT_PRIORITY = {'Dividend': 1, 'Deposit': 2, 'Withdraw': 2, 'FX': 3, 'Trade': 4}
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
    .stTabs [data-baseweb="tab-list"] {{ gap: 24px; }}
    .stTabs [data-baseweb="tab"] {{ height: 50px; white-space: pre-wrap; background-color: transparent; border-radius: 4px 4px 0px 0px; padding-top: 10px; padding-bottom: 10px; }}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 구글 스프레드시트 연동 및 계산 엔진
# ==========================================
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def load_ledger():
    try:
        client = get_sheet_client()
        sh = client.open("Investment_Dashboard_DB")
        ws = sh.worksheet("Unified_Ledger")
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame(columns=RAW_DB_COLUMNS)
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"구글 DB 로드 실패: {e}")
        return pd.DataFrame(columns=RAW_DB_COLUMNS)

def save_ledger(df):
    for col in RAW_DB_COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df_to_save = df[RAW_DB_COLUMNS].copy()
    try:
        client = get_sheet_client()
        sh = client.open("Investment_Dashboard_DB")
        ws = sh.worksheet("Unified_Ledger")
        ws.clear()
        ws.update([df_to_save.columns.values.tolist()] + df_to_save.fillna("").values.tolist())
        st.session_state.processed_ledger = calculate_reservoir_engine(df_to_save)
    except Exception as e:
        st.error(f"구글 DB 저장 실패: {e}")

def sort_ledger_events(df):
    if df.empty: return df
    df['Priority'] = df['Category'].map(EVENT_PRIORITY).fillna(99)
    df['Date'] = pd.to_datetime(df['Date'])
    df_sorted = df.sort_values(by=['Date', 'Priority'], ascending=[True, True]).reset_index(drop=True)
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
        if data['Qty'] > 0.00001: 
            data['Avg_Price'] = data['Total_Cost_Local'] / data['Qty']
            data['Attached_FX_Rate'] = data['Total_Cost_KRW'] / data['Total_Cost_Local'] if data['Total_Cost_Local'] > 0 else 0
            active_portfolio[tk] = data
    return active_portfolio

# ==========================================
# 2. 카카오톡 대화 파서 엔진 (다중 클립보드 & 세금 정밀보정 적용)
# ==========================================
# ==========================================
# 2. 카카오톡 대화 파서 엔진 (다중 클립보드 & 세금 정밀보정 적용)
# ==========================================
def parse_kakao_money_events(text):
    events = []
    
    # 💡 핵심 1: 데이터 블록의 '시작점'을 기준으로 바로 앞 150글자를 스캔하여 
    # 흩어져 있는 날짜(MM/DD)와 시간(HH:MM)을 역추적(Look-behind)으로 뽑아냅니다.
    def get_context_datetime(full_text, match_start):
        context = full_text[max(0, match_start - 150):match_start]
        now = datetime.now()
        y, m, d = now.year, now.month, now.day
        hh, mm = 0, 0
        
        date_m = re.findall(r"(\d{1,2})/(\d{1,2})", context)
        if date_m:
            m, d = int(date_m[-1][0]), int(date_m[-1][1])
            
        time_m = re.findall(r"(\d{1,2}):(\d{2})", context)
        if time_m:
            hh, mm = int(time_m[-1][0]), int(time_m[-1][1])
            
        return f"{y}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}:00"

    # 1. 해외주식 배당 (형식에 얽매이지 않고 내용만 낚아챔)
    div_pat = re.compile(
        r"(?P<ticker>[A-Za-z0-9]+)(?:/(?P<name>[^\n]*))?\s*\n"
        r"(?P<curr>[A-Z]{3}|￦|KRW)\s*(?P<amt>[\d,.]+)\s*\n"
        r"세전배당입금"
    )
    for m in div_pat.finditer(text):
        dt_str = get_context_datetime(text, m.start())
        gross_amt = float(m.group('amt').replace(',', ''))
        
        # 💡 핵심 2: 단순 0.85 곱셈이 아닌, 금융권 표준 세금 공제 로직 적용
        # (세금 15%를 먼저 반올림하여 확정한 뒤 세전 금액에서 차감)
        tax = round(gross_amt * 0.15 + 1e-9, 2) 
        net_amt = round(gross_amt - tax, 2)
        
        ticker = m.group('ticker').strip()
        name = m.group('name').strip() if m.group('name') else ticker
        curr_raw = m.group('curr').strip()
        curr = 'KRW' if curr_raw in ['￦', 'KRW'] else curr_raw
        
        events.append({
            'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao', 'Currency': curr, 'Category': 'Money', 'Type': 'Dividend',
            'Ticker': ticker, 'Name': f"배당: {name}", 
            'Qty': 0.0, 'Price': 0.0, 'Amount_Local': net_amt, 'Amount_KRW': 0.0, 
            'Note': f"세전 {gross_amt} (세금 {tax} 차감)"
        })

    # 2. 해외 매매
    ov_trade_pat = re.compile(
        r"\*매매구분:\s*(?P<type>매수|매도)\s*\n"
        r"\*종목명:\s*(?P<ticker>[A-Za-z0-9]+)/?(?P<name>[^\n]*)\n"
        r"\*체결수량:\s*(?P<qty>[\d,.]+)주\s*\n"
        r"\*체결단가:\s*(?P<curr>[A-Z]{3})\s*(?P<price>[\d,.]+)"
    )
    for m in ov_trade_pat.finditer(text):
        dt_str = get_context_datetime(text, m.start())
        t_type = 'Buy' if m.group('type') == '매수' else 'Sell'
        events.append({
            'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao', 'Currency': m.group('curr'), 'Category': 'Trade', 'Type': t_type,
            'Ticker': m.group('ticker').strip(), 'Name': m.group('name').strip() or m.group('ticker').strip(), 
            'Qty': float(m.group('qty').replace(',','')), 'Price': float(m.group('price').replace(',','')),
            'Amount_Local': 0.0, 'Amount_KRW': 0.0, 'Note': '카톡(해외매매)'
        })

    # 3. 국내 매매
    dom_trade_pat = re.compile(
        r"\*매매구분:.*?(?P<type>매수|매도).*?\n"
        r"\*종목명:\s*(?P<name>[^\(\n]+)\((?P<ticker>\d+)\)\s*\n"
        r"\*체결수량:\s*(?P<qty>[\d,.]+)주\s*\n"
        r"\*체결단가:\s*(?P<price>[\d,.]+)원"
    )
    for m in dom_trade_pat.finditer(text):
        dt_str = get_context_datetime(text, m.start())
        t_type = 'Buy' if m.group('type') == '매수' else 'Sell'
        events.append({
            'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao', 'Currency': 'KRW', 'Category': 'Trade', 'Type': t_type,
            'Ticker': m.group('ticker').strip(), 'Name': m.group('name').strip(), 
            'Qty': float(m.group('qty').replace(',','')), 'Price': float(m.group('price').replace(',','')),
            'Amount_Local': 0.0, 'Amount_KRW': 0.0, 'Note': '카톡(국내매매)'
        })

    # 4. 외화 환전
    fx_pat = re.compile(
        r"외화(?P<fx_type>매수|매도)환전\s*\n"
        r"(?P<sym1>￦|[A-Z]{3})\s*(?P<val1>[\d,.]+)\s*\n"
        r"@(?P<rate>[\d,.]+)\s*\n"
        r"(?P<sym2>￦|[A-Z]{3})\s*(?P<val2>[\d,.]+)"
    )
    for m in fx_pat.finditer(text):
        dt_str = get_context_datetime(text, m.start())
        sym1, val1 = m.group('sym1'), float(m.group('val1').replace(',', ''))
        sym2, val2 = m.group('sym2'), float(m.group('val2').replace(',', ''))
        rate = float(m.group('rate').replace(',', ''))
        
        krw_amt, curr, local_amt = (val1, sym2, val2) if sym1 == '￦' else (val2, sym1, -val1)
        
        events.append({
            'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao', 'Currency': curr, 'Category': 'Money', 'Type': 'FX',
            'Ticker': '', 'Name': f"외화{m.group('fx_type')}환전", 'Qty': 0.0, 'Price': rate,
            'Amount_Local': local_amt, 'Amount_KRW': krw_amt, 'Note': ''
        })

    # 5. 미니스탁 소수점 (원화 출납 처리)
    mini_pattern = re.compile(
        r"-\s*구매\(매수\)\s*체결\s*:\s*\d+건,\s*체결금액\s*(?P<buy_amt>[\d,]+)원\s*\n"
        r"-\s*팔기\(매도\)\s*체결\s*:\s*\d+건,\s*체결금액\s*(?P<sell_amt>[\d,]+)원"
    )
    for m in mini_pattern.finditer(text):
        dt_str = get_context_datetime(text, m.start())
        buy_amt = float(m.group('buy_amt').replace(',', ''))
        sell_amt = float(m.group('sell_amt').replace(',', ''))
        
        if buy_amt > 0:
            events.append({
                'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao_Mini', 'Currency': 'KRW', 'Category': 'Money', 'Type': 'Withdraw',
                'Ticker': '', 'Name': '미니스탁 매수출금', 'Qty': 0.0, 'Price': 0.0, 'Amount_Local': buy_amt, 'Amount_KRW': buy_amt, 'Note': ''
            })
        if sell_amt > 0:
            events.append({
                'Date': dt_str, 'PK_HASH': '', 'Source': 'Kakao_Mini', 'Currency': 'KRW', 'Category': 'Money', 'Type': 'Deposit',
                'Ticker': '', 'Name': '미니스탁 매도입금', 'Qty': 0.0, 'Price': 0.0, 'Amount_Local': sell_amt, 'Amount_KRW': sell_amt, 'Note': ''
            })

    return events


# ==========================================
# 3. KIS API 실시간 잔고 검증 엔진 (Audit) 및 핀셋 디버거
# ==========================================
import pandas as pd
import time
from datetime import datetime
import requests
import streamlit as st

def run_full_api_exploration():
    st.title("📊 통합 원장 스캐너 (잔고 + 체결내역)")
    st.caption("현재 잔고와 모든 매매내역을 한 화면에 로드합니다.")
    
    try:
        app_key = st.secrets["kis_api"]["APP_KEY"]
        app_secret = st.secrets["kis_api"]["APP_SECRET"]
        account_no = st.secrets["kis_api"]["CANO"] + st.secrets["kis_api"]["ACNT_PRDT_CD"]
    except Exception:
        st.error("secrets.toml 에러: KIS 키값이 없습니다.")
        return

    api_manager = KIS_API_Manager(app_key, app_secret, account_no)
    if not api_manager.token: 
        st.error("토큰 발급 실패")
        return

    cano = api_manager.account_no[:8]
    acnt_cd = api_manager.account_no[8:]
    
    # ==========================================
    # 1. 현재 잔고 전체 조회 (CTRP6504R)
    # ==========================================
    st.subheader("🏦 1. 실시간 보유 잔고 (CTRP6504R)")
    headers_bal = api_manager._get_common_headers("CTRP6504R")
    url_bal = f"{api_manager.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
    params_bal = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_cd,
        "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "000", "TR_MKET_CD": "00", "INQR_DVSN_CD": "00"
    }
    
    try:
        res_bal = requests.get(url_bal, headers=headers_bal, params=params_bal, timeout=10)
        json_bal = res_bal.json()
        output_bal = json_bal.get("output3", [])
        if output_bal:
            st.dataframe(pd.DataFrame(output_bal), use_container_width=True)
        else:
            st.info("조회된 보유 잔고가 없습니다.")
    except Exception as e:
        st.error(f"잔고 조회 실패: {e}")

    # ==========================================
    # 날짜 세팅 (2025.12.30 ~ 오늘)
    # ==========================================
    start_dt = "20251230"
    end_dt = datetime.now().strftime("%Y%m%d")
    
    # ==========================================
    # 2. 일별거래내역 조회 (CTOS4001R)
    # ==========================================
    st.subheader("📜 2. 일별 거래내역 (CTOS4001R)")
    headers_ctos = api_manager._get_common_headers("CTOS4001R")
    url_ctos = f"{api_manager.base_url}/uapi/overseas-stock/v1/trading/inquire-period-trans"
    params_ctos = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_cd,
        "ERLM_STRT_DT": start_dt, "ERLM_END_DT": end_dt,
        "OVRS_EXCG_CD": "", "PDNO": "", 
        "SLL_BUY_DVSN_CD": "00", "LOAN_DVSN_CD": "", 
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    all_ctos = []
    with st.spinner("CTOS4001R 수집 중..."):
        # 무한루프 방지를 위해 최대 5페이지만 조회 (안전장치)
        for page in range(5):
            try:
                res_ctos = requests.get(url_ctos, headers=headers_ctos, params=params_ctos, timeout=10)
                j_ctos = res_ctos.json()
                if j_ctos.get("output1"):
                    all_ctos.extend(j_ctos["output1"])
                
                tr_cont = res_ctos.headers.get("tr_cont", res_ctos.headers.get("TR_CONT", ""))
                if tr_cont in ["F", "M"]:
                    params_ctos["CTX_AREA_FK100"] = j_ctos.get("ctx_area_fk100", "")
                    params_ctos["CTX_AREA_NK100"] = j_ctos.get("ctx_area_nk100", "")
                    time.sleep(0.2)
                else:
                    break
            except Exception as e:
                st.error(f"CTOS4001R 페이징 중 에러: {e}")
                break
                
    if all_ctos:
        df_ctos = pd.DataFrame(all_ctos)
        st.success(f"✅ 일별거래내역 총 {len(df_ctos)}건 수집 완료")
        st.dataframe(df_ctos, use_container_width=True)
    else:
        st.info("조회된 일별 거래내역이 없습니다.")

    # ==========================================
    # 3. 주문체결내역 조회 (TTTS3035R)
    # ==========================================
    st.subheader("📜 3. 주문 체결내역 (TTTS3035R)")
    headers_ttts = api_manager._get_common_headers("TTTS3035R")
    url_ttts = f"{api_manager.base_url}/uapi/overseas-stock/v1/trading/inquire-ccnl"
    params_ttts = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_cd,
        "PDNO": "%", "ORD_STRT_DT": start_dt, "ORD_END_DT": end_dt,
        "SLL_BUY_DVSN": "00", "CCLD_NCCS_DVSN": "00", "OVRS_EXCG_CD": "%",
        "SORT_SQN": "DS", "ORD_DT": "", "ORD_GNO_BRNO": "", "ODNO": "",
        "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""
    }
    
    all_ttts = []
    with st.spinner("TTTS3035R 수집 중..."):
        # 무한루프 방지를 위해 최대 5페이지만 조회
        for page in range(5):
            try:
                res_ttts = requests.get(url_ttts, headers=headers_ttts, params=params_ttts, timeout=10)
                j_ttts = res_ttts.json()
                if j_ttts.get("output"):
                    all_ttts.extend(j_ttts["output"])
                
                tr_cont = res_ttts.headers.get("tr_cont", res_ttts.headers.get("TR_CONT", ""))
                if tr_cont in ["F", "M"]:
                    params_ttts["CTX_AREA_FK200"] = j_ttts.get("ctx_area_fk200", "")
                    params_ttts["CTX_AREA_NK200"] = j_ttts.get("ctx_area_nk200", "")
                    time.sleep(0.2)
                else:
                    break
            except Exception as e:
                st.error(f"TTTS3035R 페이징 중 에러: {e}")
                break
                
    if all_ttts:
        df_ttts = pd.DataFrame(all_ttts)
        st.success(f"✅ 주문체결내역 총 {len(df_ttts)}건 수집 완료")
        st.dataframe(df_ttts, use_container_width=True)
    else:
        st.info("조회된 주문 체결내역이 없습니다.")

# ==========================================
# 4. 포트폴리오 및 UI 렌더링 계층
# ==========================================
def render_dashboard_ui():
    df = st.session_state.get('processed_ledger', pd.DataFrame())
    if df.empty:
        st.info("데이터가 없습니다. 원화 입금 및 카톡 파싱 데이터부터 구성해 주세요.")
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
                <div style="color:#AAA; font-size:0.9rem; margin-top:10px;">이동평균 환율: <br><strong style="color:#FFF;">{pool_rate:,.2f} KRW</strong></div>
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
                    <div style="display:flex; justify-content:space-between;"><h5 style="margin:0;">{tk}</h5><span style="color:{color}; font-weight:bold;">{yield_pct:+.2f}%</span></div>
                    <div style="color:#AAA; font-size:0.85rem; margin-bottom:10px;">{data['Name'][:12]}</div>
                    <div style="display:flex; justify-content:space-between; font-size:0.9rem;"><span>현재가</span><strong style="color:#FFF;">{cur_p:,.2f}</strong></div>
                    <div style="display:flex; justify-content:space-between; font-size:0.9rem;"><span>평단가</span><strong style="color:#FFF;">{avg_p:,.2f}</strong></div>
                    <div style="display:flex; justify-content:space-between; font-size:0.85rem; margin-top:8px; color:#888;"><span>📦 {data['Qty']:,.4g} 주</span><span>🏷️ 환율 {data['Attached_FX_Rate']:,.1f}</span></div>
                </div>""", unsafe_allow_html=True)
            col_idx += 1
        st.write("")

def render_input_manager():
    tab_manual, tab_kakao = st.tabs(["✍️ 순수 KRW 입출금", "💬 카카오톡 텍스트 파싱 (모든 내역)"])
    with tab_manual:
        if 'ui_input_date' not in st.session_state: st.session_state.ui_input_date = datetime.now().strftime("%Y%m%d")
        if 'ui_input_time' not in st.session_state: st.session_state.ui_input_time = ""
        with st.form("manual_krw_form", clear_on_submit=False):
            col1, col2, col3 = st.columns([1.5, 1, 1.5])
            with col1:
                raw_date = st.text_input("날짜 (YYYYMMDD)", value=st.session_state.ui_input_date)
                raw_time = st.text_input("시간 (HHMMSS)", value=st.session_state.ui_input_time, placeholder="예: 143000")
            with col2: inout_type = st.radio("구분", ["Deposit (입금)", "Withdraw (출금)"])
            with col3:
                krw_amount = st.number_input("금액 (KRW)", min_value=0, step=10000)
                note = st.text_input("메모")
            if st.form_submit_button("원장 추가"):
                if len(raw_date) == 8 and len(raw_time) == 6 and krw_amount > 0:
                    try:
                        dt_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]} {raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:]}"
                        new_row = {
                            'Date': dt_str, 'PK_HASH': '', 'Source': 'Manual_UI', 'Currency': 'KRW', 'Category': 'Money',
                            'Type': "Deposit" if "Deposit" in inout_type else "Withdraw", 'Ticker': '', 'Name': '', 'Qty': 0.0, 'Price': 0.0, 'Amount_Local': float(krw_amount), 'Amount_KRW': float(krw_amount), 'Note': note
                        }
                        save_ledger(sort_ledger_events(pd.concat([load_ledger(), pd.DataFrame([new_row])], ignore_index=True)))
                        st.session_state.ui_input_date = raw_date
                        st.session_state.ui_input_time = ""
                        st.success(f"✅ {dt_str} 데이터가 구글 DB에 저장되었습니다.")
                        time.sleep(0.8)
                        st.rerun()
                    except ValueError: st.error("올바른 형식을 확인해 주세요.")
                else: st.error("날짜 8자리, 시간 6자리를 채워주세요.")

    with tab_kakao:
        kakao_text = st.text_area("카톡 텍스트 입력 (환전, 배당, 온주 및 미니스탁 매매까지 모두 자동 파싱)", height=150)
        if 'parsed_df_draft' not in st.session_state: st.session_state.parsed_df_draft = pd.DataFrame()
        if st.button("🚀 전체 파싱 (초안 생성)") and kakao_text:
            draft_events = parse_kakao_money_events(kakao_text)
            if draft_events:
                st.session_state.parsed_df_draft = pd.DataFrame(draft_events)
                st.success(f"{len(draft_events)}건 추출 완료. (하단 표 확인)")
            else: st.warning("추출 가능한 데이터가 없습니다.")
            
        if not st.session_state.parsed_df_draft.empty:
            edited_df = st.data_editor(st.session_state.parsed_df_draft, num_rows="dynamic", use_container_width=True)
            if st.button("💾 검수 완료 및 구글 DB 영구 병합"):
                save_ledger(sort_ledger_events(pd.concat([load_ledger(), edited_df], ignore_index=True)))
                st.success("✅ 구글 DB 원장에 완벽히 병합되었습니다!")
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
        
    col_title, col_btn1, col_btn2 = st.columns([6, 2, 2])
    with col_title: 
        st.title("🌊 Global Multi-Currency Reservoir")
    with col_btn1:
        st.write("")
        if st.button("🧪 DB-한투 잔고 실시간 검증", use_container_width=True):
            audit_realtime_balance()
    with col_btn2:
        st.write("")
        # 🔴 새로운 핀셋 테스트 버튼 부착
        if st.button("🔍 전체 원장 데이터 스캔 (잔고+내역)", use_container_width=True):
            run_full_api_exploration()
    
    st.write("")

    tab_view, tab_input = st.tabs(["📊 대시보드 뷰어", "📥 원장 관리 (자본 흐름 & 카톡 파싱)"])

    with tab_view:
        render_dashboard_ui()

    with tab_input:
        render_input_manager()
        
    st.divider()
    with st.expander("🔍 통합 원장 데이터베이스 (Unified Ledger - Calculated)"):
        st.dataframe(st.session_state.get('processed_ledger', pd.DataFrame()), use_container_width=True)

if __name__ == "__main__":
    main()
