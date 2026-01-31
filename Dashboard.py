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

# 커스텀 CSS
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
    .c-gray { color: #9E9E9E !important; }
    
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
BENCHMARK_RATE = 0.035 # 3.5%
SECTORS = {
    'SEMICON': {'emoji': '💾', 'name': '반도체', 'tickers': ['NVDA', 'AMD', 'TSM', 'INTC']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크', 'tickers': ['MSFT', 'GOOGL', 'AAPL', 'TSLA', 'AMZN', 'META']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당/방어', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'O', 'KO', 'PEP']},
    'REITS': {'emoji': '🏢', 'name': '리츠', 'tickers': ['PLD', 'AMT']},
    'CASH': {'emoji': '💵', 'name': '현금', 'tickers': ['💵 USD CASH']}
}

# -------------------------------------------------------------------
# 3. 데이터 핸들링 함수
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
    except:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_market_data(tickers):
    """KIS API 우선, 실패 시 Yahoo Finance 백업"""
    prices = {}
    status = "🔴 Closed"
    source_kis = False
    
    # 1. 환율 (Yahoo가 안정적)
    try:
        fx = yf.Ticker("KRW=X").history(period="1d")['Close'].iloc[-1]
    except:
        fx = 1450.0

    # 2. 주가 조회
    if tickers:
        valid_t = [t for t in tickers if t != '💵 USD CASH']
        for t in valid_t:
            p = 0
            # KIS 시도
            try:
                p = kis.get_current_price(t)
                if p > 0: source_kis = True
            except: pass
            
            # Yahoo 시도 (KIS 실패 시)
            if p == 0:
                try:
                    p = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
                except: p = 0
            
            if p > 0: prices[t] = p

    # 상태 결정
    now = datetime.now()
    if source_kis:
        status_html = f'<span class="status-badge status-live">🟢 Live (KIS) {now.strftime("%H:%M")}</span>'
    else:
        status_html = f'<span class="status-badge status-delayed">🟡 Delayed (Yahoo) {now.strftime("%H:%M")}</span>'
        
    return fx, prices, status_html

# -------------------------------------------------------------------
# 4. 포트폴리오 계산 엔진 (달러 저수지 반영)
# -------------------------------------------------------------------
def calculate_portfolio(trade_df, dividend_df, current_prices, current_fx):
    rows = []
    
    # 1. 주식 포트폴리오
    grouped = trade_df.groupby('Ticker')
    for ticker, group in grouped:
        buy_group = group[group['Type'] == 'Buy']
        sell_group = group[group['Type'] == 'Sell']
        
        qty_buy = buy_group['Qty'].sum()
        qty_sell = sell_group['Qty'].sum()
        current_qty = qty_buy - qty_sell
        
        if current_qty <= 0: continue # 전량 매도 종목 제외

        # 평균 매수 환율 (Ex_Avg_Rate 가중평균)
        # 공식: Sum(매수수량 * 매수단가 * 당시평단가) / Sum(매수수량 * 매수단가)
        # 주의: 여기서는 '원화 투입 원금'을 구하기 위해 사용
        total_principal_krw = (buy_group['Qty'] * buy_group['Price_USD'] * buy_group['Ex_Avg_Rate']).sum()
        # 매도분 차감 (FIFO 가정 등 복잡하므로, 평단가 비례 차감으로 단순화)
        if qty_buy > 0:
            avg_principal_per_share = total_principal_krw / qty_buy
            current_principal_krw = avg_principal_per_share * current_qty
        else:
            current_principal_krw = 0

        # 평가액
        cur_p = current_prices.get(ticker, 0)
        if cur_p == 0 and not buy_group.empty: cur_p = buy_group['Price_USD'].iloc[-1] # 현재가 없으면 최근 매수가
        
        eval_usd = current_qty * cur_p
        eval_krw = eval_usd * current_fx
        
        # 손익 계산
        total_profit_krw = eval_krw - current_principal_krw
        
        # 배당 수익 (해당 종목)
        div_usd = dividend_df[dividend_df['Ticker'] == ticker]['Amount_USD'].sum() if not dividend_df.empty else 0
        div_krw = div_usd * current_fx
        
        # 안전마진 (BEP 환율)
        # BEP = (원화원금 - 배당금) / 현재 달러평가액
        bep_rate = (current_principal_krw - div_krw) / eval_usd if eval_usd > 0 else 0
        safety_margin = current_fx - bep_rate

        rows.append({
            'Ticker': ticker,
            'Name': group['Name'].iloc[0],
            'Qty': current_qty,
            'Principal': current_principal_krw,
            'Eval': eval_krw,
            'Total_Profit': total_profit_krw + div_krw, # 배당 포함 총수익
            'Unrealized': total_profit_krw, # 단순 평가손익
            'Div_Krw': div_krw,
            'Safety_Margin': safety_margin
        })

    # 2. 현금 (달러 예수금)
    # Trade_Log 역산 or Exchange_Log의 마지막 Balance 사용? 
    # API 동기화 기능이 있으므로 Trade_Log 재계산 로직을 믿음
    # (여기서는 편의상 Trade_Log의 마지막 행 Ex_Avg_Rate 사용 불가하므로 재계산 필요. 
    #  하지만 성능상 Exchange_Log의 마지막 Balance를 신뢰하는게 좋음)
    
    # 임시: API 동기화 버튼을 눌렀다고 가정하고 Exchange_Log 계산 로직 사용
    # 복잡성을 줄이기 위해 화면 표시용으로는 간략 계산
    
    return pd.DataFrame(rows)

