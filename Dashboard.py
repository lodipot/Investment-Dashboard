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
    .badge-semi { background-color: #E3F2FD; color: #1565C0; }
    .badge-div { background-color: #E8F5E9; color: #2E7D32; }
    .badge-tech { background-color: #F3E5F5; color: #7B1FA2; }
</style>
""", unsafe_allow_html=True)

# 섹터 정의 (하드코딩 - 유지보수 용이)
SECTOR_MAP = {
    'NVDA': '반도체', 'AMD': '반도체', 'TSM': '반도체', 'AVGO': '반도체', 'SOXL': '반도체',
    'O': '배당', 'KO': '배당', 'SCHD': '배당', 'JEPQ': '배당', 'JEPI': '배당', 'MAIN': '배당',
    'MSFT': '빅테크', 'GOOGL': '빅테크', 'AAPL': '빅테크', 'AMZN': '빅테크', 'TSLA': '빅테크',
    'PLD': '리츠', 'AMT': '리츠'
}

# -------------------------------------------------------------------
# 2. 데이터 로딩 및 DB 연결
# -------------------------------------------------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def load_data():
    client = get_gsheet_client()
    sh = client.open("Investment_Dashboard_DB") # DB 파일명 확인
    
    # DataFrame으로 로드
    df_trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
    df_exchange = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
    df_dividend = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
    
    return df_trade, df_exchange, df_dividend, sh

# -------------------------------------------------------------------
# 3. [핵심 엔진] 달러 저수지 로직 (환율 재계산)
# -------------------------------------------------------------------
def calculate_reservoir(df_trade, df_exchange, df_dividend):
    """
    모든 거래 내역을 시간순으로 재구성하여
    현재 시점의 '달러 잔고'와 '이동평균 환율'을 산출한다.
    """
    # 1. 모든 이벤트를 하나의 타임라인으로 통합
    events = []
    
    # 환전 (입금)
    for _, row in df_exchange.iterrows():
        events.append({
            'date': row['Date'], 'type': 'EXCHANGE', 
            'usd': float(str(row['USD_Amount']).replace(',','')),
            'rate': float(str(row['Ex_Rate']).replace(',','')),
            'krw': float(str(row['KRW_Amount']).replace(',',''))
        })
        
    # 배당 (입금 - 환율 희석)
    for _, row in df_dividend.iterrows():
        events.append({
            'date': row['Date'], 'type': 'DIVIDEND', 
            'usd': float(str(row['Amount_USD']).replace(',','')),
            'rate': 0.0, # 배당은 0원 환율 취급
            'krw': 0.0
        })
        
    # 매매 (출금/입금 - 환율 유지)
    for _, row in df_trade.iterrows():
        qty = float(str(row['Qty']).replace(',',''))
        price = float(str(row['Price_USD']).replace(',',''))
        amt = qty * price
        
        # API 매수 데이터 등에서 Type 텍스트 정규화
        tr_type = row['Type'].lower()
        
        if 'buy' in tr_type or '매수' in tr_type:
            events.append({'date': row['Date'], 'type': 'BUY', 'usd': -amt})
        elif 'sell' in tr_type or '매도' in tr_type:
            events.append({'date': row['Date'], 'type': 'SELL', 'usd': amt})

    # 2. 시간순 정렬
    events.sort(key=lambda x: x['date'])
    
    # 3. 순차 계산
    current_usd_balance = 0.0
    current_avg_rate = 0.0
    
    # 날짜별 환율 맵 (매수 시 참조용)
    rate_history = {} 

    for event in events:
        if event['type'] == 'EXCHANGE':
            # 가중평균: (기존잔고*기존환율 + 신규잔고*신규환율) / 합계잔고
            if current_usd_balance + event['usd'] > 0:
                current_avg_rate = ((current_usd_balance * current_avg_rate) + (event['usd'] * event['rate'])) / (current_usd_balance + event['usd'])
            current_usd_balance += event['usd']
            
        elif event['type'] == 'DIVIDEND':
            # 배당금: 0원 환율로 입금 -> 환율 희석 효과 (안전마진 확보)
            if current_usd_balance + event['usd'] > 0:
                current_avg_rate = ((current_usd_balance * current_avg_rate) + (event['usd'] * 0)) / (current_usd_balance + event['usd'])
            current_usd_balance += event['usd']
            
        elif event['type'] == 'BUY':
            # 매수: 달러 잔고 감소, 평단 환율은 유지
            current_usd_balance += event['usd'] # event['usd'] is negative
            
        elif event['type'] == 'SELL':
            # 매도: 달러 잔고 증가, 평단 환율 유지 (재투자 목적)
            current_usd_balance += event['usd']
            
        # 해당 날짜의 최종 환율 기록
        rate_history[event['date']] = current_avg_rate

    return current_usd_balance, current_avg_rate, rate_history

# -------------------------------------------------------------------
# 4. API 동기화 및 DB 업데이트 (Sync Logic)
# -------------------------------------------------------------------
def sync_api_data(sh, df_trade, rate_history):
    ws = sh.worksheet("Trade_Log")
    
    # 1. DB의 마지막 날짜 확인
    if not df_trade.empty:
        last_db_date_str = str(df_trade['Date'].max())
        last_db_date = datetime.strptime(last_db_date_str, "%Y-%m-%d")
        start_date_str = (last_db_date + timedelta(days=0)).strftime("%Y%m%d") # 당일 포함 검색 (중복제거 로직 믿고)
    else:
        start_date_str = "20260101" # Default
        
    end_date_str = datetime.now().strftime("%Y%m%d")
    
    # 2. API 호출
    with st.spinner(f"KIS API 연결 중... ({start_date_str} ~ {end_date_str})"):
        res = kis.get_trade_history(start_date_str, end_date_str)
        
    if not res or res['rt_cd'] != '0':
        st.error("API 데이터 조회 실패")
        return

    api_trades = res['output1']
    if not api_trades:
        st.info("기간 내 신규 체결 내역이 없습니다.")
        return

    # 3. 중복 검사 및 신규 데이터 필터링
    # DB에 있는 고유 키 생성 (날짜_종목_구분_수량_가격)
    existing_keys = set()
    for _, row in df_trade.iterrows():
        key = f"{row['Date']}_{row['Ticker']}_{row['Type']}_{row['Qty']}_{float(str(row['Price_USD']).replace(',','')):.4f}"
        existing_keys.add(key)
        
    new_rows = []
    # API 데이터는 역순(최신순)으로 옴 -> 정순으로 변경
    for item in reversed(api_trades):
        # 파싱
        trade_date = datetime.strptime(item['dt'], "%Y%m%d").strftime("%Y-%m-%d")
        ticker = item['pdno'] # 종목코드
        name = item['prdt_name']
        side = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
        qty = int(item['ccld_qty'])
        price = float(item['ft_ccld_unpr3']) # 외화단가
        
        # 키 생성 및 중복 확인
        key = f"{trade_date}_{ticker}_{side}_{qty}_{price:.4f}"
        if key in existing_keys:
            continue # 이미 DB에 있음
            
        # 4. 환율 매핑 (달러 저수지 로직 적용)
        # 매수 시점: 해당 날짜의 reservoir Avg_Rate를 적용
        # 해당 날짜에 기록이 없으면, 가장 최근 과거 환율을 가져옴
        applied_rate = 0.0
        if side == "Buy":
            # rate_history에서 날짜 찾기 (없으면 직전 날짜)
            dates = sorted(rate_history.keys())
            target_rate = 0.0
            for d in dates:
                if d <= trade_date:
                    target_rate = rate_history[d]
                else:
                    break
            applied_rate = target_rate
        else:
            # 매도 시: 매수 당시 평단가를 추적하는건 복잡하므로 0 or 단순 표기
            applied_rate = 0.0 # 매도 시 환율은 수익률 계산용으로 필요하지만, Reservoir 로직엔 영향 없음

        # 새 행 추가
        new_row = [
            trade_date,
            f"API_{item['odno']}", # Order ID 대체
            ticker,
            name,
            side,
            qty,
            price,
            f"{applied_rate:.8f}", # 정밀도 유지
            "API_Sync"
        ]
        new_rows.append(new_row)
        
    # 5. 구글 시트에 Append
    if new_rows:
        ws.append_rows(new_rows)
        st.success(f"✅ {len(new_rows)}건의 신규 거래내역을 동기화했습니다!")
        time.sleep(1)
        st.rerun() # 새로고침
    else:
        st.info("최신 상태입니다. 추가할 내역이 없습니다.")

# -------------------------------------------------------------------
# 5. 메인 앱 실행
# -------------------------------------------------------------------
def main():
    # A. 데이터 로드
    try:
        df_trade, df_exchange, df_dividend, sheet_instance = load_data()
    except Exception as e:
        st.error(f"DB 연결 오류: {e}")
        st.stop()
        
    # B. 엔진 가동 (환율 재계산)
    reservoir_usd, reservoir_rate, rate_history = calculate_reservoir(df_trade, df_exchange, df_dividend)
    
    # C. 사이드바 / 헤더
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.title("🚀 US Stock Investment Dashboard")
    with col_h2:
        # 상태 배지
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        st.markdown(f"**Status:** `🟢 Live` ({now_str})")
        if st.button("🔄 API Sync"):
            sync_api_data(sheet_instance, df_trade, rate_history)

    # D. KPI Cube (상단)
    # 현재 보유 주식 평가액 계산
    # (실제로는 Trade Log에서 매수-매도 수량을 계산하고, 현재가를 API로 가져와야 함)
    # 여기서는 간소화하여 Trade Log 기반 수량 집계 -> 현재가 조회
    
    # 보유 종목 집계
    holdings = {}
    for _, row in df_trade.iterrows():
        tk = row['Ticker']
        qty = float(str(row['Qty']).replace(',',''))
        if row['Type'] == 'Buy':
            holdings[tk] = holdings.get(tk, 0) + qty
        elif row['Type'] == 'Sell':
            holdings[tk] = holdings.get(tk, 0) - qty
            
    # 평가액 계산
    total_stock_val_usd = 0.0
    for tk, qty in holdings.items():
        if qty > 0:
            cur_price = kis.get_current_price(tk) # 현재가 API 호출
            total_stock_val_usd += (qty * cur_price)
            
    total_asset_usd = total_stock_val_usd + reservoir_usd
    total_asset_krw_real = total_asset_usd * 1450 # 임시: 실시간 환율 API 필요시 추가
    total_invested_krw = df_exchange['KRW_Amount'].astype(str).str.replace(',','').astype(float).sum() # 총 투입 원화 (환전 기준)
    
    # 안전마진 (BEP 환율) = 총투입원화 / 현재 달러 총자산
    bep_rate = total_invested_krw / total_asset_usd if total_asset_usd > 0 else 0
    margin_safety = reservoir_rate - bep_rate # 이게 +여야 좋음 (현재 평단이 BEP보다 낮아야... 아 반대인가? BEP가 낮을수록 좋음)
    # BEP 환율: 내가 이 환율 밑으로만 환전해서 탈출하면 본전이다.
    # 즉, 현재 환율 > BEP 환율이면 이득. 
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("총 자산 (USD)", f"${total_asset_usd:,.2f}", f"Cash: ${reservoir_usd:,.2f}")
    with col2:
        st.metric("이동평균 환율 (Avg)", f"₩{reservoir_rate:,.2f}", "저수지 평단")
    with col3:
        st.metric("BEP 환율 (안전마진)", f"₩{bep_rate:,.2f}", f"Margin: {1450 - bep_rate:,.2f}") 
    with col4:
        roi = ((total_asset_usd * 1450) - total_invested_krw) / total_invested_krw * 100
        st.metric("추정 수익률 (KRW)", f"{roi:.2f}%", f"₩{total_asset_krw_real - total_invested_krw:,.0f}")

    st.divider()

    # E. 섹터별 카드 뷰 (UI)
    tabs = st.tabs(["전체", "💾 반도체", "💰 배당", "☁️ 빅테크", "🏙️ 리츠", "💵 현금"])
    
    with tabs[0]: # 전체
        st.dataframe(df_trade.sort_values(by='Date', ascending=False), use_container_width=True)
        
    # 섹터별 필터링 로직 (간단 구현)
    for i, sector_name in enumerate(["반도체", "배당", "빅테크", "리츠"]):
        with tabs[i+1]:
            cols = st.columns(3)
            idx = 0
            for tk, qty in holdings.items():
                if qty > 0 and SECTOR_MAP.get(tk) == sector_name:
                    cur_p = kis.get_current_price(tk)
                    val = qty * cur_p
                    with cols[idx % 3]:
                        st.markdown(f"""
                        <div class="metric-card">
                            <div class="metric-title">{tk}</div>
                            <div class="metric-value">${cur_p:.2f}</div>
                            <div class="metric-sub">보유: {qty}주 | 평가: ${val:,.0f}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    idx += 1
    
    with tabs[5]: # 현금
        st.info("달러 저수지 현황")
        st.metric("보유 달러", f"${reservoir_usd:,.2f}")
        st.dataframe(df_exchange.sort_values(by='Date', ascending=False))
        st.write("최근 배당 내역")
        st.dataframe(df_dividend.sort_values(by='Date', ascending=False))

if __name__ == "__main__":
    main()
