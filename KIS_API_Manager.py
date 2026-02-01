import streamlit as st
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time

# =========================================================
# [1] 설정 및 상수
# =========================================================
# secrets.toml 로드
URL_BASE = st.secrets["kis_api"]["URL_BASE"]
APP_KEY = st.secrets["kis_api"]["APP_KEY"]
APP_SECRET = st.secrets["kis_api"]["APP_SECRET"]
CANO = st.secrets["kis_api"]["CANO"]
ACNT_PRDT_CD = st.secrets["kis_api"]["ACNT_PRDT_CD"]

# =========================================================
# [2] 토큰 관리 (Smart Refresh)
# =========================================================
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_access_token(force_refresh=False):
    """
    토큰을 가져옵니다. 
    force_refresh=True면 무조건 새로 발급받습니다 (에러 발생 시 사용).
    """
    # 1. 세션 메모리 확인 (Refresh 아닐 때만)
    if not force_refresh and 'kis_token' in st.session_state:
        return st.session_state['kis_token']

    # 2. 구글 시트 확인
    client = get_sheet_client()
    try:
        sh = client.open("Investment_Dashboard_DB")
        ws = sh.worksheet("Token_Storage")
        token_val = ws.acell('A1').value
        expiry_val = ws.acell('B1').value
        
        # 유효기간 체크 (1시간 버퍼)
        if not force_refresh and token_val and expiry_val:
            expiry_dt = datetime.strptime(expiry_val, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < expiry_dt - timedelta(hours=1):
                st.session_state['kis_token'] = token_val
                return token_val
    except:
        pass # 시트 읽기 실패 시 바로 재발급 시도

    # 3. 만료/강제갱신/없음 -> 재발급 요청
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    
    try:
        res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body))
        data = res.json()
        
        if res.status_code == 200 and 'access_token' in data:
            new_token = data['access_token']
            expires_in = data['expires_in']
            expiry_dt = datetime.now() + timedelta(seconds=expires_in)
            
            # 시트 업데이트
            try:
                ws.update_acell('A1', new_token)
                ws.update_acell('B1', expiry_dt.strftime("%Y-%m-%d %H:%M:%S"))
            except:
                pass
            
            st.session_state['kis_token'] = new_token
            return new_token
        else:
            st.error(f"토큰 발급 실패: {data.get('error_description', res.text)}")
            return None
    except Exception as e:
        st.error(f"API 연결 오류: {e}")
        return None

# =========================================================
# [3] API 호출 래퍼 (Self-Healing)
# =========================================================
def _request_api(method, url, headers, params=None, body=None):
    """API 호출 실패 시 토큰 갱신 후 1회 재시도"""
    
    # 1차 시도
    if method == 'GET':
        res = requests.get(url, headers=headers, params=params)
    else:
        res = requests.post(url, headers=headers, data=json.dumps(body))
    
    # 토큰 만료 에러 감지 (EGW00123 등)
    if res.status_code != 200 or res.json().get('msg_cd') == 'EGW00123':
        # 토큰 강제 갱신
        new_token = get_access_token(force_refresh=True)
        if not new_token: return res # 갱신 실패하면 원래 응답 반환
        
        # 헤더 업데이트 및 재시도
        headers["authorization"] = f"Bearer {new_token}"
        if method == 'GET':
            res = requests.get(url, headers=headers, params=params)
        else:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            
    return res

# =========================================================
# [4] 기능 함수
# =========================================================
def get_current_price(ticker):
    token = get_access_token()
    if not token: return 0.0

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "HHDFS00000300"
    }
    
    markets = ["NYS", "NAS", "AMS"]
    for mkt in markets:
        params = {"AUTH": "", "EXCD": mkt, "SYMB": ticker}
        try:
            res = _request_api('GET', f"{URL_BASE}/uapi/overseas-price/v1/quotations/price", headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0':
                    return float(data['output']['last'])
        except:
            continue
    return 0.0

def get_trade_history(start_date, end_date):
    token = get_access_token()
    if not token: return None

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "CTOS4001R",
        "custtype": "P"
    }
    
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ORD_DT_S": start_date,
        "ORD_DT_E": end_date,
        "WCRC_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    res = _request_api('GET', f"{URL_BASE}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers, params=params)
    return res.json() if res.status_code == 200 else None
