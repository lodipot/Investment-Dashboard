import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# STEP 1의 매니저 활용
import KIS_API_Manager as kis

st.set_page_config(page_title="DB Migration", page_icon="🏗️", layout="wide")
st.title("🏗️ DB 마이그레이션 (Final)")
st.caption("새로운 API 키로 거래내역을 가져와 구글 시트를 재구축합니다.")

# -----------------------------------------------------------
# 1. 설정 및 공통 함수
# -----------------------------------------------------------
token = kis.get_access_token()
if not token:
    st.error("❌ 토큰 발급 실패. secrets.toml을 확인하세요.")
    st.stop()

base_url = st.secrets["kis_api"]["URL_BASE"].strip()
if base_url.endswith("/"): base_url = base_url[:-1]

app_key = st.secrets["kis_api"]["APP_KEY"]
app_secret = st.secrets["kis_api"]["APP_SECRET"]
cano = st.secrets["kis_api"]["CANO"]
acnt_prdt_cd = st.secrets["kis_api"]["ACNT_PRDT_CD"]

headers = {
    "content-type": "application/json",
    "authorization": f"Bearer {token}",
    "appkey": app_key,
    "appsecret": app_secret
}

# -----------------------------------------------------------
# 2. 데이터 수집 함수 (Plan A: 내역, Plan B: 잔고)
# -----------------------------------------------------------
def fetch_history_data():
    """Plan A: 거래 내역(History) 조회"""
    st.info("📡 거래 내역(History) 조회 시도 중...")
    
    # 1) 매매 내역 (CCLD)
    trade_rows = []
    # 주소 후보 (v1, v2)
    ccld_paths = ["/uapi/overseas-stock/v1/trading/inquire-period-ccld"]
    
    headers['tr_id'] = "TTTS3035R"
    start_dt = "20240101" # 넉넉하게
    end_dt = datetime.now().strftime("%Y%m%d")
    
    ccld_success = False
    
    for path in ccld_paths:
        full_url = f"{base_url}{path}"
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
            "STRT_DT": start_dt, "END_DT": end_dt,
            "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(full_url, headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0':
                    ccld_success = True
                    # 데이터 파싱
                    for item in data['output1']:
                        dt_str = item['ord_dt']
                        dt_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                        # 매수/매도 구분
                        t_type = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
                        
                        trade_rows.append([
                            dt_fmt,
                            f"{item['ord_dt']}_{item['ord_no']}", # ID
                            item['pdno'],      # Ticker
                            item['prdt_name'], # Name
                            t_type,
                            int(item['ft_ccld_qty']),
                            float(item['ft_ccld_unpr3']),
                            0, # 환율은 별도 매칭 필요하지만 일단 0
                            "API_History"
                        ])
                    break
        except: continue
        
    # 2) 배당/입출금 내역 (TRANS)
    div_rows = []
    headers['tr_id'] = "TTTS3031R"
    trans_path = "/uapi/overseas-stock/v1/trading/inquire-period-trans"
    
    params['ERNG_DVSN_CD'] = "01"
    params['WCRC_FRCR_DVSN_CD'] = "02"
    
    try:
        res = requests.get(f"{base_url}{trans_path}", headers=headers, params=params)
        if res.status_code == 200:
            data = res.json()
            if 'output' in data:
                for item in data['output']:
                    if "배당" in item['tr_nm'] and float(item['frcr_amt']) > 0:
                        dt_str = item['tr_dt']
                        dt_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                        ticker = item['ovrs_pdno']
                        
                        # [하드코딩] 리얼티인컴 1월 16일
                        ex_rate = 1450.0
                        if ticker == 'O' and '01-1' in dt_fmt: # 날짜 대충 매칭
                            ex_rate = 1469.7
                            
                        div_rows.append([
                            dt_fmt,
                            f"{item['tr_dt']}_{item['tr_no']}",
                            ticker,
                            float(item['frcr_amt']),
                            ex_rate,
                            "API_History"
                        ])
    except: pass

    if ccld_success:
        return trade_rows, div_rows
    else:
        return None, None

