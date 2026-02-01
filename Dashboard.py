import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import yfinance as yf
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# [1] 설정 & 스타일
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="🏦")

st.markdown("""
<style>
    /* KPI Grid */
    .kpi-container {
        display: grid;
        grid-template-columns: 2fr 1.5fr 1.5fr;
        gap: 15px;
        margin-bottom: 20px;
    }
    .kpi-card {
        background-color: #1E1E1E;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #333;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .kpi-title { font-size: 1rem; color: #AAAAAA; margin-bottom: 5px; }
    .kpi-main { font-size: 2rem; font-weight: bold; color: #FFFFFF; }
    .kpi-sub { font-size: 1rem; margin-top: 5px; font-weight: 500; }
    .kpi-red { color: #FF5252; }
    .kpi-blue { color: #448AFF; }
    
    /* Stock Card */
    .stock-card {
        background-color: #262626;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 15px;
        border-left: 5px solid #555;
    }
    .card-up { border-left-color: #FF5252 !important; }
    .card-down { border-left-color: #448AFF !important; }
    
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .card-ticker { font-size: 1.3rem; font-weight: 800; color: #FFF; }
    .card-price { font-size: 1.1rem; font-weight: bold; }
    
    .card-body { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.9rem; color: #DDD; }
    .card-row { display: flex; justify-content: space-between; }
    .card-label { color: #888; }
</style>
""", unsafe_allow_html=True)

# 섹터 및 순서 정의
SECTOR_ORDER = {
    '배당': ['O', 'JEPI', 'JEPQ', 'SCHD', 'MAIN', 'KO'],
    '테크': ['GOOGL', 'NVDA', 'AMD', 'TSM', 'MSFT', 'AAPL', 'AMZN', 'TSLA', 'AVGO', 'SOXL'],
    '리츠': ['PLD', 'AMT'],
    '기타': []
}

# -------------------------------------------------------------------
# [2] 데이터 로드 및 유틸리티
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

def load_data():
    client = get_gsheet_client()
    sh = client.open("Investment_Dashboard_DB")
    # Money_Log 통합 (Exchange + Dividend)
    df_money = pd.DataFrame(sh.worksheet("Money_Log").get_all_records())
    df_trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
    
    # 공백 제거
    df_money.columns = df_money.columns.str.strip()
    df_trade.columns = df_trade.columns.str.strip()
    
    return df_trade, df_money, sh

def get_realtime_rate():
    try:
        ticker = yf.Ticker("KRW=X")
        data = ticker.history(period="1d")
        if not data.empty:
            return data['Close'].iloc[-1]
    except:
        pass
    return 1450.0

