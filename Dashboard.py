import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import yfinance as yf
import KIS_API_Manager as kis
import Data_Ingestion as di

# -------------------------------------------------------------------
# [1] 설정 & 다크모드 (에러 팝업 영구 차단 CSS 추가)
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
    .metric-container {{
        background-color: {THEME_CARD};
        border: 1px solid {THEME_BORDER};
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
    }}
    .val-up {{ color: {COLOR_RED} !important; font-weight: bold; }}
    .val-down {{ color: {COLOR_BLUE} !important; font-weight: bold; }}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# [2] 통합 원장 로드 및 클라이언트 생성
# -------------------------------------------------------------------
@st.cache_resource
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def load_unified_ledger():
    client = get_sheet_client()
    try:
        ws = client.open("Investment_Dashboard_DB").worksheet("Unified_Ledger")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df = df.sort_values(by='Timestamp').reset_index(drop=True)
        return df, client
    except Exception as e:
        st.error(f"DB 로딩 오류: {e}")
        return pd.DataFrame(), client

df_ledger, g_client = load_unified_ledger()

# -------------------------------------------------------------------
# [3] 사이드바: 데이터 수동 파싱 스테이션 및 API 동기화
# -------------------------------------------------------------------
with st.sidebar:
    st.header("📥 Data Entry Station")
    
    tab_parse, tab_krw = st.tabs(["💬 카톡 파싱", "💰 원화 입출금"])
    
    with tab_parse:
        kakao_text = st.text_area("카카오톡 알림을 붙여넣으세요:", height=150)
        if st.button("파싱 및 적재", use_container_width=True):
            if kakao_text and not df_ledger.empty:
                events = di.parse_kakao_alert(kakao_text)
                count = di.insert_events_to_sheet(g_client, events)
                st.success(f"{count}건의 데이터가 신통합원장에 임시(Pending) 적재되었습니다.")
                time.sleep(1)
                st.rerun()

    with tab_krw:
        entry_date = st.date_input("날짜", datetime.now())
        entry_time = st.time_input("시간", datetime.now().time())
        io_type = st.radio("구분", ["입금", "출금"], horizontal=True)
        krw_amt = st.number_input("원화 금액", min_value=0, step=10000)
        krw_note = st.text_input("출처/메모", placeholder="ex) 국민은행 이체")
        
        if st.button("원장에 기록", use_container_width=True):
            if krw_amt > 0 and not df_ledger.empty:
                dt_combined = datetime.combine(entry_date, entry_time)
                final_amt = krw_amt if io_type == "입금" else -krw_amt
                di.manual_krw_entry(g_client, dt_combined, io_type, final_amt, krw_note)
                st.success("입출금 내역이 원장에 기록되었습니다.")
                time.sleep(1)
                st.rerun()

    st.divider()
    if st.button("🔄 API 체결내역 보완/동기화", type="primary", use_container_width=True):
        with st.spinner("API 데이터 대조 및 Upsert 중..."):
            kis.sync_api_to_ledger(g_client, df_ledger)
        st.success("데이터 무결성 검증 및 업데이트 완료!")
        time.sleep(1)
        st.rerun()

# -------------------------------------------------------------------
# [4] 데이터 분리 및 수익률 엔진 계산 (달러/엔화 저수지 모델)
# -------------------------------------------------------------------
usd_df = df_ledger[df_ledger['Currency'] == 'USD'].copy() if not df_ledger.empty else pd.DataFrame()
jpy_df = df_ledger[df_ledger['Currency'] == 'JPY'].copy() if not df_ledger.empty else pd.DataFrame()

# --- USD 회계 엔진 ---
portfolio_usd = {}
realized_profit_usd = 0
total_krw_invested_usd = 0
total_usd_exchanged = 0
accum_div_usd = 0

