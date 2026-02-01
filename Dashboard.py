import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# 1. 초기 설정 및 스타일
# -------------------------------------------------------------------
st.set_page_config(page_title="Dollar Reservoir Dashboard", layout="wide", page_icon="🏦")

st.markdown("""
<style>
    .metric-card {
        background-color: #1E1E1E;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #333;
        margin-bottom: 10px;
    }
    .metric-title { color: #AAAAAA; font-size: 0.9rem; }
    .metric-value { color: #FFFFFF; font-size: 1.5rem; font-weight: bold; }
    .metric-sub { color: #4CAF50; font-size: 0.8rem; }
    .sector-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: bold;
        margin-right: 5px;
    }
</style>
""", unsafe_allow_html=True)

# 섹터 정의
SECTOR_MAP = {
    'NVDA': '반도체', 'AMD': '반도체', 'TSM': '반도체', 'AVGO': '반도체', 'SOXL': '반도체',
    'O': '배당', 'KO': '배당', 'SCHD': '배당', 'JEPQ': '배당', 'JEPI': '배당', 'MAIN': '배당',
    'MSFT': '빅테크', 'GOOGL': '빅테크', 'AAPL': '빅테크', 'AMZN': '빅테크', 'TSLA': '빅테크',
    'PLD': '리츠', 'AMT': '리츠'
}

# -------------------------------------------------------------------
# 2. 데이터 로딩 및 전처리 (Robust)
# -------------------------------------------------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def safe_float(val):
    """문자열/숫자를 안전하게 float로 변환 (콤마 제거)"""
    if pd.isna(val) or val == '':
        return 0.0
    try:
        return float(str(val).replace(',', '').strip())
    except:
        return 0.0

def get_col_val(row, candidates):
    """여러 컬럼 이름 후보 중 존재하는 값을 반환"""
    for col in candidates:
        if col in row:
            return safe_float(row[col])
        if col.replace('_', ' ') in row: # USD Amount 대응
            return safe_float(row[col.replace('_', ' ')])
    return 0.0

def load_data():
    client = get_gsheet_client()
    sh = client.open("Investment_Dashboard_DB")
    
    # 데이터 로드 (헤더 공백 제거 처리)
    df_trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
    df_exchange = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
    df_dividend = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
    
    # 컬럼명 공백 제거 (방어 코드)
    df_trade.columns = df_trade.columns.str.strip()
    df_exchange.columns = df_exchange.columns.str.strip()
    df_dividend.columns = df_dividend.columns.str.strip()
    
    return df_trade, df_exchange, df_dividend, sh

# -------------------------------------------------------------------
# 3. [핵심 엔진] 달러 저수지 로직 (환율 재계산)
# -------------------------------------------------------------------
def calculate_reservoir(df_trade, df_exchange, df_dividend):
    events = []
    
    # 1. 환전 (입금) - 컬럼명 유연 대응
    for _, row in df_exchange.iterrows():
        usd = get_col_val(row, ['USD_Amount', 'Amount_USD', 'USD'])
        rate = get_col_val(row, ['Ex_Rate', 'Rate', 'Exchange_Rate'])
        
        events.append({
            'date': str(row['Date']), 
            'type': 'EXCHANGE', 
            'usd': usd,
            'rate': rate
        })
        
    # 2. 배당 (입금 - 환율 희석)
    for _, row in df_dividend.iterrows():
        usd = get_col_val(row, ['Amount_USD', 'Amount', 'Dividend_Amount'])
        
        events.append({
            'date': str(row['Date']), 
            'type': 'DIVIDEND', 
            'usd': usd,
            'rate': 0.0 # 배당은 0원 입금 취급
        })
        
    # 3. 매매 (출금/입금 - 환율 유지)
    for _, row in df_trade.iterrows():
        qty = get_col_val(row, ['Qty', 'Quantity'])
        price = get_col_val(row, ['Price_USD', 'Price', 'Unit_Price'])
        amt = qty * price
        
        tr_type = str(row['Type']).lower()
        if 'buy' in tr_type or '매수' in tr_type:
            events.append({'date': str(row['Date']), 'type': 'BUY', 'usd': -amt})
        elif 'sell' in tr_type or '매도' in tr_type:
            events.append({'date': str(row['Date']), 'type': 'SELL', 'usd': amt})

    # 시간순 정렬
    events.sort(key=lambda x: x['date'])
    
    # 순차 계산
    current_usd_balance = 0.0
    current_avg_rate = 0.0
    total_invested_krw = 0.0 # 총 원화 투입금
    
    rate_history = {} 

    for event in events:
        if event['type'] == 'EXCHANGE':
            # 평단가 재계산: (기존총액 + 신규총액) / (기존잔고 + 신규잔고)
            prev_krw_val = current_usd_balance * current_avg_rate
            new_krw_val = event['usd'] * event['rate']
            
            if current_usd_balance + event['usd'] > 0:
                current_avg_rate = (prev_krw_val + new_krw_val) / (current_usd_balance + event['usd'])
            
            current_usd_balance += event['usd']
            total_invested_krw += new_krw_val
            
        elif event['type'] == 'DIVIDEND':
            # 배당: 원화가치 0원인 달러 추가 -> 평단가 하락 희석
            prev_krw_val = current_usd_balance * current_avg_rate
            if current_usd_balance + event['usd'] > 0:
                current_avg_rate = prev_krw_val / (current_usd_balance + event['usd'])
            
            current_usd_balance += event['usd']
            
        elif event['type'] == 'BUY':
            current_usd_balance += event['usd'] # 잔고 감소, 환율 유지
            
        elif event['type'] == 'SELL':
            current_usd_balance += event['usd'] # 잔고 증가, 환율 유지 (재투자용)
            
        rate_history[event['date']] = current_avg_rate

    return current_usd_balance, current_avg_rate, rate_history, total_invested_krw