# -------------------------------------------------------------------
# [3] 달러 저수지 엔진 (Fill-Forward Logic)
# -------------------------------------------------------------------
def process_timeline(df_trade, df_money, sheet_instance):
    """
    모든 거래를 Order_ID 순으로 나열하고, 
    빈칸(Rate, Balance)을 순차적으로 계산하여 채움
    """
    # 1. 타임라인 병합
    df_money['Source'] = 'Money'
    df_trade['Source'] = 'Trade'
    
    # 필수 컬럼 확보
    if 'Order_ID' not in df_money.columns: df_money['Order_ID'] = 0
    if 'Order_ID' not in df_trade.columns: df_trade['Order_ID'] = 0
    
    # 병합
    timeline = pd.concat([df_money, df_trade], ignore_index=True)
    # Order_ID가 숫자인지 확인 후 정렬
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    timeline = timeline.sort_values(by=['Order_ID', 'Date'])
    
    # 2. 순차 계산 (State Machine)
    current_balance = 0.0
    current_avg_rate = 0.0
    total_krw_invested = 0.0 # 원화 투입 총액 (평단 계산용)
    
    money_updates = [] # (row_index, col_index, value)
    trade_updates = [] 
    
    # Money_Log 헤더 인덱스 찾기 (gspread는 1-based index)
    col_map_money = {name: i+1 for i, name in enumerate(df_money.columns)}
    col_map_trade = {name: i+1 for i, name in enumerate(df_trade.columns)}
    
    # 루프 시작
    for idx, row in timeline.iterrows():
        source = row['Source']
        
        # --- [A] Money Log (환전/배당) ---
        if source == 'Money':
            t_type = str(row.get('Type', '')).lower()
            usd_amt = safe_float(row.get('USD_Amount'))
            krw_amt = safe_float(row.get('KRW_Amount'))
            
            # 기존 값 확인 (Trust Existing)
            existing_rate = safe_float(row.get('Avg_Rate'))
            existing_bal = safe_float(row.get('Balance'))
            
            # 로직: 배당이든 환전이든 일단 USD 잔고는 늘어남
            # 환전(KRW_to_USD): KRW 투입 O -> 평단 재계산
            # 배당(Dividend): KRW 투입 X (0) -> 평단 희석
            
            # 1. 잔고 업데이트
            current_balance += usd_amt
            
            # 2. 평단 업데이트
            if 'dividend' in t_type or '배당' in t_type:
                # 배당: 원화투입 0원
                pass 
            else:
                # 환전: 원화투입 발생
                total_krw_invested += krw_amt
                
            # 평단가 계산 (잔고가 있을 때만)
            if current_balance > 0.0001:
                # 주의: 기존 로직은 "누적원화 / 누적달러"
                # 여기서 "누적원화"는 = (직전잔고 * 직전평단) + 신규투입원화
                prev_total_krw_val = (current_balance - usd_amt) * current_avg_rate
                
                added_krw_val = 0.0
                if 'dividend' in t_type or '배당' in t_type:
                    added_krw_val = 0
                else:
                    added_krw_val = krw_amt
                    
                # 새로운 평단
                calc_rate = (prev_total_krw_val + added_krw_val) / current_balance
                current_avg_rate = calc_rate
            
            # 3. 빈칸 채우기 (gspread update용)
            # 원본 df_money에서의 인덱스 찾기
            org_idx = row.name # concat 전의 인덱스가 보존됨 (ignore_index=False면)
            # 그러나 위에서 ignore_index=True를 썼으므로, 다시 찾아야 함.
            # 복잡하므로 Order_ID로 매칭하거나, 전체 재작성이 나을 수도 있음.
            # 여기서는 로직 단순화를 위해 "메모리 상에서 계산된 값"을 전역 변수에 저장해두고
            # 루프 끝난 후 일괄 업데이트 판단.
            
            # gspread 업데이트를 위해 cell 위치 저장 (빈칸일 경우만)
            if existing_rate == 0:
                # Money_Log 시트의 해당 행 번호 찾기 (Order_ID 기준)
                # 실제 구현시엔 시트 전체를 다시 쓰는게 속도상 빠름 (행이 적다면)
                pass # 아래에서 일괄 처리
                
            # 강제 덮어쓰기 (Sync 개념)
            df_money.loc[df_money['Order_ID'] == row['Order_ID'], 'Avg_Rate'] = current_avg_rate
            df_money.loc[df_money['Order_ID'] == row['Order_ID'], 'Balance'] = current_balance
            
        # --- [B] Trade Log (매수/매도) ---
        elif source == 'Trade':
            t_type = str(row.get('Type', '')).lower()
            qty = safe_float(row.get('Qty'))
            price = safe_float(row.get('Price_USD'))
            amount = qty * price
            
            # 기존 값
            existing_ex_rate = safe_float(row.get('Ex_Avg_Rate'))
            
            if 'buy' in t_type or '매수' in t_type:
                # 매수: 달러 감소, 평단 유지
                current_balance -= amount
                
                # Ex_Avg_Rate 채우기 (비어있으면 현재 저수지 평단 적용)
                if existing_ex_rate == 0:
                    df_trade.loc[df_trade['Order_ID'] == row['Order_ID'], 'Ex_Avg_Rate'] = current_avg_rate
                    
            elif 'sell' in t_type or '매도' in t_type:
                # 매도: 달러 증가, 평단 유지 (재투자 철학)
                current_balance += amount
                # 매도 시 Ex_Avg_Rate는 기록 안해도 됨 (수익 실현용)

    # 3. 결과 반환 (업데이트된 DF)
    return df_trade, df_money, current_balance, current_avg_rate, total_krw_invested

