import streamlit as st
import requests
import json

# 1. 토큰 발급 (접근 권한 얻기)
def get_access_token():
    # 이미 세션에 토큰이 있으면 재사용 (API 호출 낭비 방지)
    if 'kis_token' in st.session_state and st.session_state['kis_token']:
        return st.session_state['kis_token']

    # secrets에서 정보 가져오기
    base_url = st.secrets["kis_api"]["URL_BASE"]
    app_key = st.secrets["kis_api"]["APP_KEY"]
    app_secret = st.secrets["kis_api"]["APP_SECRET"]

    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    
    # 토큰 요청
    res = requests.post(f"{base_url}/oauth2/tokenP", headers=headers, data=json.dumps(body))
    
    if res.status_code == 200:
        token = res.json()["access_token"]
        st.session_state['kis_token'] = token # 세션에 저장
        return token
    else:
        st.error(f"토큰 발급 실패: {res.text}")
        return None

# 2. 미국 주식 현재가 조회 (테스트용)
def get_current_price(ticker):
    token = get_access_token()
    if not token: return 0.0

    base_url = st.secrets["kis_api"]["URL_BASE"]
    app_key = st.secrets["kis_api"]["APP_KEY"]
    app_secret = st.secrets["kis_api"]["APP_SECRET"]

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "HHDFS00000300" # 미국주식 현재가 체결가 TR ID
    }
    
    # 리얼티인컴(O) -> 뉴욕(NYS) / 나스닥(NAS) 등 시장 구분 필요
    # 편의상 자주 쓰는 시장 순서로 조회 시도 (NYS -> NAS -> AMS)
    markets = ["NYS", "NAS", "AMS"]
    
    for mkt in markets:
        params = {
            "AUTH": "",
            "EXCD": mkt,        # 시장코드 (NYS:뉴욕, NAS:나스닥)
            "SYMB": ticker      # 종목코드
        }
        
        res = requests.get(f"{base_url}/uapi/overseas-price/v1/quotations/price", headers=headers, params=params)
        
        if res.status_code == 200:
            data = res.json()
            if data['rt_cd'] == '0' and data['output']: # 성공
                price = float(data['output']['last']) # 현재가
                if price > 0: return price
    
    return 0.0 # 조회 실패 시 0 반환
