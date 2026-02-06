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

# [API 변경] 기간별 '체결내역(결제기준)' -> 기간별 '주문/체결내역(매매기준)'
# TR_ID: JTTT3001R (해외주식 주문체결내역)
def get_trade_history(start_date, end_date):
    token = get_access_token()
    if not token: return None

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "JTTT3001R", # [변경] 주문체결내역 TR
        "custtype": "P"
    }
    
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ORD_DT_S": start_date,
        "ORD_DT_E": end_date,
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    res = _request_api('GET', f"{URL_BASE}/uapi/overseas-stock/v1/trading/inquire-period-ccld", headers, params=params)
    
    if res.status_code == 200:
        data = res.json()
        output_list = []
        
        # JTTT3001R 응답 포맷을 기존 로직(Dashboard.py)이 이해할 수 있는 형태로 변환
        if 'output1' in data:
            for item in data['output1']:
                # 미체결 내역은 제외 (체결수량 > 0 인 것만)
                # JTTT3001R은 'ccld_qty'(체결수량) 필드가 있음
                ccld_qty = int(item.get('ccld_qty', 0)) if item.get('ccld_qty') else 0
                
                if ccld_qty > 0:
                    # 필드 매핑 (CTOS4001R -> JTTT3001R 차이 보정)
                    mapped_item = {
                        'dt': item['ord_dt'],        # 주문일자 (거래일)
                        'pdno': item['pdno'],        # 종목코드
                        'prdt_name': item['prdt_name'], # 종목명
                        'sll_buy_dvsn_cd': item['sll_buy_dvsn_cd'], # 01:매도, 02:매수
                        'ccld_qty': str(ccld_qty),
                        # ft_ccld_unpr3: 체결단가 (소수점 포함 3자리) vs ft_ord_unpr3? 
                        # 보통 avg_prvs (체결평균가) 사용이 안전
                        'ft_ccld_unpr3': item.get('avg_prvs', item.get('ft_ccld_unpr3', '0')) 
                    }
                    output_list.append(mapped_item)
                    
            # 변환된 리스트를 output1 키에 담아 리턴 (Dashboard.py 호환성 유지)
            return {'output1': output_list}
            
    return None