# -------------------------------------------------------------------
# [4] API 동기화 및 저장 (Sync)
# -------------------------------------------------------------------
def sync_api_data(sheet_instance, df_trade, df_money):
    ws_trade = sheet_instance.worksheet("Trade_Log")
    ws_money = sheet_instance.worksheet("Money_Log")
    
    # 1. 마지막 Order_ID 확인
    max_id_trade = pd.to_numeric(df_trade['Order_ID'], errors='coerce').max()
    max_id_money = pd.to_numeric(df_money['Order_ID'], errors='coerce').max()
    if pd.isna(max_id_trade): max_id_trade = 0
    if pd.isna(max_id_money): max_id_money = 0
    next_order_id = int(max(max_id_trade, max_id_money)) + 1
    
    # 2. 마지막 날짜 확인
    last_date_str = "20260101"
    if not df_trade.empty:
        last_date = pd.to_datetime(df_trade['Date']).max()
        last_date_str = last_date.strftime("%Y%m%d")
        
    end_date_str = datetime.now().strftime("%Y%m%d")
    
    # 3. API 호출
    with st.spinner(f"거래내역 조회 중... ({last_date_str} ~)"):
        res = kis.get_trade_history(last_date_str, end_date_str)
        
    if not res: return
    
    api_list = res.get('output1', [])
    if not api_list:
        st.toast("추가할 내역이 없습니다.")
        # 데이터가 없어도 빈칸 채우기 로직은 수행해야 함 (수기 입력분이 있을 수 있으니)
    else:
        # 4. 신규 데이터 필터링 & 추가
        new_rows = []
        # 중복 키: 날짜_종목_수량_가격
        keys = set(f"{r['Date']}_{r['Ticker']}_{safe_float(r['Qty'])}_{safe_float(r['Price_USD'])}" for _, r in df_trade.iterrows())
        
        for item in reversed(api_list):
            dt = datetime.strptime(item['dt'], "%Y%m%d").strftime("%Y-%m-%d")
            tk = item['pdno']
            name = item['prdt_name']
            qty = int(item['ccld_qty'])
            price = float(item['ft_ccld_unpr3'])
            side = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
            
            key = f"{dt}_{tk}_{qty}_{price}"
            if key in keys: continue
            
            # API 데이터 Append
            new_rows.append([
                dt, next_order_id, tk, name, side, qty, price, "", "API_Auto" # Ex_Avg_Rate는 비워둠
            ])
            next_order_id += 1
            
        if new_rows:
            ws_trade.append_rows(new_rows)
            st.success(f"{len(new_rows)}건 신규 거래 추가됨")
            # 다시 로드
            df_trade = pd.DataFrame(ws_trade.get_all_records())
            
    # 5. 빈칸 채우기 및 재계산 (Core Logic)
    updated_trade, updated_money, _, _, _ = process_timeline(df_trade, df_money, sheet_instance)
    
    # 6. 시트 전체 업데이트 (가장 확실한 방법)
    # 데이터가 많아지면 cell update로 변경해야 하지만 지금은 전체 덮어쓰기
    ws_trade.update([updated_trade.columns.values.tolist()] + updated_trade.astype(str).values.tolist())
    ws_money.update([updated_money.columns.values.tolist()] + updated_money.astype(str).values.tolist())
    
    st.toast("모든 데이터 동기화 및 재계산 완료!")
    time.sleep(1)
    st.rerun()

