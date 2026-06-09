import streamlit as st
import pandas as pd
import hashlib
import re
from datetime import datetime, timedelta

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
LEDGER_PATH = "Unified_Ledger_V3.csv"

THEME_CARD = "#18181A"
THEME_BORDER = "#444746"
COLOR_RED = "#FF5252"
COLOR_BLUE = "#448AFF"

st.markdown(f"""
    <style>
    .stException {{ display: none; }}
    .item-card {{ background:{THEME_CARD}; padding:15px; border-radius:8px; height: 165px; margin-bottom: 15px; }}
    .cube-card {{ background:{THEME_CARD}; padding:20px; border-radius:10px; border:1px solid {THEME_BORDER}; text-align:center; }}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 데이터베이스 I/O 및 코어 엔진
# ==========================================
def load_ledger():
    try:
        df = pd.read_csv(LEDGER_PATH)
    except FileNotFoundError:
        df = pd.DataFrame(columns=[
            'Date', 'Category', 'Type', 'Ticker', 'Name', 'Qty', 'Price', 
            'Amount_Local', 'Amount_KRW', 'Currency', 'Source', 'PK_Hash'
        ])
    return df

def save_ledger(df):
    df.to_csv(LEDGER_PATH, index=False)
    # 저장 시 세션 스테이트 동기화
    st.session_state.processed_ledger = calculate_reservoir_engine(df)

def generate_trade_hash(row):
    date_str = pd.to_datetime(row['Date']).strftime('%Y-%m-%d')
    raw_str = f"{date_str}_{row['Ticker']}_{row['Type']}_{row['Qty']}_{row['Price']}"
    return hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

def sort_ledger_events(df):
    if df.empty: return df
    df['Priority'] = df['Category'].map(EVENT_PRIORITY).fillna(99)
    df['Date'] = pd.to_datetime(df['Date'])
    df_sorted = df.sort_values(by=['Date', 'Priority'], ascending=[True, True]).reset_index(drop=True)
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

        # [제1원칙] 물 채우기
        if cat == 'Money':
            if type_ == 'Deposit' and curr == 'KRW': cash_pool['KRW'] += amt_krw
            elif type_ == 'Withdraw' and curr == 'KRW': cash_pool['KRW'] -= amt_krw
            elif type_ == 'FX':
                if amt_local > 0: # KRW Out, FX In
                    cash_pool['KRW'] -= amt_krw
                    cash_pool[curr] += amt_local
                    invested_krw_pool[curr] += amt_krw
                else: # FX Out, KRW In
                    cash_pool['KRW'] += amt_krw
                    cash_pool[curr] += amt_local 
                    invested_krw_pool[curr] += amt_local * current_avg_rate
                if cash_pool[curr] > 0: avg_fx_rate[curr] = invested_krw_pool[curr] / cash_pool[curr]
            
            elif type_ == 'Dividend': # 배당 희석 로직
                cash_pool[curr] += amt_local
                if cash_pool[curr] > 0: avg_fx_rate[curr] = invested_krw_pool[curr] / cash_pool[curr]

        # [제2, 3원칙] 매매와 꼬리표 환율
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
    
    fx_pattern = re.compile(
        r"(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일.*?\n"
        r"(?:.*?\n){1,5}?"
        r"외화(?P<fx_type>매수|매도)환전\s*\n"
        r"(?P<sym1>￦|[A-Z]{3})\s*(?P<val1>[\d,.]+)\s*\n"
        r"@(?P<rate>[\d,.]+)\s*\n"
        r"(?P<sym2>[A-Z]{3}|￦)\s*(?P<val2>[\d,.]+)"
    )
    for match in fx_pattern.finditer(text):
        y, m, d = match.group('year'), match.group('month').zfill(2), match.group('day').zfill(2)
        sym1, val1, val2 = match.group('sym1'), float(match.group('val1').replace(',', '')), float(match.group('val2').replace(',', ''))
        krw_amt, curr, local_amt = (val1, match.group('sym2'), val2) if sym1 == '￦' else (val2, sym1, -val1)
        
        events.append({
            'Date': f"{y}-{m}-{d} 00:00:00", 'Category': 'Money', 'Type': 'FX',
            'Ticker': '', 'Name': f"외화{match.group('fx_type')}환전", 'Qty': 0.0, 
            'Price': float(match.group('rate').replace(',', '')),
            'Amount_Local': local_amt, 'Amount_KRW': krw_amt,
            'Currency': curr, 'Source': 'Kakao', 'PK_Hash': ''
        })

    div_pattern = re.compile(
        r"(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일.*?\n(?:.*?\n)?.*?\d{2}/\d{2}\s*\n"
        r"(?P<ticker>[A-Z0-9]+)[^\n]*\n(?P<curr>[A-Z]{3})\s*(?P<amt>[\d,.]+)\s*\n세전배당입금"
    )
    for match in div_pattern.finditer(text):
        y, m, d = match.group('year'), match.group('month').zfill(2), match.group('day').zfill(2)
        events.append({
            'Date': f"{y}-{m}-{d} 00:00:00", 'Category': 'Money', 'Type': 'Dividend',
            'Ticker': match.group('ticker'), 'Name': '해외 배당금', 'Qty': 0.0, 'Price': 0.0,
            'Amount_Local': round(float(match.group('amt').replace(',', '')) * 0.85, 2), 
            'Amount_KRW': 0.0, 'Currency': match.group('curr'), 'Source': 'Kakao', 'PK_Hash': ''
        })

    etf_pattern = re.compile(
        r"(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일.*?\n(?:.*?\n)*?"
        r"ETF 결산분배금 입금 안내\s*\n\*\s*종목명\s*:\s*(?P<name>[^\n]+)\s*\n(?:.*?\n)*?"
        r"\*\s*입금액\s*:\s*(?P<amt>[\d,]+)원"
    )
    for match in etf_pattern.finditer(text):
        y, m, d = match.group('year'), match.group('month').zfill(2), match.group('day').zfill(2)
        amt = float(match.group('amt').replace(',', ''))
        events.append({
            'Date': f"{y}-{m}-{d} 00:00:00", 'Category': 'Money', 'Type': 'Dividend',
            'Ticker': 'ETF', 'Name': match.group('name').strip(), 'Qty': 0.0, 'Price': 0.0,
            'Amount_Local': amt, 'Amount_KRW': amt, 'Currency': 'KRW', 'Source': 'Kakao', 'PK_Hash': ''
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
        start_date = (trade_dates.max() - timedelta(days=3)).strftime('%Y%m%d')
    else:
        start_date = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
        
    end_date = datetime.now().strftime('%Y%m%d')
    target_markets = ["NASD", "NYSE", "AMEX", "TYO", "SEHK"]
    fetched_dfs = [api_manager.fetch_trade_history(start_date, end_date, m) for m in target_markets]
    fetched_dfs = [df for df in fetched_dfs if not df.empty]
    
    if fetched_dfs:
        api_df = pd.concat(fetched_dfs, ignore_index=True)
        api_df['PK_Hash'] = api_df.apply(generate_trade_hash, axis=1)
        
        if 'PK_Hash' not in ledger_df.columns:
            ledger_df['PK_Hash'] = ledger_df.apply(lambda x: generate_trade_hash(x) if x['Category'] == 'Trade' else None, axis=1)
            
        existing_hashes = ledger_df['PK_Hash'].dropna().tolist()
        unique_new = api_df[~api_df['PK_Hash'].isin(existing_hashes)]
        
        if not unique_new.empty:
            updated_ledger = sort_ledger_events(pd.concat([ledger_df, unique_new], ignore_index=True))
            save_ledger(updated_ledger)
            st.toast(f"✅ 신규 체결 {len(unique_new)}건이 병합되었습니다.", icon="✅")
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
    col_title, col_btn = st.columns([8, 2])
    with col_title: st.title("🌊 Global Multi-Currency Reservoir")
    with col_btn:
        st.write("")
        if st.button("🔄 최신 내역 동기화", use_container_width=True):
            sync_api_data()
            st.rerun()

    df = st.session_state.get('processed_ledger', pd.DataFrame())
    if df.empty:
        st.info("데이터가 없습니다. API 동기화 또는 입력 매니저를 통해 원장을 구성해주세요.")
        return

    latest = df.iloc[-1]
    portfolio = build_portfolio(df)
    
    # 임시 실시간 시세 (추후 yfinance 및 KIS 시세 로직 연결)
    current_prices = {tk: data['Avg_Price'] * 1.05 for tk, data in portfolio.items()} 
    live_fx = {'USD': 1380.0, 'JPY': 9.0, 'HKD': 175.0, 'KRW': 1.0} # JPY는 100엔 기준이 아닌 1엔 기준으로 세팅

    # --- [Top] 통합 큐브 ---
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

    # --- [Sections] 시장별 카드 ---
    for curr in TARGET_CURRENCIES:
        st.markdown(f"### {curr} Market")
        curr_stocks = {tk: data for tk, data in portfolio.items() if data['Currency'] == curr}
        cols = st.columns(4)
        
        # 1. Cash 카드
        pool_rate = df[df['Currency'] == curr].iloc[-1]['Current_Pool_Rate'] if not df[df['Currency'] == curr].empty else 0.0
        with cols[0]:
            st.markdown(f"""<div class="item-card" style="border-left:5px solid #FFCA28;">
                <h5 style="margin-top:0;">💵 {curr} 예수금</h5>
                <div style="font-size:1.8rem; font-weight:bold; color:#FFF;">{latest[f'Cash_{curr}']:,.2f}</div>
                <div style="color:#AAA; font-size:0.9rem; margin-top:10px;">
                    이동평균 환율: <br><strong style="color:#FFF;">{pool_rate:,.2f} KRW</strong>
                </div>
            </div>""", unsafe_allow_html=True)

        # 2. Stock 카드
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

def render_input_manager():
    st.markdown("### 📥 자본 흐름 입력 매니저")
    tab_manual, tab_kakao = st.tabs(["✍️ 순수 KRW 입출금", "💬 카카오톡 파싱 (배당/환전)"])
    
    with tab_manual:
        with st.form("manual_krw_form"):
            col1, col2, col3 = st.columns([1.5, 1, 1.5])
            with col1:
                input_date = st.date_input("날짜", datetime.today())
                input_time = st.time_input("시간", datetime.now().time())
            with col2:
                inout_type = st.radio("구분", ["Deposit (입금)", "Withdraw (출금)"])
            with col3:
                krw_amount = st.number_input("금액 (KRW)", min_value=0, step=10000)
                note = st.text_input("메모")
                
            if st.form_submit_button("원장 추가") and krw_amount > 0:
                new_row = {
                    'Date': f"{input_date} {input_time.strftime('%H:%M:%S')}", 'Category': 'Money',
                    'Type': "Deposit" if "Deposit" in inout_type else "Withdraw",
                    'Ticker': '', 'Name': note, 'Qty': 0.0, 'Price': 0.0,
                    'Amount_Local': float(krw_amount), 'Amount_KRW': float(krw_amount),
                    'Currency': 'KRW', 'Source': 'Manual_UI', 'PK_Hash': ''
                }
                save_ledger(sort_ledger_events(pd.concat([load_ledger(), pd.DataFrame([new_row])], ignore_index=True)))
                st.success("✅ 원장에 추가되었습니다.")

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
            if st.button("💾 검수 완료 및 DB 병합"):
                save_ledger(sort_ledger_events(pd.concat([load_ledger(), edited_df], ignore_index=True)))
                st.success("✅ 병합 완료!")
                st.session_state.parsed_df_draft = pd.DataFrame()
                st.rerun()

# ==========================================
# 4. 앱 메인 루프 (사이드바 네비게이션)
# ==========================================
def main():
    # 1회 자동 초기화
    if 'initialized' not in st.session_state:
        st.session_state.processed_ledger = calculate_reservoir_engine(load_ledger())
        st.session_state.initialized = True
        
    st.sidebar.title("🏦 Menu")
    app_mode = st.sidebar.radio("이동", ["📊 대시보드 뷰어", "📥 원장 관리 (입력)"])
    st.sidebar.divider()
    st.sidebar.info("**작동 안내**\n- API로 매매 내역을 동기화합니다.\n- 환전/배당은 '원장 관리'에서 카톡 파싱으로 넣으세요.")

    if app_mode == "📊 대시보드 뷰어":
        render_dashboard_ui()
    else:
        render_input_manager()
        
    # 하단 통합 테이블 검증 뷰 (항상 표시)
    st.divider()
    with st.expander("🔍 통합 원장 데이터베이스 (Unified Ledger)"):
        st.dataframe(st.session_state.get('processed_ledger', pd.DataFrame()), use_container_width=True)

if __name__ == "__main__":
    main()