if not usd_df.empty:
    ex_usd = usd_df[usd_df['Event_Type'] == '환전']
    total_krw_invested_usd = ex_usd['KRW_Amount'].sum()
    total_usd_exchanged = ex_usd['Total_Amount'].sum()
    accum_div_usd = usd_df[usd_df['Event_Type'] == '배당']['Total_Amount'].sum()
    
    trades_usd = usd_df[usd_df['Event_Type'].isin(['매수', '매도'])]
    for _, row in trades_usd.iterrows():
        tk = row['Ticker']
        qty = float(row['Quantity'])
        price = float(row['Price'])
        if row['Event_Type'] == '매수':
            if tk not in portfolio_usd:
                portfolio_usd[tk] = {'qty': 0, 'avg_price': 0, 'currency': 'USD', 'raw_ticker': tk, 'name': row['Asset_Name']}
            old_qty = portfolio_usd[tk]['qty']
            old_avg = portfolio_usd[tk]['avg_price']
            if old_qty + qty > 0:
                portfolio_usd[tk]['avg_price'] = (old_avg * old_qty + price * qty) / (old_qty + qty)
            portfolio_usd[tk]['qty'] += qty
        elif row['Event_Type'] == '매도':
            if tk in portfolio_usd:
                realized_profit_usd += (price - portfolio_usd[tk]['avg_price']) * qty
                portfolio_usd[tk]['qty'] -= qty

portfolio_usd = {k: v for k, v in portfolio_usd.items() if v['qty'] > 0}
avg_usd_rate = total_krw_invested_usd / total_usd_exchanged if total_usd_exchanged > 0 else 0

# --- JPY 회계 엔진 ---
portfolio_jpy = {}
realized_profit_jpy = 0
total_krw_invested_jpy = 0
total_jpy_exchanged = 0
accum_div_jpy = 0

if not jpy_df.empty:
    ex_jpy = jpy_df[jpy_df['Event_Type'] == '환전']
    total_krw_invested_jpy = ex_jpy['KRW_Amount'].sum()
    total_jpy_exchanged = ex_jpy['Total_Amount'].sum()
    accum_div_jpy = jpy_df[jpy_df['Event_Type'] == '배당']['Total_Amount'].sum()
    
    trades_jpy = jpy_df[jpy_df['Event_Type'].isin(['매수', '매도'])]
    for _, row in trades_jpy.iterrows():
        tk = row['Ticker']
        qty = float(row['Quantity'])
        price = float(row['Price'])
        if row['Event_Type'] == '매수':
            if tk not in portfolio_jpy:
                portfolio_jpy[tk] = {'qty': 0, 'avg_price': 0, 'currency': 'JPY', 'raw_ticker': tk, 'name': row['Asset_Name']}
            old_qty = portfolio_jpy[tk]['qty']
            old_avg = portfolio_jpy[tk]['avg_price']
            if old_qty + qty > 0:
                portfolio_jpy[tk]['avg_price'] = (old_avg * old_qty + price * qty) / (old_qty + qty)
            portfolio_jpy[tk]['qty'] += qty
        elif row['Event_Type'] == '매도':
            if tk in portfolio_jpy:
                realized_profit_jpy += (price - portfolio_jpy[tk]['avg_price']) * qty
                portfolio_jpy[tk]['qty'] -= qty

portfolio_jpy = {k: v for k, v in portfolio_jpy.items() if v['qty'] > 0}
avg_jpy_rate = (total_krw_invested_jpy / total_jpy_exchanged) * 100 if total_jpy_exchanged > 0 else 0

# 통합 포트폴리오 딕셔너리 (시세 페칭용)
full_portfolio = {**portfolio_usd, **portfolio_jpy}

# -------------------------------------------------------------------
# [5] 백그라운드 시세 페칭 (yfinance & KIS API)
# -------------------------------------------------------------------
if st.session_state.get('needs_fetch', False):
    st.toast("📡 최신 시세를 동기화합니다...", icon="🔄")
    new_prices = {}
    old_prices = st.session_state.get('price_cache', {})
    
    for tk, data in full_portfolio.items():
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
        new_usd = usd_data['Close'].iloc[-1] if not usd_data.empty else 1400.0
    except: new_usd = 1400.0

    try:
        jpy_data = yf.Ticker("JPYKRW=X").history(period="1d")
        new_jpy = jpy_data['Close'].iloc[-1] * 100 if not jpy_data.empty else 900.0
    except: new_jpy = 900.0
    
    st.session_state['price_cache'] = new_prices
    st.session_state['usd_krw'] = new_usd
    st.session_state['jpy_krw'] = new_jpy
    st.session_state['needs_fetch'] = False

current_prices = st.session_state.get('price_cache', {})
current_usd_rate = st.session_state.get('usd_krw', 1400.0)
current_jpy_rate = st.session_state.get('jpy_krw', 900.0)

# -------------------------------------------------------------------
# [6] 메인 대시보드 UI (Metrics & Tabs)
# -------------------------------------------------------------------
st.title("🏦 Investment Command Center")

