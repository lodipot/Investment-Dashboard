import streamlit as st
import requests
import json
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# =========================================================
# [1] 설정 및 상수 (st.secrets 사용)
# =========================================================
# secrets.toml 파일에 아래 내용이 있어야 합니다.
# [kis_api]
# APP_KEY = "..."
# APP_SECRET = "..."
# URL_BASE = "https://openapi.koreainvestment.com:9443"
# CANO = "..."
# ACNT_PRDT_CD = "..."

URL_BASE = st.secrets["kis_api"]["URL_BASE"]
APP_KEY = st.secrets["kis_api"]["APP_KEY"]
APP_SECRET = st.secrets["kis_api"]["APP_SECRET"]
CANO = st.secrets["kis_api"]["CANO"]
ACNT_PRDT_CD = st.secrets["kis_api"]["ACNT_PRDT_CD"]

# =========================================================
# [2] 구글 시트 및 토큰 관리
# =========================================================
def get_sheet_client():
    """구글 시트 클라이언트 연결"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def get_access_token():
    """토큰 발급 및 유효성 검사 (Auto Refresh)"""
    # 1. 세션에 있으면 반환
    if 'kis_token' in st.session_state and st.session_state['kis_token']:
        return st.session_state['kis_token']

    # 2. 시트에서 확인
    try:
        client = get_sheet_client()
        sh = client.open("Investment_Dashboard_DB") # 파일명 주의
        ws = sh.worksheet("Token_Storage")
        
        token_val = ws.acell('A1').value
        expiry_val = ws.acell('B1').value
        
        # 유효기간 체크 (여유있게 1시간 전)
        if token_val and expiry_val:
            expiry_dt = datetime.strptime(expiry_val, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < expiry_dt - timedelta(hours=1):
                st.session_state['kis_token'] = token_val
                return token_val
    except:
        pass

    # 3. 만료되었거나 없으면 재발급
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    
    res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body))
    
    if res.status_code == 200:
        data = res.json()
        new_token = data['access_token']
        expires_in = data['expires_in'] # 초 단위
        expiry_dt = datetime.now() + timedelta(seconds=expires_in)
        
        # 시트에 저장
        try:
            ws.update_acell('A1', new_token)
            ws.update_acell('B1', expiry_dt.strftime("%Y-%m-%d %H:%M:%S"))
            st.session_state['kis_token'] = new_token
            return new_token
        except Exception as e:
            st.error(f"토큰 시트 저장 실패: {e}")
            return new_token
    else:
        st.error(f"API 토큰 발급 실패: {res.text}")
        return None

def get_hashkey(datas):
    """POST 요청용 해시키 발급"""
    headers = {
        'content-type': 'application/json',
        'appkey': APP_KEY,
        'appsecret': APP_SECRET
    }
    res = requests.post(f"{URL_BASE}/uapi/hashkey", headers=headers, data=json.dumps(datas))
    if res.status_code == 200:
        return res.json()["HASH"]
    return None

# =========================================================
# [3] 핵심 기능 API
# =========================================================

def get_trade_history(start_date, end_date):
    """
    해외주식 기간별 체결내역 (CTOS4001R)
    start_date, end_date format: YYYYMMDD
    """
    token = get_access_token()
    if not token: return None

    path = "/uapi/overseas-stock/v1/trading/inquire-period-trans"
    url = f"{URL_BASE}{path}"
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "CTOS4001R", # 해외주식 기간별 매매내역
        "custtype": "P"
    }
    
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ORD_DT_S": start_date,
        "ORD_DT_E": end_date,
        "WCRC_DVSN": "00", # 통화구분
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 200:
        return res.json()
    else:
        st.error(f"체결내역 조회 실패: {res.text}")
        return None

def get_current_price(ticker):
    """미국 주식 현재가 (HHDFS00000300)"""
    token = get_access_token()
    if not token: return 0.0

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "HHDFS00000300"
    }
    
    # 주요 거래소 순회
    markets = ["NYS", "NAS", "AMS"]
    for mkt in markets:
        params = {
            "AUTH": "",
            "EXCD": mkt,
            "SYMB": ticker
        }
        try:
            res = requests.get(f"{URL_BASE}/uapi/overseas-price/v1/quotations/price", headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0':
                    return float(data['output']['last'])
        except:
            continue
            
    return 0.0
