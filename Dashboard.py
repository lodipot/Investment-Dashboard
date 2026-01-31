import streamlit as st
import pandas as pd
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# STEP 1에서 만든 매니저 활용
import KIS_API_Manager as kis

st.set_page_config(page_title="DB Migration Tool", page_icon="🛠️", layout="wide")

st.title("🛠️ DB 마이그레이션 (주소 자동 탐지)")
st.warning("⚠️ 404 에러 해결을 위해 여러 주소를 자동으로 시도합니다.")

# -----------------------------------------------------------
# 1. API 데이터 수집 함수 (스마트 탐지 기능 추가)
# -----------------------------------------------------------
def fetch_api_data():
    token = kis.get_access_token()
    if not token:
        st.error("토큰 발급 실패. secrets.toml 설정을 확인하세요.")
        return None, None

    base_url = st.secrets["kis_api"]["URL_BASE"]
    if base_url.endswith("/"): base_url = base_url[:-1]

    app_key = st.secrets["kis_api"]["APP_KEY"]
    app_secret = st.secrets["kis_api"]["APP_SECRET"]
    cano = st.secrets["kis_api"]["CANO"]
    acnt_prdt_cd = st.secrets["kis_api"]["ACNT_PRDT_CD"]
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "TTTS3035R" # 기본값: 해외주식 기간별 체결내역
    }
    
    start_dt = "20250101"
    end_dt = datetime.now().strftime("%Y%m%d")
    
    # -------------------------------------------------------
    # [1] 매매 내역 주소 탐지 (Probe)
    # -------------------------------------------------------
    # 가능한 주소 후보군
    candidate_urls = [
        "/uapi/overseas-stock/v1/trading/inquire-period-ccld", # 1순위 (기간별)
        "/uapi/overseas-stock/v1/trading/inquire-ccld",        # 2순위 (체결내역)
    ]
    
    trade_list = []
    success_url = ""
    
    for url_path in candidate_urls:
        full_url = f"{base_url}{url_path}"
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "STRT_DT": start_dt,
            "END_DT": end_dt,
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = requests.get(full_url, headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if 'output1' in data: # 데이터 구조가 맞는지 확인
                    success_url = url_path
                    st.success(f"✅ 매매내역 주소 찾음: {url_path}")
                    break # 찾았으면 루프 종료
        except:
            continue
            
    if not success_url:
        st.error(f"❌ 매매내역 조회 실패 (404/500). API 설정을 확인해주세요.")
        return None, None

    # 찾은 주소로 진짜 데이터 수집 (페이지네이션)
    next_key = ""
    for _ in range(5):
        params['CTX_AREA_FK100'] = next_key
        res = requests.get(f"{base_url}{success_url}", headers=headers, params=params)
        data = res.json()
        
        if data['rt_cd'] != '0':
            st.error(f"조회 실패 메시지: {data['msg1']}")
            break
            
        for item in data['output1']:
            dt_str = item['ord_dt']
            date_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
            ticker = item['pdno']
            name = item['prdt_name']
            qty = int(item['ft_ccld_qty'])
            price = float(item['ft_ccld_unpr3'])
            type_raw = item['sll_buy_dvsn_cd'] # 01:매도, 02:매수
            trade_type = "Buy" if type_raw == '02' else "Sell"
            order_id = f"{item['ord_dt']}_{item['ord_no']}"
            
            trade_list.append([
                date_fmt, order_id, ticker, name, trade_type, qty, price, 0, "API_Init"
            ])
        
        next_key = data.get('ctx_area_fk100', '').strip()
        if not next_key: break
        time.sleep(0.2)

    # -------------------------------------------------------
    # [2] 배당 내역 조회 (거래내역 TR)
    # -------------------------------------------------------
    # 주소 후보군 (거래내역)
    div_candidates = [
        "/uapi/overseas-stock/v1/trading/inquire-period-trans", # 1순위
        "/uapi/overseas-stock/v1/trading/inquire-trans",        # 2순위
    ]
    
    headers['tr_id'] = "TTTS3031R" # 해외주식 거래내역
    div_list = []
    
    for div_path in div_candidates:
        full_url = f"{base_url}{div_path}"
        params_div = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "STRT_DT": start_dt,
            "END_DT": end_dt,
            "ERNG_DVSN_CD": "01",
            "WCRC_FRCR_DVSN_CD": "02",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        try:
            res_div = requests.get(full_url, headers=headers, params=params_div)
            if res_div.status_code == 200:
                data_div = res_div.json()
                if 'output' in data_div:
                    st.success(f"✅ 배당내역 주소 찾음: {div_path}")
                    
                    for item in data_div['output']:
                        if "배당" in item['tr_nm'] and float(item['frcr_amt']) > 0:
                            dt_str = item['tr_dt']
                            date_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                            ticker = item['ovrs_pdno']
                            amount = float(item['frcr_amt'])
                            
                            # [환율 하드코딩 적용] 리얼티인컴 1월 16일
                            ex_rate = 1450.0
                            if ticker == 'O' and '2026-01-1' in date_fmt:
                                ex_rate = 1469.7
                            
                            div_id = f"{item['tr_dt']}_{item['tr_no']}"
                            div_list.append([date_fmt, div_id, ticker, amount, ex_rate, "API_Init"])
                    break # 성공 시 루프 종료
        except:
            continue
            
    return trade_list, div_list

# -----------------------------------------------------------
# 2. 구글 시트 저장 함수
# -----------------------------------------------------------
def save_to_sheet(trade_data, div_data):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")
        
        ws_trade = sh.worksheet("Trade_Log")
        ws_trade.clear()
        ws_trade.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Exchange_Rate", "Note"])
        if trade_data: ws_trade.append_rows(trade_data)
        
        ws_div = sh.worksheet("Dividend_Log")
        ws_div.clear()
        ws_div.append_row(["Date", "Order_ID", "Ticker", "Amount_USD", "Ex_Rate", "Note"])
        if div_data: ws_div.append_rows(div_data)
            
        return True
    except Exception as e:
        st.error(f"구글 시트 저장 오류: {e}")
        return False

# -----------------------------------------------------------
# 3. UI
# -----------------------------------------------------------
if st.button("1. KIS API 데이터 불러오기 (주소 자동 탐지)"):
    with st.spinner("서버 주소를 탐색하며 조회 중..."):
        t_data, d_data = fetch_api_data()
        
        if t_data is not None:
            st.subheader(f"📋 매매 내역 ({len(t_data)}건)")
            df_t = pd.DataFrame(t_data, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Rate", "Note"])
            st.dataframe(df_t)
            
            st.subheader(f"💰 배당 내역 ({len(d_data)}건)")
            if d_data:
                df_d = pd.DataFrame(d_data, columns=["Date", "ID", "Ticker", "Amount", "Rate", "Note"])
                st.dataframe(df_d)
            
            st.session_state['mig_trade'] = t_data
            st.session_state['mig_div'] = d_data

if st.button("2. 구글 시트에 덮어쓰기 (실행)"):
    if 'mig_trade' in st.session_state:
        if save_to_sheet(st.session_state['mig_trade'], st.session_state['mig_div']):
            st.success("✅ DB 교체 완료! STEP 3(정규 대시보드) 코드를 적용하세요.")
            st.balloons()
    else:
        st.warning("먼저 데이터를 불러와주세요.")
