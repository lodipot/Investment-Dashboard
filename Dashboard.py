import streamlit as st
import pandas as pd
import hashlib
from datetime import datetime
# from KIS_API_Manager import KIS_API_Manager # 작성해주신 API 매니저 모듈 임포트

# ==========================================
# 0. 전역 설정 및 CSS (에러 은닉 및 UI 스타일링)
# ==========================================
st.set_page_config(page_title="Global Multi-Currency Reservoir", layout="wide")

TARGET_CURRENCIES = ['KRW', 'USD', 'JPY', 'HKD']
EVENT_PRIORITY = {'Dividend': 1, 'Deposit': 2, 'Withdraw': 2, 'FX': 3, 'Trade': 4}
LEDGER_PATH = "Unified_Ledger_V3.csv" # 통합원장 파일 경로

# 404 에러 등 기술적 경고창 숨김 및 큐브/카드 UI 스타일 지정
st.markdown("""
    <style>
    /* 에러 메시지 하이드 */
    .stException { display: none; }
    /* KPI 큐브 및 카드 스타일 */
    .kpi-cube {
        background-color: #1E1E1E; padding: 20px; border-radius: 10px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.5); text-align: center; margin-bottom: 20px;
    }
    .kpi-title { font-size: 1.2rem; color: #AAAAAA; margin-bottom: 10px; }
    .kpi-value { font-size: 1.8rem; font-weight: bold; color: #FFFFFF; }
    .color-red { color: #FF4B4B; } /* HTS 수익(빨강) */
    .color-blue { color: #4B4BFF; } /* HTS 손실(파랑) */
    .item-card {
        background-color: #2A2A2A; padding: 15px; border-radius: 8px;
        border-left: 5px solid #555; margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 데이터 처리 및 회계 엔진
# ==========================================
def load_ledger():
    try:
        df = pd.read_csv(LEDGER_PATH)
    except FileNotFoundError:
        # 파일이 없을 경우 빈 스키마 생성
        df = pd.DataFrame(columns=[
            'Date', 'Category', 'Type', 'Ticker', 'Name', 'Qty', 'Price', 
            'Amount_Local', 'Amount_KRW', 'Currency', 'Source', 'PK_Hash'
        ])
    return df

def save_ledger(df):
    df.to_csv(LEDGER_PATH, index=False)

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

def sync_api_data():
    """KIS API를 호출하여 신규 매매 내역만 Upsert"""
    st.toast("API 동기화를 시작합니다...", icon="🔄")
    # api_manager = KIS_API_Manager(APP_KEY, APP_SECRET, ACCOUNT_NO)
    # api_df = api_manager.fetch_trade_history(start_date="20240101", end_date="20241231")
    
    # 더미 데이터 생성 (실제 연동 시 위 주석 해제)
    api_df = pd.DataFrame() 
    
    if not api_df.empty:
        api_df['PK_Hash'] = api_df.apply(generate_trade_hash, axis=1)
        ledger_df = load_ledger()
        if 'PK_Hash' not in ledger_df.columns:
            ledger_df['PK_Hash'] = ledger_df.apply(lambda x: generate_trade_hash(x) if x['Category']=='Trade' else None, axis=1)
            
        existing_hashes = ledger_df['PK_Hash'].dropna().tolist()
        unique_new = api_df[~api_df['PK_Hash'].isin(existing_hashes)]
        
        if not unique_new.empty:
            updated_ledger = pd.concat([ledger_df, unique_new], ignore_index=True)
            updated_ledger = sort_ledger_events(updated_ledger)
            save_ledger(updated_ledger)
            st.toast(f"{len(unique_new)}건의 신규 체결 내역이 업데이트되었습니다.", icon="✅")
        else:
            st.toast("새로운 체결 내역이 없습니다.", icon="ℹ️")
    
    st.session_state.processed_ledger = calculate_reservoir_engine(load_ledger())
    st.session_state.initialized = True

# ==========================================
# 2. 메인 대시보드 UI 랜더링
# ==========================================
def render_dashboard():
    # 상단 헤더 및 수동 동기화 버튼
    col_title, col_btn = st.columns([8, 2])
    with col_title:
        st.title("🌊 Global Multi-Currency Reservoir")
    with col_btn:
        st.write("") # 수직 정렬용 여백
        if st.button("🔄 최신 내역 동기화", use_container_width=True):
            sync_api_data()
            st.rerun()

    # 최초 1회 자동 동기화
    if 'initialized' not in st.session_state:
        sync_api_data()

    df = st.session_state.get('processed_ledger', pd.DataFrame())
    
    # --- [Top] 통합 지휘소 (Asset Cubes) ---
    st.markdown("### 🌐 Global Assets Overview")
    cube_cols = st.columns(len(TARGET_CURRENCIES) + 1)
    
    # 총 자산 및 국가별 자산 큐브 렌더링 (예시 값, 실제 df 연산 로직 연결 필요)
    cube_titles = ["총 자산 (KRW)", "미국 자산 (USD)", "일본 자산 (JPY)", "한국 자산 (KRW)", "홍콩 자산 (HKD)"]
    for i, col in enumerate(cube_cols):
        with col:
            st.markdown(f"""
                <div class="kpi-cube">
                    <div class="kpi-title">{cube_titles[i]}</div>
                    <div class="kpi-value">-</div>
                </div>
            """, unsafe_allow_html=True)

    st.divider()

    # --- [Sections] 통화별 시장 (Cash Card -> Stock Cards) ---
    for curr in TARGET_CURRENCIES:
        st.markdown(f"### {curr} Market")
        
        # 최신 잔고 추출
        latest_cash = df.iloc[-1][f'Cash_{curr}'] if not df.empty else 0.0
        latest_avg_rate = df[df['Currency'] == curr].iloc[-1]['Current_Pool_Rate'] if not df[df['Currency'] == curr].empty else 0.0
        
        # ■ 1. 해당 통화 예수금(Cash) 카드 배치
        st.markdown(f"""
            <div class="item-card" style="border-left-color: #FFB347;">
                <h4>💵 {curr} 예수금 (Cash Pool)</h4>
                <p style="font-size: 1.2rem; margin: 0;">잔고: <strong>{latest_cash:,.2f} {curr}</strong></p>
                <p style="font-size: 1rem; color: #AAAAAA; margin: 0;">이동평균 환율: {latest_avg_rate:,.2f} KRW</p>
            </div>
        """, unsafe_allow_html=True)

        # □ 2. 해당 통화 개별 종목(Stock) 카드 배치
        curr_trades = df[(df['Category'] == 'Trade') & (df['Currency'] == curr)]
        if not curr_trades.empty:
            tickers = curr_trades['Ticker'].unique()
            # 종목 카드 그리드 배치 (3열)
            stock_cols = st.columns(3)
            for idx, ticker in enumerate(tickers):
                with stock_cols[idx % 3]:
                    st.markdown(f"""
                        <div class="item-card">
                            <h5>📈 {ticker}</h5>
                            <p style="margin: 0; color: #888;">상세 구현 영역 (수량, 꼬리표 환율 등)</p>
                        </div>
                    """, unsafe_allow_html=True)
        else:
            st.info(f"보유 중인 {curr} 종목이 없습니다.")
            
        st.write("") # 통화 간 여백

if __name__ == "__main__":
    render_dashboard()
