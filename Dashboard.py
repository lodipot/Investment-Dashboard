import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# STEP 1 매니저 활용
import KIS_API_Manager as kis

st.set_page_config(page_title="DB Migration Final", page_icon="🏗️", layout="wide")
st.title("🏗️ DB 마이그레이션 (Token Reset)")
st.caption("오래된 토큰을 삭제하고, 새로운 키로 거래내역을 가져옵니다.")

# -----------------------------------------------------------
# 0. 토큰 강제 초기화 및 재발급 (핵심 기능)
# -----------------------------------------------------------
def force_refresh_token():
    try:
        # 1. 구글 시트 연결
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")
        ws = sh.worksheet("Token_Storage")
        
        # 2. 시트 비우기 (옛날 토큰 삭제)
        ws.clear()
        
        # 3. 세션 비우기
        if 'kis_token' in st.session_state:
            del st.session_state['kis_token']
            
        # 4. 새 토큰 발급 요청
        new_token = kis.get_access_token()
        return new_token
        
    except Exception as e:
        st.error(f"토큰 초기화 실패: {e}")
        return None

# -----------------------------------------------------------
# 1. 설정 및 공통 변수
# -----------------------------------------------------------
# (주의: 토큰은 버튼 누를 때 받아옵니다)
base_url = st.secrets["kis_api"]["URL_BASE"].strip()
if base_url.endswith("/"): base_url = base_url[:-1]

app_key = st.secrets["kis_api"]["APP_KEY"]
app_secret = st.secrets["kis_api"]["APP_SECRET"]
cano = st.secrets["kis_api"]["CANO"]
acnt_prdt_cd = st.secrets["kis_api"]["ACNT_PRDT_CD"]

# -----------------------------------------------------------
# 2. 데이터 수집 함수 (Plan A & B)
# -----------------------------------------------------------
def fetch_history_data(token):
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret
    }
    
    # 1) 매매 내역 (Plan A)
    st.info("📡 거래 내역(History) 조회 시도 중...")
    trade_rows = []
    
    # [중요] v1 주소 시도 (대부분 여기서 성공해야 함)
    path = "/uapi/overseas-stock/v1/trading/inquire-period-ccld"
    full_url = f"{base_url}{path}"
    
    headers['tr_id'] = "TTTS3035R"
    
    params = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
        "STRT_DT": "20240101", "END_DT": datetime.now().strftime("%Y%m%d"),
        "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    ccld_success = False
    
    try:
        res = requests.get(full_url, headers=headers, params=params)
        if res.status_code == 200:
            data = res.json()
            if data['rt_cd'] == '0':
                ccld_success = True
                for item in data['output1']:
                    dt_str = item['ord_dt']
                    dt_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                    t_type = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
                    
                    trade_rows.append([
                        dt_fmt,
                        f"{item['ord_dt']}_{item['ord_no']}",
                        item['pdno'],
                        item['prdt_name'],
                        t_type,
                        int(item['ft_ccld_qty']),
                        float(item['ft_ccld_unpr3']),
                        0,
                        "API_History"
                    ])
            else:
                st.warning(f"매매내역 응답코드 실패: {data['msg1']}")
        else:
            st.warning(f"매매내역 통신 실패: {res.status_code}")
    except Exception as e:
        st.error(f"매매내역 오류: {e}")

    # 2) 배당 내역
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
                        
                        ex_rate = 1450.0
                        if ticker == 'O' and '01-1' in dt_fmt: ex_rate = 1469.7
                            
                        div_rows.append([
                            dt_fmt,
                            f"{item['tr_dt']}_{item['tr_no']}",
                            ticker,
                            float(item['frcr_amt']),
                            ex_rate,
                            "API_History"
                        ])
    except: pass

    if ccld_success: return trade_rows, div_rows
    else: return None, None

def fetch_balance_snapshot(token):
    # Plan B: 잔고 스냅샷
    st.warning("⚠️ 거래 내역 조회 실패. '실시간 잔고'로 대체합니다.")
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "TTTS3012R"
    }
    
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
                    trade_rows.append([
                        today, "INIT_SNAPSHOT",
                        item['ovrs_pdno'], item['ovrs_item_name'],
                        "Buy", qty, float(item['pchs_avg_pric']),
                        0, "Snapshot_Setup"
                    ])
            return trade_rows, []
    except: pass
    return None, None

def save_to_sheet(t_data, d_data):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")
        
        ws_trade = sh.worksheet("Trade_Log")
        ws_trade.clear()
        ws_trade.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Exchange_Rate", "Note"])
        if t_data: ws_trade.append_rows(t_data)
        
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

if st.button("🚀 토큰 초기화 & 데이터 불러오기"):
    with st.spinner("구글 시트 토큰 삭제 및 재발급 중..."):
        # [핵심] 강제로 새 토큰을 받아옵니다.
        fresh_token = force_refresh_token()
        
    if not fresh_token:
        st.error("❌ 새 토큰 발급 실패! Secrets 설정이나 API 신청 상태를 다시 확인하세요.")
        st.stop()
        
    st.success("✅ 새 토큰 발급 완료! 데이터 조회를 시작합니다.")
    
    with st.spinner("거래 내역 조회 중..."):
        # 새 토큰으로 조회 시도
        t_data, d_data = fetch_history_data(fresh_token)
        
        if t_data is None:
            t_data, d_data = fetch_balance_snapshot(fresh_token)
            if t_data is None:
                st.error("❌ 모든 조회 실패. (키 권한 문제 지속됨)")
                st.stop()
            else:
                st.warning("👉 '잔고 스냅샷' 모드입니다.")
        else:
            st.success("✅ '거래 내역' 조회 성공! (권한 정상)")

        st.session_state['final_t'] = t_data
        st.session_state['final_d'] = d_data
        
        st.write(f"📊 매매 데이터: {len(t_data)}건")
        st.dataframe(pd.DataFrame(t_data, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Rate", "Note"]))
        
        if d_data:
            st.write(f"💰 배당 데이터: {len(d_data)}건")
            st.dataframe(pd.DataFrame(d_data, columns=["Date", "ID", "Ticker", "Amount", "Rate", "Note"]))

st.subheader("2. DB 저장")
if st.button("💾 구글 시트에 덮어쓰기"):
    if 'final_t' in st.session_state:
        if save_to_sheet(st.session_state['final_t'], st.session_state['final_d']):
            st.success("🎉 DB 구축 완료! 이제 Dashboard.py를 STEP 3(최종본)로 교체하세요.")
            st.balloons()
    else:
        st.warning("먼저 데이터를 불러와주세요.")