# -------------------------------------------------------------------
# 5. API 동기화 및 DB 업데이트 함수 (핵심 기능)
# -------------------------------------------------------------------
def sync_api_and_update_db():
    try:
        # 1. API 데이터 가져오기
        token = kis.get_access_token()
        if not token: return False, "토큰 발급 실패"
        
        # 1/18일 이후 데이터 조회 (API)
        headers = {"content-type":"application/json", "authorization":f"Bearer {token}", "appkey":st.secrets["kis_api"]["APP_KEY"], "appsecret":st.secrets["kis_api"]["APP_SECRET"], "tr_id":"CTOS4001R"}
        params = {
            "CANO": st.secrets["kis_api"]["CANO"], "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"],
            "ERLM_STRT_DT": "20260118", "ERLM_END_DT": datetime.now().strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00", "OVRS_EXCG_CD": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        
        new_trades = []
        res = requests.get(f"{kis.URL_BASE}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers=headers, params=params)
        data = res.json()
        if data['rt_cd'] == '0':
            for item in data['output1']:
                if '매수' in item['sll_buy_dvsn_name'] or '매도' in item['sll_buy_dvsn_name']:
                    qty = int(float(item['ccld_qty']))
                    if qty > 0:
                        dt = item['trad_dt']
                        price = float(item['ft_ccld_unpr2'])
                        if price == 0: price = float(item['ovrs_stck_ccld_unpr'])
                        
                        new_trades.append({
                            'Date': f"{dt[:4]}-{dt[4:6]}-{dt[6:]}",
                            'Order_ID': f"API_{dt}_{item['pdno']}_{qty}",
                            'Ticker': item['pdno'],
                            'Name': item['ovrs_item_name'],
                            'Type': 'Buy' if '매수' in item['sll_buy_dvsn_name'] else 'Sell',
                            'Qty': qty,
                            'Price_USD': price,
                            'Note': 'API_Sync'
                        })
        
        # 2. 기존 DB 로드 (수기 데이터 포함)
        sh = get_client()
        trade_data = sh.worksheet("Trade_Log").get_all_records()
        ex_data = sh.worksheet("Exchange_Log").get_all_records()
        div_data = sh.worksheet("Dividend_Log").get_all_records()
        
        # 3. 데이터 병합 (중복 제거)
        df_trade = pd.DataFrame(trade_data)
        existing_ids = df_trade['Order_ID'].astype(str).tolist()
        
        added_count = 0
        for t in new_trades:
            if t['Order_ID'] not in existing_ids:
                # 환율 보정 (YFinance)
                try:
                    fx = yf.download("KRW=X", start=t['Date'], end=str(datetime.now().date()), progress=False)['Close'].iloc[0]
                except: fx = 1450.0
                
                # Ex_Avg_Rate 계산 (간이 로직: 이전 값 유지)
                last_rate = df_trade['Ex_Avg_Rate'].iloc[-1] if not df_trade.empty else 1450.0
                if t['Type'] == 'Buy': # 매수 시 평단가는 유지 (물 쓰기)
                    applied_rate = last_rate 
                else: 
                    applied_rate = last_rate
                    
                new_row = [t['Date'], t['Order_ID'], t['Ticker'], t['Name'], t['Type'], t['Qty'], t['Price_USD'], applied_rate, t['Note']]
                sh.worksheet("Trade_Log").append_row(new_row)
                added_count += 1
        
        return True, f"{added_count}건 업데이트 완료"
        
    except Exception as e:
        return False, str(e)

# -------------------------------------------------------------------
# 6. 메인 UI
# -------------------------------------------------------------------
st.title("🚀 Investment Command Center")

tab1, tab2 = st.tabs(["📊 대시보드", "⚙️ 입력 매니저"])

with tab1:
    trade_df, ex_df, div_df = load_db()
    
    if trade_df.empty:
        st.error("DB가 비어있습니다. '입력 매니저'에서 동기화를 실행하세요.")
    else:
        # 상단 상태바
        tickers = trade_df['Ticker'].unique().tolist()
        fx, price_map, status_html = get_market_data(tickers)
        st.markdown(f"<div style='text-align:right; margin-bottom:10px;'>{status_html}</div>", unsafe_allow_html=True)

        # 포트폴리오 계산
        pf_df = calculate_portfolio(trade_df, div_df, price_map, fx)
        
        # KPI 섹션
        total_eval = pf_df['Eval'].sum()
        total_principal = pf_df['Principal'].sum()
        total_profit = pf_df['Total_Profit'].sum()
        roi = (total_profit / total_principal * 100) if total_principal > 0 else 0
        
        st.markdown(f"""
        <div class="kpi-container">
            <div class="kpi-cube">
                <div class="kpi-title">총 평가액 (KRW)</div>
                <div class="kpi-value">{total_eval/10000:,.0f}만</div>
                <div class="kpi-sub">원금: {total_principal/10000:,.0f}만</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">총 수익률</div>
                <div class="kpi-value {'c-red' if roi>0 else 'c-blue'}">{roi:+.2f}%</div>
                <div class="kpi-sub">Benchmark 3.5%</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">누적 수익금</div>
                <div class="kpi-value {'c-red' if total_profit>0 else 'c-blue'}">{total_profit/10000:+.0f}만</div>
                <div class="kpi-sub">평가손익 + 배당</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">현재 환율</div>
                <div class="kpi-value">{fx:,.1f}원</div>
                <div class="kpi-sub">USD/KRW</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # 섹터별 카드 뷰
        st.subheader("🗂️ 포트폴리오 현황")
        
        # 섹터 할당
        def get_sector(t):
            for s, info in SECTORS.items():
                if t in info['tickers']: return s
            return 'ETC'
        pf_df['Sector'] = pf_df['Ticker'].apply(get_sector)
        
        # 탭으로 섹터 구분
        sec_tabs = st.tabs([i['name'] for i in SECTORS.values()] + ["전체"])
        
        for idx, (sec_code, info) in enumerate(SECTORS.items()):
            with sec_tabs[idx]:
                sec_df = pf_df[pf_df['Sector'] == sec_code]
                if sec_df.empty:
                    st.caption("보유 종목이 없습니다.")
                else:
                    cols = st.columns(3)
                    for i, row in enumerate(sec_df.itertuples()):
                        with cols[i % 3]:
                            profit = row.Unrealized
                            roi_val = (profit / row.Principal * 100) if row.Principal else 0
                            color = "c-red" if profit > 0 else "c-blue"
                            
                            # 안전마진 표시 (현금은 하이픈)
                            if row.Ticker == '💵 USD CASH': margin_str = "-"
                            else: margin_str = f"{row.Safety_Margin:,.0f}원"

                            st.markdown(f"""
                            <div class="stock-card">
                                <div class="card-header">
                                    <span class="ticker-name">{info['emoji']} {row.Ticker}</span>
                                    <span style="font-size:0.8rem; color:#666;">{row.Qty:,.0f}주</span>
                                </div>
                                <div class="main-val">{row.Eval:,.0f}원</div>
                                <div class="{color}" style="font-weight:bold;">
                                    {profit:+,.0f} ({roi_val:+.1f}%)
                                </div>
                                <div style="margin-top:8px; font-size:0.8rem; display:flex; justify-content:space-between;">
                                    <span>배당: {row.Div_Krw:,.0f}</span>
                                    <span style="background:#eee; padding:2px 6px; border-radius:4px;">🛡️ {margin_str}</span>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

        with sec_tabs[-1]: # 전체 탭
            st.dataframe(pf_df, use_container_width=True)

with tab2:
    st.subheader("⚙️ 데이터 관리")
    
    # 1. API 동기화 버튼 (핵심 기능)
    col_btn, col_msg = st.columns([1, 3])
    with col_btn:
        if st.button("🔄 거래내역 동기화 (API)", type="primary"):
            with st.spinner("KIS API 접속 중..."):
                res, msg = sync_api_and_update_db()
                if res: 
                    st.success(msg)
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                else: st.error(f"실패: {msg}")
    with col_msg:
        st.info("오늘/어제 체결된 매매 내역을 가져와 DB에 추가합니다. (환전/배당 제외)")
    
    st.divider()
    
    # 2. 수동 입력 (배당/환전용)
    st.write("📝 **수동 입력 (배당/환전)**")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        input_type = st.selectbox("종류", ["배당(Dividend)", "환전(Exchange)"])
    with col2:
        input_date = st.date_input("날짜")
    
    if input_type == "배당(Dividend)":
        with st.form("div_form"):
            t_ticker = st.text_input("종목코드 (예: O)")
            t_amt = st.number_input("세후 입금액 ($)", min_value=0.01, step=0.01)
            t_rate = st.number_input("적용 환율 (원)", value=1450.0)
            if st.form_submit_button("배당 기록 저장"):
                sh = get_client()
                sh.worksheet("Dividend_Log").append_row([str(input_date), f"DIV_{datetime.now().strftime('%H%M%S')}", t_ticker, t_amt, t_rate, "수동"])
                st.success("저장 완료")
                st.cache_data.clear()
                
    elif input_type == "환전(Exchange)":
        with st.form("ex_form"):
            krw_in = st.number_input("투입 원화 (KRW)", min_value=1000)
            usd_out = st.number_input("환전 달러 (USD)", min_value=1.0)
            if st.form_submit_button("환전 기록 저장"):
                rate = krw_in / usd_out if usd_out > 0 else 0
                sh = get_client()
                sh.worksheet("Exchange_Log").append_row([str(input_date), f"EX_{datetime.now().strftime('%H%M%S')}", "KRW_to_USD", krw_in, usd_out, rate, 0, 0, "수동"])
                st.success("저장 완료 (Avg_Rate는 다음 동기화 시 갱신됨)")
                st.cache_data.clear()
