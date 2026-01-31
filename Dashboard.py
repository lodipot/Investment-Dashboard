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
# 1. 초기 설정 & 스타일
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈")

st.markdown("""
<style>
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
    .kpi-title { font-size: 0.9rem; opacity: 0.7; font-weight: 600; }
    .kpi-value { font-size: 1.8rem; font-weight: 800; margin: 5px 0; }
    .kpi-sub { font-size: 0.8rem; opacity: 0.8; }
    
    .stock-card {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.2);
        border-radius: 12px; padding: 15px; margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .card-header { display: flex; justify-content: space-between; align-items: baseline; }
    .ticker-name { font-size: 1.2rem; font-weight: 800; }
    .main-val { font-size: 1.5rem; font-weight: 700; margin: 5px 0; }
    
    .c-red { color: #FF5252 !important; }
    .c-blue { color: #448AFF !important; }
    
    .status-badge {
        padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8rem;
    }
    .status-live { background-color: #E8F5E9; color: #2E7D32; border: 1px solid #2E7D32; }
    .status-delayed { background-color: #FFF8E1; color: #F57F17; border: 1px solid #F57F17; }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# 2. 설정 값
# -------------------------------------------------------------------
BENCHMARK_RATE = 0.035
SECTORS = {
    'SEMICON': {'emoji': '💾', 'name': '반도체', 'tickers': ['NVDA', 'AMD', 'TSM', 'INTC']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크', 'tickers': ['MSFT', 'GOOGL', 'AAPL', 'TSLA', 'AMZN', 'META']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당/방어', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'O', 'KO', 'PEP']},
    'REITS': {'emoji': '🏢', 'name': '리츠', 'tickers': ['PLD', 'AMT', 'EQIX']},
    'CASH': {'emoji': '💵', 'name': '현금', 'tickers': ['💵 USD CASH']}
}

# -------------------------------------------------------------------
# 3. 데이터 로드 및 전처리
# -------------------------------------------------------------------
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = dict(st.secrets["gcp_service_account"])
    return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)).open("Investment_Dashboard_DB")

def clean_currency(val):
    if isinstance(val, str):
        return float(val.replace(',', ''))
    return float(val) if val else 0.0

@st.cache_data(ttl=60)
def load_db():
    try:
        sh = get_client()
        trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        exchange = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        dividend = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        
        # 전처리
        if not trade.empty:
            trade['Qty'] = trade['Qty'].apply(clean_currency)
            trade['Price_USD'] = trade['Price_USD'].apply(clean_currency)
            # Ex_Avg_Rate가 없거나 비어있으면 0으로 처리 (나중에 계산)
            if 'Ex_Avg_Rate' not in trade.columns: trade['Ex_Avg_Rate'] = 0.0
            trade['Ex_Avg_Rate'] = trade['Ex_Avg_Rate'].apply(clean_currency)
            
        if not exchange.empty:
            exchange['USD_Amount'] = exchange['USD_Amount'].apply(clean_currency)
            exchange['KRW_Amount'] = exchange['KRW_Amount'].apply(clean_currency)
            exchange['Ex_Rate'] = exchange['Ex_Rate'].apply(clean_currency)

        if not dividend.empty:
            # 컬럼명 유연성 확보
            amt_col = 'Amount_USD' if 'Amount_USD' in dividend.columns else dividend.columns[3]
            dividend['Amount'] = dividend[amt_col].apply(clean_currency)
            dividend['Ticker'] = dividend['Ticker'].str.upper()

        return trade, exchange, dividend
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# -------------------------------------------------------------------
# 4. [핵심] 재무 상태 재계산 (파일의 Balance 무시하고 직접 계산)
# -------------------------------------------------------------------
def calculate_financial_status(trade_df, exchange_df, dividend_df):
    """
    모든 거래 기록을 시간순으로 정렬하여 현재의
    1. 달러 예수금 (Cash Balance)
    2. 이동평균 환율 (Avg Rate)
    3. 종목별 평단가 및 수량
    을 산출합니다.
    """
    
    # 1. 모든 이벤트를 타임라인으로 통합
    timeline = []
    
    # 환전
    for _, row in exchange_df.iterrows():
        timeline.append({
            'date': row['Date'], 'type': 'exchange', 
            'usd': row['USD_Amount'], 'krw': row['KRW_Amount'], 'rate': row['Ex_Rate']
        })
        
    # 배당
    for _, row in dividend_df.iterrows():
        timeline.append({
            'date': row['Date'], 'type': 'dividend',
            'usd': row['Amount'], 'krw': 0, 'ticker': row['Ticker']
        })
        
    # 매매
    for _, row in trade_df.iterrows():
        timeline.append({
            'date': row['Date'], 'type': 'trade', 'action': row['Type'],
            'ticker': row['Ticker'], 'qty': row['Qty'], 'price': row['Price_USD'],
            'name': row.get('Name', row['Ticker'])
        })

    # 시간순 정렬
    timeline.sort(key=lambda x: x['date'])
    
    # 2. 시뮬레이션
    current_cash_usd = 0.0
    current_total_krw = 0.0 # 투입된 총 원화 (잔고 기준)
    avg_rate = 0.0
    
    portfolio = {} # { 'AAPL': {'qty': 10, 'invested_krw': 1000000} }
    
    for item in timeline:
        if item['type'] == 'exchange':
            # 환전: 달러 증가, 원화 투입 증가
            current_cash_usd += item['usd']
            current_total_krw += item['krw']
            
        elif item['type'] == 'dividend':
            # 배당: 달러 증가, 원화 투입 없음 (평단가 인하 효과)
            current_cash_usd += item['usd']
            # KRW는 변동 없음
            
        elif item['type'] == 'trade':
            ticker = item['ticker']
            if ticker not in portfolio: portfolio[ticker] = {'qty': 0, 'invested_krw': 0, 'name': item['name']}
            
            # 거래 시점의 이동평균 환율
            current_avg_rate = (current_total_krw / current_cash_usd) if current_cash_usd > 0 else 1450.0
            
            amt_usd = item['qty'] * item['price']
            
            if item['action'] == 'Buy':
                # 매수: 달러 감소, 원화 투입분도 해당 비율만큼 차감 (주식으로 이동)
                current_cash_usd -= amt_usd
                
                # 주식에 투입된 원화 계산 (당시 평단가 적용)
                invested_krw = amt_usd * current_avg_rate
                current_total_krw -= invested_krw
                
                portfolio[ticker]['qty'] += item['qty']
                portfolio[ticker]['invested_krw'] += invested_krw
                
            elif item['action'] == 'Sell':
                # 매도: 달러 증가
                current_cash_usd += amt_usd
                # 원화 투입분 복구 (여기선 수익 포함된 금액이 달러로 들어옴)
                # 매도 시에는 평단가(Avg Rate)가 변하지 않도록 관리하는 것이 일반적
                # 매도한 금액만큼의 가치를 현재 평단가로 환산하여 KRW Pool에 더함
                
                current_total_krw += (amt_usd * current_avg_rate)
                
                # 포트폴리오 조정 (FIFO 복잡하므로 평단 기준 차감)
                if portfolio[ticker]['qty'] > 0:
                    avg_unit_cost = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                    portfolio[ticker]['invested_krw'] -= (avg_unit_cost * item['qty'])
                    portfolio[ticker]['qty'] -= item['qty']

    # 최종 상태 반환
    final_avg_rate = (current_total_krw / current_cash_usd) if current_cash_usd > 0 else 0
    return current_cash_usd, final_avg_rate, portfolio

# -------------------------------------------------------------------
# 5. API 동기화 (누락 데이터 수집)
# -------------------------------------------------------------------
def sync_data():
    try:
        # DB 로드
        sh = get_client()
        trade_data = sh.worksheet("Trade_Log").get_all_records()
        df_trade = pd.DataFrame(trade_data)
        existing_ids = df_trade['Order_ID'].astype(str).tolist() if not df_trade.empty else []
        
        # API 호출
        token = kis.get_access_token()
        url = st.secrets["kis_api"]["URL_BASE"] # [수정] 모듈 변수 대신 직접 호출
        if url.endswith("/"): url = url[:-1]
        
        headers = {"content-type":"application/json", "authorization":f"Bearer {token}", "appkey":st.secrets["kis_api"]["APP_KEY"], "appsecret":st.secrets["kis_api"]["APP_SECRET"], "tr_id":"CTOS4001R"}
        
        # 1월 17일부터 조회 (안전하게)
        params = {
            "CANO": st.secrets["kis_api"]["CANO"], "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"],
            "ERLM_STRT_DT": "20260117", "ERLM_END_DT": datetime.now().strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00", "OVRS_EXCG_CD": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        
        res = requests.get(f"{url}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers=headers, params=params)
        data = res.json()
        
        new_rows = []
        if data['rt_cd'] == '0':
            for item in data['output1']:
                if '매수' in item['sll_buy_dvsn_name'] or '매도' in item['sll_buy_dvsn_name']:
                    dt = item['trad_dt']
                    qty = int(float(item['ccld_qty']))
                    oid = f"API_{dt}_{item['pdno']}_{qty}"
                    
                    if qty > 0 and oid not in existing_ids:
                        price = float(item.get('ft_ccld_unpr2', 0))
                        if price == 0: price = float(item.get('ovrs_stck_ccld_unpr', 0))
                        
                        # [Date, Order_ID, Ticker, Name, Type, Qty, Price, Rate, Note]
                        new_rows.append([
                            f"{dt[:4]}-{dt[4:6]}-{dt[6:]}", oid, item['pdno'], item['ovrs_item_name'],
                            'Buy' if '매수' in item['sll_buy_dvsn_name'] else 'Sell',
                            qty, price, 0, "API_Sync" # Rate는 나중에 계산되므로 0
                        ])
                        
        if new_rows:
            # 날짜순 정렬 후 추가
            new_rows.sort(key=lambda x: x[0])
            sh.worksheet("Trade_Log").append_rows(new_rows)
            return True, f"{len(new_rows)}건 추가됨"
        
        return True, "최신 상태"
        
    except Exception as e:
        return False, str(e)

def get_current_prices(tickers):
    prices = {}
    source_kis = False
    
    # 환율
    try: fx = yf.Ticker("KRW=X").history(period="1d")['Close'].iloc[-1]
    except: fx = 1450.0
    
    # 주가
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
        
    status = "🟢 Live (KIS)" if source_kis else "🟡 Delayed (Yahoo)"
    return fx, prices, status

# -------------------------------------------------------------------
# 6. 메인 UI
# -------------------------------------------------------------------
st.title("🚀 Investment Command Center")

tab1, tab2 = st.tabs(["📊 대시보드", "⚙️ 입력 매니저"])

with tab1:
    trade, ex, div = load_db()
    
    if trade.empty:
        st.warning("데이터가 없습니다. 동기화를 실행해주세요.")
    else:
        # 1. 상태 계산 (파일 Balance 무시, 직접 계산)
        cash_usd, avg_rate, pf_data = calculate_financial_status(trade, ex, div)
        
        # 2. 현재가 조회
        tickers = list(pf_data.keys())
        fx, prices, status = get_current_prices(tickers)
        st.markdown(f"<div style='text-align:right'><span class='status-badge { 'status-live' if 'Live' in status else 'status-delayed'}'>{status}</span></div>", unsafe_allow_html=True)
        
        # 3. 화면 표시용 데이터 생성
        display_rows = []
        
        # 주식
        total_eval = 0
        total_principal = 0
        
        for t, data in pf_data.items():
            qty = data['qty']
            if qty <= 0: continue
            
            principal = data['invested_krw']
            cur_p = prices.get(t, 0)
            eval_krw = qty * cur_p * fx
            
            # 배당 누적
            div_usd = div[div['Ticker'] == t]['Amount'].sum() if not div.empty else 0
            div_krw = div_usd * fx
            
            total_profit = (eval_krw - principal) + div_krw
            
            # 안전마진
            bep = (principal - div_krw) / (qty * cur_p) if (qty * cur_p) > 0 else 0
            margin = fx - bep
            
            total_eval += eval_krw
            total_principal += principal
            
            display_rows.append({
                'Ticker': t, 'Name': data['name'], 'Qty': qty,
                'Principal': principal, 'Eval': eval_krw,
                'Profit': total_profit, 'Div': div_krw,
                'Margin': margin
            })
            
        # 현금
        cash_principal = cash_usd * avg_rate
        cash_eval = cash_usd * fx
        display_rows.append({
            'Ticker': '💵 USD CASH', 'Name': '달러예수금', 'Qty': cash_usd,
            'Principal': cash_principal, 'Eval': cash_eval,
            'Profit': cash_eval - cash_principal, 'Div': 0, 'Margin': 9999
        })
        
        total_eval += cash_eval
        total_principal += cash_principal
        total_profit_sum = sum([r['Profit'] for r in display_rows])
        roi = total_profit_sum / total_principal * 100 if total_principal > 0 else 0
        
        # KPI 큐브
        st.markdown(f"""
        <div class="kpi-container">
            <div class="kpi-cube">
                <div class="kpi-title">총 평가액</div>
                <div class="kpi-value">{total_eval/10000:,.0f}만</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">총 수익률</div>
                <div class="kpi-value {'c-red' if roi>0 else 'c-blue'}">{roi:+.2f}%</div>
                <div class="kpi-sub">Benchmark {BENCHMARK_RATE*100}%</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">누적 수익금</div>
                <div class="kpi-value {'c-red' if total_profit_sum>0 else 'c-blue'}">{total_profit_sum/10000:+.0f}만</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">현재 환율 (평단)</div>
                <div class="kpi-value">{fx:,.1f}원</div>
                <div class="kpi-sub">({avg_rate:,.1f}원)</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # 카드 뷰
        df_disp = pd.DataFrame(display_rows)
        df_disp['Sector'] = df_disp['Ticker'].apply(lambda x: next((k for k,v in SECTORS.items() if x in v['tickers']), 'ETC'))
        
        tabs = st.tabs([v['name'] for v in SECTORS.values()] + ['전체'])
        
        for i, (k, v) in enumerate(SECTORS.items()):
            with tabs[i]:
                sec_data = df_disp[df_disp['Sector'] == k]
                if sec_data.empty: st.info("종목 없음")
                else:
                    cols = st.columns(3)
                    for idx, row in enumerate(sec_data.itertuples()):
                        with cols[idx%3]:
                            pct = (row.Profit / row.Principal * 100) if row.Principal else 0
                            color = "c-red" if row.Profit > 0 else "c-blue"
                            margin_str = "-" if row.Ticker == '💵 USD CASH' else f"{row.Margin:,.0f}원"
                            
                            st.markdown(f"""
                            <div class="stock-card">
                                <div class="card-header">
                                    <span class="ticker-name">{v['emoji']} {row.Ticker}</span>
                                    <span>{row.Qty:,.0f}</span>
                                </div>
                                <div class="main-val">{row.Eval:,.0f}원</div>
                                <div class="{color}">
                                    {row.Profit:+,.0f} ({pct:+.1f}%)
                                </div>
                                <div style="margin-top:8px; font-size:0.8rem; color:#666; display:flex; justify-content:space-between;">
                                    <span>배당 {row.Div:,.0f}</span>
                                    <span>🛡️ {margin_str}</span>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            
        with tabs[-1]:
            st.dataframe(df_disp)

with tab2:
    st.subheader("⚙️ 데이터 동기화")
    if st.button("🔄 거래내역 동기화 (API)", type="primary"):
        with st.spinner("API 조회 중..."):
            res, msg = sync_data()
            if res: st.success(msg); time.sleep(1); st.rerun()
            else: st.error(f"실패: {msg}")
            
    st.divider()
    st.write("📝 **수동 입력 (배당/환전)**")
    c1, c2, c3 = st.columns(3)
    with c1: itype = st.selectbox("구분", ["배당", "환전"])
    with c2: idate = st.date_input("날짜")
    
    if itype == "배당":
        with st.form("d"):
            tk = st.text_input("종목 (예: O)")
            amt = st.number_input("세후 입금($)", 0.01)
            if st.form_submit_button("저장"):
                sh=get_client(); sh.worksheet("Dividend_Log").append_row([str(idate), f"D{int(time.time())}", tk.upper(), amt, 0, "수동"])
                st.success("저장됨")
    else:
        with st.form("e"):
            kin = st.number_input("원화 (KRW)", 1000)
            uout = st.number_input("달러 (USD)", 1.0)
            if st.form_submit_button("저장"):
                rate = kin/uout if uout else 0
                sh=get_client(); sh.worksheet("Exchange_Log").append_row([str(idate), f"E{int(time.time())}", "KRW_to_USD", kin, uout, rate, 0, 0, "수동"])
                st.success("저장됨")