# 가치 계산
total_eval_usd = sum(v['qty'] * current_prices.get(k, v['avg_price']) for k, v in portfolio_usd.items())
total_eval_jpy = sum(v['qty'] * current_prices.get(k, v['avg_price']) for k, v in portfolio_jpy.items())

total_krw_eval = (total_eval_usd * current_usd_rate) + (total_eval_jpy * current_jpy_rate / 100)
total_krw_invested_all = total_krw_invested_usd + total_krw_invested_jpy
total_pnl = total_krw_eval - total_krw_invested_all

st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
col1, col2, col3 = st.columns(3)
col1.metric("총 투자원금 (KRW)", f"₩ {total_krw_invested_all:,.0f}")
col2.metric("총 평가금액 (KRW)", f"₩ {total_krw_eval:,.0f}", f"{total_pnl:,.0f} KRW")
col3.metric("현재 환율 (USD / JPY)", f"₩ {current_usd_rate:,.2f} / ₩ {current_jpy_rate:,.2f}")
st.markdown("</div>", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["📈 Portfolio (USD)", "💴 Portfolio (JPY)", "⚙️ System Log"])

with tab1:
    st.subheader("🇺🇸 USD 달러 저수지")
    u_col1, u_col2, u_col3, u_col4 = st.columns(4)
    u_col1.metric("평균 환전환율", f"₩ {avg_usd_rate:,.2f}")
    u_col2.metric("누적 배당금", f"$ {accum_div_usd:,.2f}")
    u_col3.metric("달러 실현손익", f"$ {realized_profit_usd:,.2f}")
    u_col4.metric("주식 평가금액", f"$ {total_eval_usd:,.2f}")
    
    # Portfolio Table 구축
    display_data_usd = []
    for k, v in portfolio_usd.items():
        cp = current_prices.get(k, v['avg_price'])
        pnl_pct = ((cp - v['avg_price']) / v['avg_price'] * 100) if v['avg_price'] > 0 else 0
        display_data_usd.append({
            "종목명": v['name'],
            "Ticker": k,
            "보유수량": v['qty'],
            "평단가": f"$ {v['avg_price']:,.2f}",
            "현재가": f"$ {cp:,.2f}",
            "수익률(%)": round(pnl_pct, 2),
            "평가금액": f"$ {v['qty']*cp:,.2f}"
        })
    if display_data_usd:
        st.dataframe(pd.DataFrame(display_data_usd), use_container_width=True)
    else:
        st.info("USD 보유 종목이 없습니다.")

with tab2:
    st.subheader("🇯🇵 JPY 엔화 저수지")
    j_col1, j_col2, j_col3, j_col4 = st.columns(4)
    j_col1.metric("평균 환전환율(100엔)", f"₩ {avg_jpy_rate:,.2f}")
    j_col2.metric("누적 배당금", f"¥ {accum_div_jpy:,.0f}")
    j_col3.metric("엔화 실현손익", f"¥ {realized_profit_jpy:,.0f}")
    j_col4.metric("주식 평가금액", f"¥ {total_eval_jpy:,.0f}")
    
    display_data_jpy = []
    for k, v in portfolio_jpy.items():
        cp = current_prices.get(k, v['avg_price'])
        pnl_pct = ((cp - v['avg_price']) / v['avg_price'] * 100) if v['avg_price'] > 0 else 0
        display_data_jpy.append({
            "종목명": v['name'],
            "Ticker": k,
            "보유수량": v['qty'],
            "평단가": f"¥ {v['avg_price']:,.0f}",
            "현재가": f"¥ {cp:,.0f}",
            "수익률(%)": round(pnl_pct, 2),
            "평가금액": f"¥ {v['qty']*cp:,.0f}"
        })
    if display_data_jpy:
        st.dataframe(pd.DataFrame(display_data_jpy), use_container_width=True)
    else:
        st.info("JPY 보유 종목이 없습니다.")

with tab3:
    st.subheader("원장 데이터 검증 (Unified Ledger)")
    if not df_ledger.empty:
        # 역순 정렬하여 최신 내역이 위로 오도록 표시
        st.dataframe(df_ledger.sort_values(by='Timestamp', ascending=False), use_container_width=True)
    else:
        st.warning("데이터베이스가 비어있습니다. 사이드바에서 초기 데이터를 적재해주세요.")

    if st.button("수동 시세 갱신"):
        st.session_state['needs_fetch'] = True
        st.rerun()
