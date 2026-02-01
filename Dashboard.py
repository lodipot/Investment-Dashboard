import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# [1] UI 스타일 및 설정 (구버전 철학 계승)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="📈")

st.markdown("""
<style>
    /* 전체 컨테이너 및 탭 스타일 */
    .block-container { padding-top: 1rem; }
    
    /* KPI 큐브 그리드 */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        margin-bottom: 20px;
    }
    .kpi-card {
        background-color: #1E1E1E;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #333;
        text-align: center;
    }
    .kpi-label { font-size: 0.8rem; color: #888; margin-bottom: 5px; }
    .kpi-value { font-size: 1.4rem; font-weight: bold; color: #FFF; }
    .kpi-sub { font-size: 0.75rem; color: #AAA; margin-top: 5px; }
    
    /* 주식 카드 스타일 */
    .stock-card {
        background-color: #262626;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
        border-left: 5px solid #555;
    }
    .card-up { border-left-color: #ff4b4b !important; }
    .card-down { border-left-color: #4b4bff !important; }
    
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .card-ticker { font-size: 1.2rem; font-weight: bold; color: #FFF; }
    .card-price { font-size: 1.1rem; font-weight: bold; }
    .price-up { color: #ff4b4b; }
    .price-down { color: #4b4bff; }
    
    .card-body { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; font-size: 0.85rem; color: #DDD; }
    .card-row { display: flex; justify-content: space-between; }
    
    /* 통합 테이블 스타일 */
    .custom-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    .custom-table th { background-color: #333; color: #FFF; padding: 8px; text-align: left; }
    .custom-table td { padding: 8px; border-bottom: 1px solid #444; color: #EEE; }
    .row-buy { background-color: rgba(255, 75, 75, 0.1); }
    .row-sell { background-color: rgba(75, 75, 255, 0.1); }
    .row-div { background-color: rgba(75, 255, 75, 0.1); }
    .badge { padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: bold; }
    .bg-red { background-color: #ff4b4b; color: white; }
    .bg-blue { background-color: #4b4bff; color: white; }
</style>
""", unsafe_allow_html=True)

SECTOR_MAP = {
    'NVDA': '반도체', 'AMD': '반도체', 'TSM': '반도체', 'AVGO': '반도체', 'SOXL': '반도체',
    'O': '배당', 'KO': '배당', 'SCHD': '배당', 'JEPQ': '배당', 'JEPI': '배당', 'MAIN': '배당',
    'MSFT': '빅테크', 'GOOGL': '빅테크', 'AAPL': '빅테크', 'AMZN': '빅테크', 'TSLA': '빅테크',
    'PLD': '리츠', 'AMT': '리츠'
}

# -------------------------------------------------------------------
# [2] 데이터 로드 및 전처리 (Bulletproof)
# -------------------------------------------------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def safe_float(val):
    if pd.isna(val) or val == '': return 0.0
    try: return float(str(val).replace(',', '').strip())
    except: return 0.0

def get_col(row, candidates):
    for col in candidates:
        if col in row: return row[col]
        if col.replace('_', ' ') in row: return row[col.replace('_', ' ')]
    return None

def load_data():
    client = get_gsheet_client()
    sh = client.open("Investment_Dashboard_DB")
    
    df_trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
    df_exchange = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
    df_dividend = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
    
    # 컬럼명 공백 제거
    for df in [df_trade, df_exchange, df_dividend]:
        df.columns = df.columns.str.strip()
        
    return df_trade, df_exchange, df_dividend, sh