# -------------------------------------------------------------------
# [5] 메인 앱
# -------------------------------------------------------------------
def main():
    try:
        df_trade, df_money, sheet_instance = load_data()
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        st.stop()
        
    # 엔진 가동 (읽기 전용 모드 - 화면 표시용)
    # 실제 DB 업데이트는 Sync 버튼 눌렀을 때만 함
    u_trade, u_money, cur_bal, cur_rate, total_krw = process_timeline(df_trade, df_money, sheet_instance)
    
    cur_real_rate = get_realtime_rate()
    
    # 포트폴리오 구성
    portfolio = {}
    total_stock_val_usd = 0.0
    
    # 보유 수량 계산
    for _, row in u_trade.iterrows():
        tk = row['Ticker']
        qty = safe_float(row['Qty'])
        t_type = str(row['Type']).lower()
        
        if tk not in portfolio: portfolio[tk] = {'qty': 0, 'invested': 0}
        
        if 'buy' in t_type:
            portfolio[tk]['qty'] += qty
            # 매수 당시 환율 적용된 원화 투자금 (Ex_Avg_Rate 사용)
            rate_at_buy = safe_float(row['Ex_Avg_Rate'])
            if rate_at_buy == 0: rate_at_buy = cur_rate # 방어코드
            portfolio[tk]['invested'] += (qty * safe_float(row['Price_USD']) * rate_at_buy)
            
        elif 'sell' in t_type:
            # 매도 시 평단 기준으로 투자금 차감 (FIFO 아님, 이동평균 차감)
            if portfolio[tk]['qty'] > 0:
                avg_unit_invest = portfolio[tk]['invested'] / portfolio[tk]['qty']
                portfolio[tk]['invested'] -= (qty * avg_unit_invest)
                portfolio[tk]['qty'] -= qty

    # 현재가 조회 (API)
    tickers = [t for t in portfolio if portfolio[t]['qty'] > 0]
    prices = {}
    
    # --- UI Header ---
    c1, c2 = st.columns([3, 1])
    now = datetime.now()
    status = "🟢 Live" if (23 <= now.hour or now.hour < 6) else "🔴 Closed"
    
    with c1:
        st.title("🚀 Investment Command Center")
        st.caption(f"{status} | {now.strftime('%Y-%m-%d %H:%M:%S')}")
    with c2:
        if st.button("🔄 API Sync & Recalc"):
            sync_api_data(sheet_instance, df_trade, df_money)

    # 가격 가져오기 (스피너)
    if tickers:
        with st.spinner("시장가 조회 중..."):
            for t in tickers:
                prices[t] = kis.get_current_price(t)
    
    # 자산 가치 계산
    stock_val_usd = sum([portfolio[t]['qty'] * prices.get(t, 0) for t in tickers])
    total_asset_usd = stock_val_usd + cur_bal
    
    # KPI 계산
    # 총 자산 (KRW) = (주식평가액$ + 달러잔고$) * 현재실시간환율
    # *주의: 달러잔고는 내 평단(cur_rate)이 아니라, 현재 환전했을 때 가치(cur_real_rate)로 평가해야 실질 자산임
    total_asset_krw_real = total_asset_usd * cur_real_rate
    
    # 총 손익 = 현재 총자산(KRW) - 총 투입 원금(Money Log의 KRW 합계)
    # *Money Log의 KRW 합계 = 순수하게 내가 계좌에 넣은 돈
    total_input_krw = df_money.loc[df_money['Type'] == 'KRW_to_USD', 'KRW_Amount'].sum() # 배당 제외
    
    total_pl_krw = total_asset_krw_real - total_input_krw
    pl_pct = (total_pl_krw / total_input_krw * 100) if total_input_krw > 0 else 0
    
    # 안전마진 = 현재환율 - BEP환율
    # BEP환율 = 총 투입 원화 / 현재 달러 총자산
    bep_rate = total_input_krw / total_asset_usd if total_asset_usd > 0 else 0
    safety_margin = cur_real_rate - bep_rate

    # KPI UI
    kpi_html = f"""
    <div class="kpi-container">
        <div class="kpi-card">
            <div class="kpi-title">총 자산 (Total Assets)</div>
            <div class="kpi-main">₩ {total_asset_krw_real:,.0f}</div>
            <div class="kpi-sub {'kpi-red' if total_pl_krw >= 0 else 'kpi-blue'}">
                {'▲' if total_pl_krw >= 0 else '▼'} {abs(total_pl_krw):,.0f} ({pl_pct:+.2f}%)
            </div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">달러 저수지 (Reservoir)</div>
            <div class="kpi-main">$ {cur_bal:,.2f}</div>
            <div class="kpi-sub">Avg Rate: ₩ {cur_rate:,.2f}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">안전마진 (Safety Margin)</div>
            <div class="kpi-main">{safety_margin:+.2f} 원</div>
            <div class="kpi-sub">BEP: ₩ {bep_rate:,.2f}</div>
        </div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🕹️ 입력 매니저", "📊 대시보드", "📋 상세 테이블", "📜 통합 로그"])
    
    # Tab 1: 입력 매니저
    with tab1:
        st.subheader("📝 환전 & 배당 입력")
        with st.form("money_input"):
            c1, c2 = st.columns(2)
            i_type = c1.radio("구분", ["KRW_to_USD", "Dividend"], format_func=lambda x: "💰 환전 (입금)" if x=="KRW_to_USD" else "🏦 배당 (수령)")
            i_date = c2.date_input("날짜")
            
            c3, c4 = st.columns(2)
            i_usd = c3.number_input("USD 금액 ($)", min_value=0.01, step=0.01)
            i_krw = c4.number_input("KRW 금액 (₩)", min_value=0, step=100, disabled=(i_type=="Dividend"))
            
            i_note = st.text_input("비고", "수기입력")
            
            if st.form_submit_button("저장하기"):
                # 다음 Order_ID 구하기
                max_id = max(pd.to_numeric(df_trade['Order_ID']).max(), pd.to_numeric(df_money['Order_ID']).max())
                next_id = int(max_id) + 1 if not pd.isna(max_id) else 1
                
                # 배당일 경우 KRW=0, Rate=0
                rate = i_krw / i_usd if i_type=="KRW_to_USD" and i_usd > 0 else 0
                
                # 시트 저장
                ws_money = sheet_instance.worksheet("Money_Log")
                ws_money.append_row([
                    i_date.strftime("%Y-%m-%d"),
                    next_id,
                    i_type,
                    i_krw if i_type=="KRW_to_USD" else 0,
                    i_usd,
                    rate if i_type=="KRW_to_USD" else 0,
                    "", "", i_note # Avg, Bal은 비워둠 (Sync시 계산)
                ])
                st.success("저장되었습니다! (반영을 위해 상단 Sync 버튼을 눌러주세요)")
    
    # Tab 2: 대시보드 (카드)
    with tab2:
        for cat, t_list in SECTOR_ORDER.items():
            valid_tickers = [t for t in t_list if t in portfolio and portfolio[t]['qty'] > 0]
            if not valid_tickers: continue
            
            st.subheader(f"{cat}")
            cols = st.columns(4)
            idx = 0
            for tk in valid_tickers:
                data = portfolio[tk]
                cur_p = prices.get(tk, 0)
                # 내 평단가 (USD)
                my_avg_usd = data['invested'] / data['qty'] / cur_rate # 근사치 (정확한 USD 평단은 아님. 원화투자금 기반 역산)
                # 더 정확히: Trade Log에서 매수 USD 가중평균 구하는게 맞으나, 여기선 간단히
                # 로직상 portfolio['invested']는 KRW 기준임 (매수시 환율 적용했으므로)
                # -> portfolio['invested'] (KRW) / qty / cur_real_rate 하면 현재 환율 기준 BEP $ 나옴
                
                # 손익 ($): 단순 주가 차이
                # 정확한 손익은 (현재가 - 매수당시가) * 수량
                # 매수당시가(USD)를 별도로 관리해야 함. 지금 portfolio['invested']는 KRW임.
                # 편의상 Trade_Log를 다시 훑어 USD 평단을 구함
                usd_invested = 0
                buy_qty = 0
                for _, r in u_trade.iterrows():
                    if r['Ticker'] == tk and 'buy' in str(r['Type']).lower():
                        usd_invested += (safe_float(r['Price_USD']) * safe_float(r['Qty']))
                        buy_qty += safe_float(r['Qty'])
                    elif r['Ticker'] == tk and 'sell' in str(r['Type']).lower():
                        if buy_qty > 0:
                            avg = usd_invested / buy_qty
                            usd_invested -= (safe_float(r['Qty']) * avg)
                            buy_qty -= safe_float(r['Qty'])
                
                my_avg_usd = usd_invested / buy_qty if buy_qty > 0 else 0
                pl_usd = (cur_p - my_avg_usd) * data['qty']
                pl_rate = (cur_p - my_avg_usd) / my_avg_usd * 100 if my_avg_usd > 0 else 0
                
                color = "card-up" if pl_usd >= 0 else "card-down"
                font_c = "#FF5252" if pl_usd >= 0 else "#448AFF"
                arrow = "▲" if pl_usd >= 0 else "▼"
                
                html = f"""
                <div class="stock-card {color}">
                    <div class="card-header">
                        <span class="card-ticker">{tk}</span>
                        <span class="card-price" style="color:{font_c}">${cur_p:.2f}</span>
                    </div>
                    <div class="card-body">
                        <div class="card-row"><span class="card-label">수량</span><span>{data['qty']:.0f}</span></div>
                        <div class="card-row"><span class="card-label">평단</span><span>${my_avg_usd:.2f}</span></div>
                        <div class="card-row"><span class="card-label">손익</span><span style="color:{font_c}">{arrow} ${abs(pl_usd):.0f}</span></div>
                        <div class="card-row"><span class="card-label">수익률</span><span style="color:{font_c}">{pl_rate:+.1f}%</span></div>
                    </div>
                </div>
                """
                with cols[idx % 4]:
                    st.markdown(html, unsafe_allow_html=True)
                idx += 1

    # Tab 3: 상세 테이블
    with tab3:
        rows = []
        for tk in tickers:
            qty = portfolio[tk]['qty']
            if qty <= 0: continue
            
            # USD 평단 재계산 (위 로직 반복)
            usd_invested = 0; b_qty = 0
            for _, r in u_trade.iterrows():
                if r['Ticker'] == tk and 'buy' in str(r['Type']).lower():
                    usd_invested += (safe_float(r['Price_USD']) * safe_float(r['Qty']))
                    b_qty += safe_float(r['Qty'])
                elif r['Ticker'] == tk and 'sell' in str(r['Type']).lower():
                    if b_qty > 0:
                        avg = usd_invested / b_qty
                        usd_invested -= (safe_float(r['Qty']) * avg)
                        b_qty -= safe_float(r['Qty'])
            
            avg_usd = usd_invested / b_qty if b_qty > 0 else 0
            cur_p = prices.get(tk, 0)
            
            # 평가손익 (USD)
            val_usd = qty * cur_p
            pl_usd = val_usd - usd_invested
            
            # 원화 환산
            val_krw = val_usd * cur_real_rate
            invested_krw = portfolio[tk]['invested'] # 매수 당시 환율 적용된 원금
            
            total_pl_krw_tk = val_krw - invested_krw
            
            rows.append({
                "종목": tk,
                "수량": qty,
                "평단($)": f"{avg_usd:.2f}",
                "현재가($)": f"{cur_p:.2f}",
                "평가액(₩)": f"{val_krw:,.0f}",
                "총손익(₩)": f"{total_pl_krw_tk:,.0f}",
                "수익률": f"{(total_pl_krw_tk/invested_krw*100):.2f}%" if invested_krw>0 else "0%"
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # Tab 4: 통합 로그
    with tab4:
        # 시간순으로 정렬된 u_trade + u_money 표시
        # Order_ID 기준으로 병합하여 보여주기
        timeline_view = pd.concat([u_money.assign(Log='Money'), u_trade.assign(Log='Trade')], ignore_index=True)
        timeline_view['Order_ID'] = pd.to_numeric(timeline_view['Order_ID']).fillna(99999)
        timeline_view = timeline_view.sort_values(by=['Order_ID', 'Date'], ascending=[False, False])
        
        # 보기 좋게 컬럼 정리
        cols = ['Date', 'Log', 'Type', 'Ticker', 'Qty', 'USD_Amount', 'KRW_Amount', 'Avg_Rate', 'Balance', 'Ex_Avg_Rate']
        st.dataframe(timeline_view[cols].fillna(''), use_container_width=True)

if __name__ == "__main__":
    main()
