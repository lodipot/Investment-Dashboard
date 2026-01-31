import streamlit as st
import pandas as pd
import requests
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# 1. 초기 설정 & 스타일 (구버전 CSS 복원 + 상태 배지 추가)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈")

st.markdown("""
<style>
    /* 구버전 KPI 큐브 스타일 복원 */
    .kpi-container {
        display: grid; grid-template-columns: repeat(4, 1fr);
        gap: 10px; margin-bottom: 20px;
    }
    .kpi-cube {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.2);
        border-radius: 12px; padding: 15px; text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .kpi-title { font-size: 0.8rem; opacity: 0.7; font-weight: 600; white-space: nowrap; }
    .kpi-value { font-size: clamp(14px, 2vw, 24px); font-weight: 800; margin: 4px 0; }
    .kpi-sub { font-size: 0.7rem; opacity: 0.8; }
    
    /* 구버전 주식 카드 스타일 복원 */
    .stock-card {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.2);
        border-radius: 12px; padding: 16px; margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .card-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
    .ticker-name { font-size: 1.1rem; font-weight: 700; color: var(--text-color); }
    .main-val { font-size: 1.4rem; font-weight: 800; margin-bottom: 6px; }
    
    /* 유틸리티 클래스 */
    .c-red { color: #FF5252 !important; }
    .c-blue { color: #448AFF !important; }
    .c-gray { color: #9E9E9E !important; }
    
    /* [NEW] 상태 배지 */
    .status-badge {
        padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8rem;
    }
    .status-live { background-color: #E8F5E9; color: #2E7D32; border: 1px solid #2E7D32; }
    .status-delayed { background-color: #FFF8E1; color: #F57F17; border: 1px solid #F57F17; }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# 2. 설정 및 섹터 정의 (반도체 추가)
# -------------------------------------------------------------------
BENCHMARK_RATE = 0.035
SECTORS = {
    'SEMICON': {'emoji': '💾', 'name': '반도체', 'tickers': ['NVDA', 'AMD', 'TSM', 'INTC', 'AVGO']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크', 'tickers': ['MSFT', 'GOOGL', 'AAPL', 'TSLA', 'AMZN', 'META']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당/방어', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'O', 'KO', 'PEP']},
    'REITS': {'emoji': '🏢', 'name': '리츠', 'tickers': ['PLD', 'AMT', 'EQIX']},
    'CASH': {'emoji': '💵', 'name': '현금', 'tickers': ['💵 USD CASH']}
}

# -------------------------------------------------------------------
# 3. 데이터 로드 및 시세 조회
# -------------------------------------------------------------------
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = dict(st.secrets["gcp_service_account"])
    return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)).open("Investment_Dashboard_DB")

@st.cache_data(ttl=60)
def load_db():
    try:
        sh = get_client()
        trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        exchange = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        dividend = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        return trade, exchange, dividend
    except: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_market_data(tickers):
    prices = {}
    source_kis = False
    
    # 1. 환율
    try: fx = yf.Ticker("KRW=X").history(period="1d")['Close'].iloc[-1]
    except: fx = 1450.0

    # 2. 주가 (KIS -> Yahoo Fallback)
    valid_t = [t for t in tickers if t != '💵 USD CASH']
    for t in valid_t:
        p = 0
        try:
            p = kis.get_current_price(t)
            if p > 0: source_kis = True
        except: pass
        
        if p == 0:
            try: p = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
            except: p = 0
        
        if p > 0: prices[t] = p

    status_html = f'<span class="status-badge status-live">🟢 Live (KIS)</span>' if source_kis else f'<span class="status-badge status-delayed">🟡 Delayed (Yahoo)</span>'
    return fx, prices, status_html

# -------------------------------------------------------------------
# 4. 포트폴리오 계산 (Ex_Avg_Rate 사용)
# -------------------------------------------------------------------
def calculate_portfolio(trade_df, div_df, ex_df, prices, fx):
    rows = []
    
    # [주식]
    for ticker, group in trade_df.groupby('Ticker'):
        buy = group[group['Type'] == 'Buy']
        sell = group[group['Type'] == 'Sell']
        
        qty = buy['Qty'].sum() - sell['Qty'].sum()
        if qty <= 0: continue
        
        # 원화 원금 = (매수수량 * 매수단가 * Ex_Avg_Rate) 총합 / 총매수수량 * 현재수량
        # (간단히: 매수 시점의 환율을 적용한 원화 금액의 평단가)
        total_buy_krw = (buy['Qty'] * buy['Price_USD'] * buy['Ex_Avg_Rate']).sum()
        avg_krw_unit = total_buy_krw / buy['Qty'].sum()
        principal_krw = avg_krw_unit * qty
        
        cur_p = prices.get(ticker, buy['Price_USD'].iloc[-1])
        eval_krw = qty * cur_p * fx
        
        # 배당 (종목별)
        div_usd = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() if not div_df.empty else 0
        div_krw = div_usd * fx
        
        # 손익
        total_profit = (eval_krw - principal_krw) + div_krw
        
        # 안전마진 (BEP)
        bep_rate = (principal_krw - div_krw) / (qty * cur_p) if (qty * cur_p) > 0 else 0
        margin = fx - bep_rate

        rows.append({
            'Ticker': ticker, 'Name': group['Name'].iloc[0], 'Qty': qty,
            'Principal': principal_krw, 'Eval': eval_krw,
            'Total_Profit': total_profit, 'Div_Krw': div_krw,
            'Safety_Margin': margin
        })
        
    # [현금] (Exchange_Log의 마지막 Balance 사용)
    if not ex_df.empty:
        last_row = ex_df.iloc[-1]
        cash_usd = float(last_row['Balance'])
        cash_rate = float(last_row['Avg_Rate'])
        
        # 현금은 원금 = 보유달러 * 평단가
        # 평가액 = 보유달러 * 현재환율
        rows.append({
            'Ticker': '💵 USD CASH', 'Name': '달러예수금', 'Qty': cash_usd,
            'Principal': cash_usd * cash_rate,
            'Eval': cash_usd * fx,
            'Total_Profit': (cash_usd * fx) - (cash_usd * cash_rate),
            'Div_Krw': 0, 'Safety_Margin': 9999 # 마커
        })
        
    return pd.DataFrame(rows)

# -------------------------------------------------------------------
# 5. API 동기화 (Sync)
# -------------------------------------------------------------------
def sync_data():
    try:
        # API 조회
        token = kis.get_access_token()
        headers = {"content-type":"application/json", "authorization":f"Bearer {token}", "appkey":st.secrets["kis_api"]["APP_KEY"], "appsecret":st.secrets["kis_api"]["APP_SECRET"], "tr_id":"CTOS4001R"}
        params = {
            "CANO": st.secrets["kis_api"]["CANO"], "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"],
            "ERLM_STRT_DT": "20260118", "ERLM_END_DT": datetime.now().strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00", "OVRS_EXCG_CD": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        res = requests.get(f"{kis.URL_BASE}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers=headers, params=params)
        data = res.json()
        
        new_trades = []
        if data['rt_cd'] == '0':
            # DB 로드하여 중복 체크
            sh = get_client()
            ws = sh.worksheet("Trade_Log")
            df_db = pd.DataFrame(ws.get_all_records())
            exist_ids = df_db['Order_ID'].astype(str).tolist()
            
            # 최신 평단가 (환전 로그에서)
            ex_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
            cur_avg_rate = float(ex_df['Avg_Rate'].iloc[-1]) if not ex_df.empty else 1450.0

            for item in data['output1']:
                if '매수' in item['sll_buy_dvsn_name'] or '매도' in item['sll_buy_dvsn_name']:
                    dt = item['trad_dt']
                    qty = int(float(item['ccld_qty']))
                    oid = f"API_{dt}_{item['pdno']}_{qty}"
                    
                    if oid not in exist_ids and qty > 0:
                        price = float(item.get('ft_ccld_unpr2', 0))
                        if price == 0: price = float(item.get('ovrs_stck_ccld_unpr', 0))
                        
                        t_type = 'Buy' if '매수' in item['sll_buy_dvsn_name'] else 'Sell'
                        
                        new_trades.append([
                            f"{dt[:4]}-{dt[4:6]}-{dt[6:]}", oid, item['pdno'], item['ovrs_item_name'],
                            t_type, qty, price, cur_avg_rate, "API_Sync"
                        ])
            
            if new_trades:
                new_trades.sort(key=lambda x: x[0])
                ws.append_rows(new_trades)
                return True, f"{len(new_trades)}건 업데이트"
        return True, "최신 상태입니다."
    except Exception as e: return False, str(e)

# -------------------------------------------------------------------
# 6. 메인 UI
# -------------------------------------------------------------------
main_tab1, main_tab2 = st.tabs(["📊 대시보드", "⚙️ 입력 매니저"])

with main_tab1:
    trade, ex, div = load_db()
    if trade.empty:
        st.error("DB가 비어있습니다. 먼저 데이터를 복구하세요.")
    else:
        # 상단 정보
        tickers = trade['Ticker'].unique().tolist()
        fx, prices, status_badge = get_market_data(tickers)
        st.markdown(f"<div style='text-align:right'>{status_badge}</div>", unsafe_allow_html=True)
        
        # 계산
        pf = calculate_portfolio(trade, div, ex, prices, fx)
        
        # KPI 큐브
        tot_eval = pf['Eval'].sum()
        tot_prin = pf['Principal'].sum()
        tot_prof = pf['Total_Profit'].sum()
        roi = (tot_prof / tot_prin * 100) if tot_prin else 0
        
        st.markdown(f"""
        <div class="kpi-container">
            <div class="kpi-cube">
                <div class="kpi-title">총 평가액</div>
                <div class="kpi-value">{tot_eval/10000:,.0f}만</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">총 수익률</div>
                <div class="kpi-value {'c-red' if roi>0 else 'c-blue'}">{roi:+.2f}%</div>
                <div class="kpi-sub">Benchmark {BENCHMARK_RATE*100}%</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">누적 수익금</div>
                <div class="kpi-value {'c-red' if tot_prof>0 else 'c-blue'}">{tot_prof/10000:+.0f}만</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">현재 환율</div>
                <div class="kpi-value">{fx:,.1f}원</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # 섹터별 탭
        pf['Sector'] = pf['Ticker'].apply(lambda t: next((k for k,v in SECTORS.items() if t in v['tickers']), 'ETC'))
        
        sec_names = [v['name'] for v in SECTORS.values()] + ['전체']
        tabs = st.tabs(sec_names)
        
        for i, (k, v) in enumerate(SECTORS.items()):
            with tabs[i]:
                sec_data = pf[pf['Sector'] == k]
                if sec_data.empty: st.info("보유 종목 없음")
                else:
                    cols = st.columns(3)
                    for idx, row in enumerate(sec_data.itertuples()):
                        with cols[idx%3]:
                            prof = row.Total_Profit
                            pct = (prof/row.Principal*100) if row.Principal else 0
                            color = "c-red" if prof > 0 else "c-blue"
                            margin = f"{row.Safety_Margin:,.0f}원" if row.Ticker != '💵 USD CASH' else "-"
                            
                            st.markdown(f"""
                            <div class="stock-card">
                                <div class="card-header">
                                    <span class="ticker-name">{v['emoji']} {row.Ticker}</span>
                                    <span>{row.Qty:,.0f}주</span>
                                </div>
                                <div class="main-val">{row.Eval:,.0f}원</div>
                                <div class="{color}">
                                    {prof:+,.0f} ({pct:+.1f}%)
                                </div>
                                <div style="font-size:0.8rem; margin-top:8px; display:flex; justify-content:space-between; color:#666;">
                                    <span>배당 {row.Div_Krw:,.0f}</span>
                                    <span>🛡️ {margin}</span>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            
        with tabs[-1]:
            st.dataframe(pf)

with main_tab2:
    st.subheader("⚙️ 데이터 관리")
    if st.button("🔄 거래내역 동기화 (API)", type="primary"):
        with st.spinner("동기화 중..."):
            res, msg = sync_data()
            if res: st.success(msg); time.sleep(1); st.rerun()
            else: st.error(f"실패: {msg}")
            
    st.divider()
    st.write("📝 **수동 입력 (배당/환전)**")
    c1, c2, c3 = st.columns(3)
    with c1: itype = st.selectbox("종류", ["배당", "환전"])
    with c2: idate = st.date_input("날짜")
    
    if itype == "배당":
        with st.form("d"):
            tk = st.text_input("종목 (예: O)")
            amt = st.number_input("세후 입금($)", 0.01)
            rate = st.number_input("환율", 1450.0)
            if st.form_submit_button("저장"):
                sh=get_client(); sh.worksheet("Dividend_Log").append_row([str(idate), f"D{int(time.time())}", tk, amt, rate, "수동"])
                st.success("저장됨")
    else:
        with st.form("e"):
            kin = st.number_input("투입 원화", 1000)
            uout = st.number_input("환전 달러", 1.0)
            if st.form_submit_button("저장"):
                rate = kin/uout
                sh=get_client(); sh.worksheet("Exchange_Log").append_row([str(idate), f"E{int(time.time())}", "KRW_to_USD", kin, uout, rate, 0, 0, "수동"])
                st.success("저장됨 (평단가는 다음 동기화 시 갱신)")
