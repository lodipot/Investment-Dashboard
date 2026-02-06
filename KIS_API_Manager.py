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
    if not force_refresh and 'kis_token' in st.session_state:
        return st.session_state['kis_token']

    client = get_sheet_client()
    try:
        sh = client.open("Investment_Dashboard_DB")
        ws = sh.worksheet("Token_Storage")
        token_val = ws.acell('A1').value
        expiry_val = ws.acell('B1').value
        
        if not force_refresh and token_val and expiry_val:
            expiry_dt = datetime.strptime(expiry_val, "%Y-%m-%d %H:%M:%S")
            if datetime.now() < expiry_dt - timedelta(hours=1):
                st.session_state['kis_token'] = token_val
                return token_val
    except:
        pass

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
            
            try:
                ws.update_acell('A1', new_token)
                ws.update_acell('B1', expiry_dt.strftime("%Y-%m-%d %H:%M:%S"))
            except:
                pass
            
            st.session_state['kis_token'] = new_token
            return new_token
        return None
    except Exception as e:
        print(f"Token Error: {e}")
        return None

def _request_api(method, url, headers, params=None, body=None):
    if method == 'GET':
        res = requests.get(url, headers=headers, params=params)
    else:
        res = requests.post(url, headers=headers, data=json.dumps(body))
    
    if res.status_code != 200 or res.json().get('msg_cd') == 'EGW00123':
        new_token = get_access_token(force_refresh=True)
        if not new_token: return res
        
        headers["authorization"] = f"Bearer {new_token}"
        if method == 'GET':
            res = requests.get(url, headers=headers, params=params)
        else:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            
    return res

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

# [API 변경] 결제내역(CTOS4001R) 대신 체결내역(TTTS3035R) 사용
# URL: /uapi/overseas-stock/v1/trading/inquire-ccnl (기간별 체결 조회 가능)
def get_trade_history(start_date, end_date):
    token = get_access_token()
    if not token: return None

    # [공식 문서 기반 수정]
    # API 명: 해외주식 주문체결내역
    # TR_ID: TTTS3035R (실전투자)
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "TTTS3035R", # [중요] 문서에서 확인한 정확한 TR_ID
        "custtype": "P"
    }
    
    # 문서에 명시된 파라미터 구조 준수 (ORD_STRT_DT, ORD_END_DT)
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ORD_STRT_DT": start_date,  # 조회시작일 (YYYYMMDD)
        "ORD_END_DT": end_date,    # 조회종료일 (YYYYMMDD)
        "SLL_BUY_DVSN_CD": "00",   # 매도매수구분 (00:전체)
        "CCLD_NCCS_DVSN": "00",    # 체결미체결구분 (00:전체)
        "OVRS_EXCG_CD": "%",       # 해외거래소코드 (%: 전체)
        "SORT_SQN": "DS",          # 정렬순서 (DS:주문순)
        "ORD_DT": "",
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "CTX_AREA_FK200": "",      
        "CTX_AREA_NK200": ""       
    }
    
    # [수정된 URL] inquire-ccnl (O)
    res = _request_api('GET', f"{URL_BASE}/uapi/overseas-stock/v1/trading/inquire-ccnl", headers, params=params)
    
    if res.status_code == 200:
        data = res.json()
        output_list = []
        
        # 문서상 응답 리스트 키는 'output'
        if 'output' in data:
            for item in data['output']:
                # FT_CCLD_QTY (체결수량)이 0보다 큰 것만 추출 (미체결 주문 제외)
                # 문서상 필드명: ft_ccld_qty (체결수량), ft_ccld_unpr3 (체결단가)
                ccld_qty = float(item.get('ft_ccld_qty', 0))
                
                if ccld_qty > 0:
                    # Dashboard.py가 이해하는 포맷으로 변환
                    mapped_item = {
                        'dt': item['ord_dt'],           # 주문일자
                        'pdno': item['pdno'],           # 종목코드
                        'prdt_name': item['prdt_name'], # 종목명
                        'sll_buy_dvsn_cd': item['sll_buy_dvsn_cd'], # 01:매도, 02:매수
                        'ccld_qty': str(int(ccld_qty)),
                        'ft_ccld_unpr3': item.get('ft_ccld_unpr3', '0') # 체결단가
                    }
                    output_list.append(mapped_item)
        
        return {'output1': output_list}
            
    return None