# -------------------------------------------------------------------
# [3] 달러 저수지 엔진 (Logic)
# -------------------------------------------------------------------
def calculate_metrics(df_trade, df_exchange, df_dividend):
    # 1. 환율 및 잔고 계산 (저수지 모델)
    events = []
    
    # 환전
    for _, row in df_exchange.iterrows():
        usd = safe_float(get_col(row, ['USD_Amount', 'USD']))
        rate = safe_float(get_col(row, ['Ex_Rate', 'Rate']))
        events.append({'date': str(row['Date']), 'type': 'EXCHANGE', 'usd': usd, 'rate': rate})
        
    # 배당
    for _, row in df_dividend.iterrows():
        usd = safe_float(get_col(row, ['Amount_USD', 'Amount']))
        events.append({'date': str(row['Date']), 'type': 'DIVIDEND', 'usd': usd, 'rate': 0.0}) # 0원 입금
        
    # 매매
    for _, row in df_trade.iterrows():
        qty = safe_float(get_col(row, ['Qty']))
        price = safe_float(get_col(row, ['Price_USD', 'Price']))
        amt = qty * price
        t_type = str(row['Type']).lower()
        if 'buy' in t_type or '매수' in t_type:
            events.append({'date': str(row['Date']), 'type': 'BUY', 'usd': -amt})
        elif 'sell' in t_type or '매도' in t_type:
            events.append({'date': str(row['Date']), 'type': 'SELL', 'usd': amt})
            
    events.sort(key=lambda x: x['date'])
    
    reservoir_usd = 0.0
    avg_rate = 0.0
    total_invested_krw = 0.0
    rate_history = {} # 날짜별 평단환율 (API 매핑용)

    for e in events:
        if e['type'] == 'EXCHANGE':
            prev_krw = reservoir_usd * avg_rate
            new_krw = e['usd'] * e['rate']
            if reservoir_usd + e['usd'] > 0:
                avg_rate = (prev_krw + new_krw) / (reservoir_usd + e['usd'])
            reservoir_usd += e['usd']
            total_invested_krw += new_krw
            
        elif e['type'] == 'DIVIDEND':
            prev_krw = reservoir_usd * avg_rate
            if reservoir_usd + e['usd'] > 0:
                avg_rate = prev_krw / (reservoir_usd + e['usd'])
            reservoir_usd += e['usd']
            
        elif e['type'] in ['BUY', 'SELL']:
            reservoir_usd += e['usd']
            
        rate_history[e['date']] = avg_rate

    # 2. 종목별 평단가 계산 (FIFO 아님, 이동평균)
    portfolio = {}
    for _, row in df_trade.iterrows():
        tk = row['Ticker']
        qty = safe_float(get_col(row, ['Qty']))
        price = safe_float(get_col(row, ['Price_USD']))
        t_type = str(row['Type']).lower()
        
        if tk not in portfolio: portfolio[tk] = {'qty': 0.0, 'invested': 0.0, 'avg': 0.0}
        
        if 'buy' in t_type or '매수' in t_type:
            portfolio[tk]['invested'] += (qty * price)
            portfolio[tk]['qty'] += qty
        elif 'sell' in t_type or '매도' in t_type:
            # 매도시 평단 유지, 수량/금액 감소
            if portfolio[tk]['qty'] > 0:
                avg = portfolio[tk]['invested'] / portfolio[tk]['qty']
                portfolio[tk]['qty'] -= qty
                portfolio[tk]['invested'] -= (qty * avg)
                
    # 평단가 최종 계산
    for tk in portfolio:
        if portfolio[tk]['qty'] > 0:
            portfolio[tk]['avg'] = portfolio[tk]['invested'] / portfolio[tk]['qty']
        else:
            portfolio[tk]['avg'] = 0.0
            
    return reservoir_usd, avg_rate, total_invested_krw, portfolio, rate_history