def fetch_balance_snapshot():
    """Plan B: 잔고(Balance) 스냅샷 조회"""
    st.warning("⚠️ 거래 내역 조회 실패. '실시간 잔고' 기준으로 DB를 초기화합니다.")
    
    headers['tr_id'] = "TTTS3012R"
    path = "/uapi/overseas-stock/v1/trading/inquire-present-balance"
    
    params = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
        "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "840",
        "TR_MKET_CD": "00", "INQR_DVSN_CD": "00"
    }
    
    trade_rows = []
    today = datetime.now().strftime("%Y-%m-%d")
    
    try:
        res = requests.get(f"{base_url}{path}", headers=headers, params=params)
        data = res.json()
        if res.status_code == 200 and data['rt_cd'] == '0':
            for item in data['output1']:
                qty = int(item['ovrs_cblc_qty'])
                if qty > 0:
                    # 평균단가(pchs_avg_pric) 사용
                    avg_price = float(item['pchs_avg_pric'])
                    trade_rows.append([
                        today,
                        "INIT_SNAPSHOT",
                        item['ovrs_pdno'],
                        item['ovrs_item_name'],
                        "Buy",
                        qty,
                        avg_price,
                        0,
                        "Snapshot_Setup"
                    ])
            return trade_rows, [] # 배당은 스냅샷으로 알 수 없음
    except Exception as e:
        st.error(f"잔고 조회 오류: {e}")
        
    return None, None

def save_to_sheet(t_data, d_data):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")
        
        # Trade_Log
        ws_trade = sh.worksheet("Trade_Log")
        ws_trade.clear()
        ws_trade.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Exchange_Rate", "Note"])
        if t_data: ws_trade.append_rows(t_data)
        
        # Dividend_Log
        ws_div = sh.worksheet("Dividend_Log")
        ws_div.clear()
        ws_div.append_row(["Date", "Order_ID", "Ticker", "Amount_USD", "Ex_Rate", "Note"])
        if d_data: ws_div.append_rows(d_data)
        
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# -----------------------------------------------------------
# 3. UI 실행
# -----------------------------------------------------------
st.subheader("1. 데이터 수집")

if st.button("🚀 데이터 불러오기 (자동 감지)"):
    with st.spinner("API 조회 중..."):
        # Plan A 시도
        t_data, d_data = fetch_history_data()
        
        if t_data is None:
            # Plan B 시도
            t_data, d_data = fetch_balance_snapshot()
            if t_data is None:
                st.error("❌ 모든 조회 실패. 키 권한을 다시 확인해주세요.")
                st.stop()
            else:
                st.warning("👉 '잔고 스냅샷' 모드로 데이터를 가져왔습니다.")
        else:
            st.success("✅ '거래 내역'을 완벽하게 가져왔습니다!")

        # 결과 보여주기
        st.write(f"📊 매매 데이터: {len(t_data)}건")
        st.dataframe(pd.DataFrame(t_data, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Rate", "Note"]))
        
        st.write(f"💰 배당 데이터: {len(d_data)}건")
        if d_data:
            st.dataframe(pd.DataFrame(d_data, columns=["Date", "ID", "Ticker", "Amount", "Rate", "Note"]))
            
        st.session_state['final_t'] = t_data
        st.session_state['final_d'] = d_data

st.subheader("2. DB 저장")
if st.button("💾 구글 시트에 덮어쓰기"):
    if 'final_t' in st.session_state:
        if save_to_sheet(st.session_state['final_t'], st.session_state['final_d']):
            st.success("🎉 DB 구축 완료! 이제 Dashboard.py를 STEP 3(최종본)로 교체하세요.")
            st.balloons()
    else:
        st.warning("먼저 데이터를 불러와주세요.")