# -------------------------------------------------------------------
# 4. API 동기화 및 DB 업데이트
# -------------------------------------------------------------------
def sync_api_data(sh, df_trade, rate_history):
    ws = sh.worksheet("Trade_Log")
    
    # 마지막 날짜 확인
    if not df_trade.empty:
        last_date = pd.to_datetime(df_trade['Date']).max()
        start_date_str = last_date.strftime("%Y%m%d")
    else:
        start_date_str = "20260101"
        
    end_date_str = datetime.now().strftime("%Y%m%d")
    
    with st.spinner(f"KIS API 동기화 중... ({start_date_str} ~ {end_date_str})"):
        res = kis.get_trade_history(start_date_str, end_date_str)
        
    if not res or res['rt_cd'] != '0':
        st.error(f"API 호출 실패: {res.get('msg1', 'Unknown Error')}")
        return

    api_trades = res['output1']
    if not api_trades:
        st.info("추가할 신규 내역이 없습니다.")
        return

    # 중복 체크 키 생성
    existing_keys = set()
    for _, row in df_trade.iterrows():
        key = f"{row['Date']}_{row['Ticker']}_{row['Type']}_{get_col_val(row, ['Qty'])}"
        existing_keys.add(key)
        
    new_rows = []
    for item in reversed(api_trades): # 과거순 정렬
        t_date = datetime.strptime(item['dt'], "%Y%m%d").strftime("%Y-%m-%d")
        ticker = item['pdno']
        side = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
        qty = int(item['ccld_qty'])
        price = float(item['ft_ccld_unpr3'])
        
        # 키 검사
        key = f"{t_date}_{ticker}_{side}_{qty}"
        if key in existing_keys: continue
            
        # 환율 매핑
        applied_rate = 0.0
        if side == "Buy":
            # 해당 날짜의 저수지 환율 찾기
            dates = sorted([d for d in rate_history.keys() if d <= t_date])
            if dates:
                applied_rate = rate_history[dates[-1]]
                
        new_rows.append([
            t_date, f"API_{item['odno']}", ticker, item['prdt_name'], side, qty, price, f"{applied_rate:.8f}", "API_Auto"
        ])
        
    if new_rows:
        ws.append_rows(new_rows)
        st.success(f"✅ {len(new_rows)}건 업데이트 완료!")
        time.sleep(1)
        st.rerun()
    else:
        st.info("이미 최신 상태입니다.")

# -------------------------------------------------------------------
# 5. 메인 앱 실행
# -------------------------------------------------------------------
def main():
    try:
        df_trade, df_exchange, df_dividend, sheet_instance = load_data()
    except Exception as e:
        st.error(f"데이터 로드 중 치명적 오류: {e}")
        st.stop()
        
    # 엔진 가동
    reservoir_usd, reservoir_rate, rate_history, total_invested_krw = calculate_reservoir(df_trade, df_exchange, df_dividend)
    
    # 레이아웃
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1: st.title("🚀 US Stock Investment Dashboard")
    with col_h2:
        if st.button("🔄 API Sync"):
            sync_api_data(sheet_instance, df_trade, rate_history)

    # 평가액 계산
    holdings = {}
    for _, row in df_trade.iterrows():
        tk = row['Ticker']
        qty = get_col_val(row, ['Qty'])
        if row['Type'] == 'Buy': holdings[tk] = holdings.get(tk, 0) + qty
        elif row['Type'] == 'Sell': holdings[tk] = holdings.get(tk, 0) - qty
            
    total_stock_val_usd = 0.0
    for tk, qty in holdings.items():
        if qty > 0:
            price = kis.get_current_price(tk)
            total_stock_val_usd += (qty * price)
            
    total_asset_usd = total_stock_val_usd + reservoir_usd
    
    # KPI
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 자산 (USD)", f"${total_asset_usd:,.2f}")
    col2.metric("보유 현금 (USD)", f"${reservoir_usd:,.2f}")
    col3.metric("이동평균 환율", f"₩{reservoir_rate:,.2f}")
    
    # 안전마진 (BEP 환율)
    bep_rate = total_invested_krw / total_asset_usd if total_asset_usd > 0 else 0
    margin = 1450 - bep_rate # 현재 환율 1450 가정
    col4.metric("BEP 환율 (안전마진)", f"₩{bep_rate:,.2f}", f"여유: {margin:,.2f}원")

    st.divider()
    
    # 탭 뷰
    tabs = st.tabs(["전체 내역", "반도체", "배당", "빅테크", "리츠"])
    
    with tabs[0]:
        st.dataframe(df_trade.sort_values('Date', ascending=False), use_container_width=True)
        
    for i, sec in enumerate(["반도체", "배당", "빅테크", "리츠"]):
        with tabs[i+1]:
            cols = st.columns(3)
            idx = 0
            for tk, qty in holdings.items():
                if qty > 0 and SECTOR_MAP.get(tk) == sec:
                    cur_p = kis.get_current_price(tk)
                    val = qty * cur_p
                    with cols[idx%3]:
                        st.markdown(f"""
                        <div class="metric-card">
                            <div class="metric-title">{tk}</div>
                            <div class="metric-value">${cur_p:.2f}</div>
                            <div class="metric-sub">보유: {qty} | 평가: ${val:,.0f}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    idx+=1

if __name__ == "__main__":
    main()