# -------------------------------------------------------------------
# [4] HTML 생성기 (UI Components)
# -------------------------------------------------------------------
def make_kpi_html(label, value, sub):
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>
    """

def make_card_html(ticker, qty, avg_price, cur_price, avg_rate, bep_rate):
    if qty <= 0: return ""
    
    val_usd = qty * cur_price
    # 손익 (달러 기준)
    pl_usd = (cur_price - avg_price) * qty
    pl_rate = ((cur_price - avg_price) / avg_price * 100) if avg_price > 0 else 0
    
    # 안전마진 (환율)
    margin = avg_rate - bep_rate # 내 평단환율 - BEP환율? or 현재환율 - BEP?
    # 보통 안전마진 = 현재환율 - BEP환율 (지금 환전해도 이득인가?)
    # 여기서는 PM님 공식: 현재환율(실시간X, 저수지평단) - BEP
    
    color_cls = "card-up" if pl_usd >= 0 else "card-down"
    price_cls = "price-up" if pl_usd >= 0 else "price-down"
    arrow = "▲" if pl_usd >= 0 else "▼"
    
    return f"""
    <div class="stock-card {color_cls}">
        <div class="card-header">
            <span class="card-ticker">{ticker}</span>
            <span class="card-price {price_cls}">${cur_price:.2f}</span>
        </div>
        <div class="card-body">
            <div class="card-row">
                <span>보유수량</span><span>{qty:,.0f}주</span>
            </div>
            <div class="card-row">
                <span>평단가</span><span>${avg_price:.2f}</span>
            </div>
            <div class="card-row">
                <span>평가손익</span><span class="{price_cls}">{arrow} ${pl_usd:,.2f} ({pl_rate:.1f}%)</span>
            </div>
            <div class="card-row" style="margin-top:5px; border-top:1px solid #444; padding-top:5px;">
                <span>평가금액</span><span>${val_usd:,.2f}</span>
            </div>
        </div>
    </div>
    """

def make_table_html(df):
    html = '<table class="custom-table"><thead><tr><th>Date</th><th>Type</th><th>Ticker</th><th>Qty</th><th>Price</th><th>Amount</th></tr></thead><tbody>'
    for _, row in df.iterrows():
        t_type = str(row.get('Type', '')).lower()
        date = row.get('Date', '')
        ticker = row.get('Ticker', '')
        qty = row.get('Qty', '')
        price = row.get('Price_USD', '')
        
        row_cls = ""
        badge = ""
        if 'buy' in t_type: 
            row_cls = "row-buy"
            badge = '<span class="badge bg-red">BUY</span>'
        elif 'sell' in t_type: 
            row_cls = "row-sell"
            badge = '<span class="badge bg-blue">SELL</span>'
        elif 'div' in t_type: 
            row_cls = "row-div"
            badge = '<span class="badge" style="background:#28a745;color:white">DIV</span>'
            
        html += f'<tr class="{row_cls}"><td>{date}</td><td>{badge}</td><td>{ticker}</td><td>{qty}</td><td>${price}</td><td>-</td></tr>'
    html += '</tbody></table>'
    return html

# -------------------------------------------------------------------
# [5] 메인 앱
# -------------------------------------------------------------------
def main():
    # A. 데이터 로드
    try:
        df_trade, df_exchange, df_dividend, sheet_instance = load_data()
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        st.stop()
        
    # B. 계산 엔진 가동
    reservoir_usd, reservoir_rate, total_invested_krw, portfolio, rate_history = calculate_metrics(df_trade, df_exchange, df_dividend)
    
    # C. 현재가 가져오기 (API)
    all_tickers = list(portfolio.keys())
    prices = {}
    total_stock_val_usd = 0.0
    
    # (API 속도 위해 루프)
    with st.spinner("시장 데이터 수신 중..."):
        for tk in all_tickers:
            if portfolio[tk]['qty'] > 0:
                price = kis.get_current_price(tk)
                prices[tk] = price
                total_stock_val_usd += (portfolio[tk]['qty'] * price)
    
    # D. 전체 자산 계산
    total_asset_usd = total_stock_val_usd + reservoir_usd
    bep_rate = total_invested_krw / total_asset_usd if total_asset_usd > 0 else 0
    margin = reservoir_rate - bep_rate

    # --- UI RENDERING ---
    
    # 1. Header & Sync
    c1, c2 = st.columns([3, 1])
    c1.title("Investment Dashboard")
    with c2:
        st.write("") # Spacer
        if st.button("🔄 API Sync (1/18~)", use_container_width=True):
            from Dashboard import sync_api_data # 순환참조 방지 (함수는 아래 정의)
            sync_api_data(sheet_instance, df_trade, rate_history)

    # 2. KPI Cube
    kpi_html = f"""
    <div class="kpi-grid">
        {make_kpi_html("총 자산 (USD)", f"${total_asset_usd:,.0f}", f"≈ ₩{total_asset_usd*1450/100000000:.2f}억")}
        {make_kpi_html("달러 저수지", f"${reservoir_usd:,.0f}", f"평단: ₩{reservoir_rate:.2f}")}
        {make_kpi_html("BEP 환율", f"₩{bep_rate:.2f}", f"안전마진: {margin:+.2f}")}
        {make_kpi_html("주식 평가액", f"${total_stock_val_usd:,.0f}", f"{len(prices)} 종목 보유")}
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)
    
    # 3. Main View (Tabs)
    tab1, tab2, tab3, tab4 = st.tabs(["💳 카드 현황", "📜 통합 로그", "📊 세부 내역", "⚙️ 설정"])
    
    with tab1:
        # 섹터 필터
        sectors = ["전체", "반도체", "배당", "빅테크", "리츠"]
        sec_choice = st.radio("섹터 선택", sectors, horizontal=True, label_visibility="collapsed")
        
        st.write("---")
        card_cols = st.columns(4) # 4열 배치
        idx = 0
        
        for tk, data in portfolio.items():
            qty = data['qty']
            if qty <= 0: continue
            
            my_sec = SECTOR_MAP.get(tk, "기타")
            if sec_choice != "전체" and sec_choice != my_sec: continue
            
            html = make_card_html(tk, qty, data['avg'], prices.get(tk, 0), reservoir_rate, bep_rate)
            with card_cols[idx % 4]:
                st.markdown(html, unsafe_allow_html=True)
            idx += 1
            
    with tab2:
        # 통합 테이블 (구버전 스타일 HTML)
        # Trade Log + Dividend Log + Exchange Log 합쳐서 시간순 정렬 필요하지만
        # 일단 Trade Log 만이라도 이쁘게 보여줌
        st.markdown(make_table_html(df_trade.sort_values('Date', ascending=False)), unsafe_allow_html=True)
        
    with tab3:
        st.dataframe(df_trade)
        st.dataframe(df_exchange)

