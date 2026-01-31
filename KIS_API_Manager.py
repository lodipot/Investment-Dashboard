import streamlit as st
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# -----------------------------------------------------------
# 1. 구글 시트 연결 (토큰 저장소 접근용)
# -----------------------------------------------------------
def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# -----------------------------------------------------------
# 2. 토큰 관리 (핵심: 시트 확인 -> 없으면 발급 -> 저장)
# -----------------------------------------------------------
def get_access_token():
    # 1단계: 세션(메모리)에 있으면 그거 씀 (가장 빠름)
    if 'kis_token' in st.session_state and st.session_state['kis_token']:
        return st.session_state['kis_token']

    # 2단계: 구글 시트(저장소) 확인
    try:
        client = get_sheet_client()
        sh = client.open("Investment_Dashboard_DB")
        ws = sh.worksheet("Token_Storage") # 토큰 저장용 시트
        
        # A1: 토큰, B1: 만료시간 (YYYY-MM-DD HH:MM:SS)
        saved_data = ws.row_values(1)
        
        if saved_data:
            saved_token = saved_data[0]
            saved_expiry_str = saved_data[1]
            
            # 유효기간 체크 (여유 있게 1시간 뺌)
            expiry_dt = datetime.strptime(saved_expiry_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < (expiry_dt - timedelta(hours=1)):
                st.session_state['kis_token'] = saved_token
                # print("✅ 구글 시트의 캐시된 토큰을 사용합니다.") # 디버깅용
                return saved_token
    except Exception:
        # 시트가 없거나 읽기 실패하면 그냥 넘어감 (새로 발급받으면 됨)
        pass

    # 3단계: KIS 서버에 새 토큰 요청 (하루 1회만 실행됨)
    try:
        base_url = st.secrets["kis_api"]["URL_BASE"]
        app_key = st.secrets["kis_api"]["APP_KEY"]
        app_secret = st.secrets["kis_api"]["APP_SECRET"]

        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "appsecret": app_secret
        }
        
        res = requests.post(f"{base_url}/oauth2/tokenP", headers=headers, data=json.dumps(body))
        
        if res.status_code == 200:
            data = res.json()
            new_token = data["access_token"]
            expiry_str = data["access_token_token_expired"] # 예: 2026-01-31 14:00:00
            
            # 세션에 저장
            st.session_state['kis_token'] = new_token
            
            # 4단계: 구글 시트에 백업 (다음번 접속을 위해)
            try:
                ws.clear()
                ws.append_row([new_token, expiry_str])
                # print("💾 새 토큰을 구글 시트에 저장했습니다.")
            except:
                pass # 저장 실패해도 당장 쓰는덴 지장 없음

            return new_token
        else:
            st.error(f"토큰 발급 실패: {res.text}")
            return None
            
    except Exception as e:
        st.error(f"API 연결 오류: {e}")
        return None

# -----------------------------------------------------------
# 3. 미국 주식 현재가 조회 (기능 함수)
# -----------------------------------------------------------
def get_current_price(ticker):
    token = get_access_token() # 여기서 스마트하게 가져옴
    if not token: return 0.0

    base_url = st.secrets["kis_api"]["URL_BASE"]
    app_key = st.secrets["kis_api"]["APP_KEY"]
    app_secret = st.secrets["kis_api"]["APP_SECRET"]

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "HHDFS00000300"
    }
    
    # 조회할 시장 순서 (뉴욕 -> 나스닥 -> 아멕스 -> 기타)
    # TSM 같은 경우 뉴욕(NYS)에 있음.
    markets = ["NYS", "NAS", "AMS"]
    
    for mkt in markets:
        params = {
            "AUTH": "",
            "EXCD": mkt,
            "SYMB": ticker
        }
        
        try:
            res = requests.get(f"{base_url}/uapi/overseas-price/v1/quotations/price", headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0' and data['output']:
                    price = float(data['output']['last'])
                    if price > 0: return price
        except:
            continue
    
    return 0.0
