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
try:
    URL_BASE = st.secrets["kis_api"]["URL_BASE"]
    APP_KEY = st.secrets["kis_api"]["APP_KEY"]
    APP_SECRET = st.secrets["kis_api"]["APP_SECRET"]
    CANO = st.secrets["kis_api"]["CANO"]
    ACNT_PRDT_CD = st.secrets["kis_api"]["ACNT_PRDT_CD"]
except Exception:
    st.error("secrets.toml 파일 설정을 확인해주세요.")
    st.stop()

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

# =========================================================
# [3] 핵심: 하이브리드 거래내역 조회 (기간별 + 잔고)
# =========================================================
def get_trade_history(start_date, end_date):
    token = get_access_token()
    if not token: return None

    final_result = []

    # --- TRACK A: 기간별 결제내역 조회 (CTOS4001R) ---
    # * 목적: 이미 결제(T+3)가 끝나서 원장에 박제된 '확정 데이터' 조회
    try:
        headers_hist = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET,
            "tr_id": "CTOS4001R", 
            "custtype": "P"
        }
        
        params_hist = {
            "CANO": CANO,
            "ACNT_PRDT_CD": ACNT_PRDT_CD,
            "ORD_DT_S": start_date, # YYYYMMDD
            "ORD_DT_E": end_date,   # YYYYMMDD
            "WCRC_DVSN": "00",      # 외화기준
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        res_hist = _request_api('GET', f"{URL_BASE}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers_hist, params=params_hist)
        
        if res_hist.status_code == 200:
            data = res_hist.json()
            if 'output1' in data:
                for item in data['output1']:
                    if item.get('dt') and float(item.get('ccld_qty', 0)) > 0:
                        final_result.append({
                            'dt': item['dt'],  # 날짜
                            'pdno': item['pdno'], # 종목코드
                            'prdt_name': item['ovrs_item_name'],
                            'sll_buy_dvsn_cd': item['sll_buy_dvsn_cd'], # 01:매도, 02:매수
                            'ccld_qty': str(int(float(item['ccld_qty']))),
                            'ft_ccld_unpr3': item.get('ovrs_stck_ccld_unpr', '0') # 체결단가
                        })
    except Exception:
        pass

    # --- TRACK B: 체결기준 현재잔고 조회 (CTRP6504R) ---
    # * 목적: 아직 결제일이 안 되어 A트랙에 안 뜨는 '당일/최근 체결분' 확인
    # * 2월 3일 거래(미결제)는 여기서 잡힐 것입니다.
    try:
        headers_bal = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET,
            "tr_id": "CTRP6504R", # 체결기준잔고
            "custtype": "P"
        }
        
        params_bal = {
            "CANO": CANO,
            "ACNT_PRDT_CD": ACNT_PRDT_CD,
            "WCRC_FRCR_DVSN_CD": "01",
            "NATN_CD": "840", # 미국
            "TR_MKET_CD": "00",
            "INQR_DVSN_CD": "00"
        }
        
        res_bal = _request_api('GET', f"{URL_BASE}/uapi/overseas-stock/v1/trading/inquire-present-balance", headers_bal, params=params_bal)
        
        if res_bal.status_code == 200:
            data_bal = res_bal.json()
            if 'output1' in data_bal:
                for item in data_bal['output1']:
                    # 금일 매수 체결 수량(thdt_buy_ccld_qty1) 확인
                    today_buy = float(item.get('thdt_buy_ccld_qty1', 0))
                    
                    if today_buy > 0:
                        # 잔고 API는 날짜를 안 주므로 '오늘'로 가정하고 생성
                        final_result.append({
                            'dt': datetime.now().strftime("%Y%m%d"), 
                            'pdno': item['pdno'],
                            'prdt_name': item['prdt_name'],
                            'sll_buy_dvsn_cd': '02', # 매수
                            'ccld_qty': str(int(today_buy)),
                            'ft_ccld_unpr3': item.get('pchs_avg_pric', '0') # 매입평균가 사용
                        })
    except Exception:
        pass

    return {'output1': final_result}