# -------------------------------------------------------------------
# [6] Sync Logic (함수 분리)
# -------------------------------------------------------------------
def sync_api_data(sh, df_trade, rate_history):
    ws = sh.worksheet("Trade_Log")
    last_date = pd.to_datetime(df_trade['Date']).max() if not df_trade.empty else datetime(2026,1,1)
    start_str = last_date.strftime("%Y%m%d")
    end_str = datetime.now().strftime("%Y%m%d")
    
    res = kis.get_trade_history(start_str, end_str)
    if not res: return
    
    api_list = res.get('output1', [])
    if not api_list: 
        st.toast("최신 내역이 없습니다.")
        return
        
    new_rows = []
    # 중복 방지 로직 (기존 키: 날짜_종목_수량)
    keys = set(f"{r['Date']}_{r['Ticker']}_{safe_float(r['Qty'])}" for _, r in df_trade.iterrows())
    
    for item in reversed(api_list):
        dt = datetime.strptime(item['dt'], "%Y%m%d").strftime("%Y-%m-%d")
        tk = item['pdno']
        qty = int(item['ccld_qty'])
        side = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
        price = float(item['ft_ccld_unpr3'])
        
        if f"{dt}_{tk}_{float(qty)}" in keys: continue
        
        # 환율 매핑
        app_rate = 0.0
        if side == "Buy":
            dates = sorted([d for d in rate_history if d <= dt])
            if dates: app_rate = rate_history[dates[-1]]
            
        new_rows.append([
            dt, f"API_{item['odno']}", tk, item['prdt_name'], side, qty, price, f"{app_rate:.8f}", "API_Auto"
        ])
        
    if new_rows:
        ws.append_rows(new_rows)
        st.success(f"{len(new_rows)}건 업데이트 완료")
        time.sleep(1)
        st.rerun()

if __name__ == "__main__":
    main()
