import streamlit as st
import pandas as pd
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# [중요] STEP 1에서 만든 매니저 활용
import KIS_API_Manager as kis

st.set_page_config(page_title="DB Migration Tool", page_icon="🛠️", layout="wide")

st.title("🛠️ DB 마이그레이션 (초기화) 도구")
st.warning("⚠️ 이 도구는 구글 시트의 [Trade_Log]와 [Dividend_Log]를 API 데이터로 **완전히 덮어씁니다.** 백업을 권장합니다.")

# -----------------------------------------------------------
# 1. API 데이터 수집 함수
# -----------------------------------------------------------
# [수정된 함수] 에러 내용을 보여주는 디버깅 버전
def fetch_api_data():
    token = kis.get_access_token()
    if not token:
        st.error("토큰 발급 실패. secrets.toml 설정을 확인하세요.")
        return None, None

    base_url = st.secrets["kis_api"]["URL_BASE"]
    # [중요] URL 뒤에 슬래시가 있다면 제거
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
        "tr_id": "TTTS3035R" # 해외주식 체결내역 조회 (기간)
    }
    
    # (1) 매매 내역 조회
    start_dt = "20250101"
    end_dt = datetime.now().strftime("%Y%m%d")
    
    trade_list = []
    
    next_key = ""
    for i in range(5):
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "STRT_DT": start_dt,
            "END_DT": end_dt,
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_DVSN": "00",
            "CTX_AREA_FK100": next_key,
            "CTX_AREA_NK100": ""
        }
        
        # [디버깅] 요청 URL 확인
        full_url = f"{base_url}/uapi/overseas-stock/v1/trading/inquire-period-ccld"
        
        try:
            res = requests.get(full_url, headers=headers, params=params)
            
            # [수정] JSON 변환 전에 에러 체크
            if res.status_code != 200:
                st.error(f"❌ API 요청 실패 (Status: {res.status_code})")
                st.code(res.text) # 에러 내용 출력
                return None, None
                
            data = res.json()
        except Exception as e:
            st.error(f"❌ 데이터 파싱 오류 (JSONDecodeError)")
            st.write("▼ 서버가 보낸 응답 내용 (이걸 확인해보세요):")
            st.code(res.text) # HTML 에러 페이지가 올 경우 확인 가능
            return None, None
        
        if data['rt_cd'] != '0':
            st.error(f"매매내역 조회 실패: {data['msg1']}")
            st.write(f"Message Code: {data['msg_cd']}")
            break
            
        for item in data['output1']:
            dt_str = item['ord_dt']
            date_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
            ticker = item['pdno']
            name = item['prdt_name']
            qty = int(item['ft_ccld_qty'])
            price = float(item['ft_ccld_unpr3'])
            type_raw = item['sll_buy_dvsn_cd']
            trade_type = "Buy" if type_raw == '02' else "Sell"
            order_id = f"{item['ord_dt']}_{item['ord_no']}"
            
            trade_list.append([
                date_fmt, order_id, ticker, name, trade_type, qty, price, 0, "API_Init"
            ])
            
        next_key = data.get('ctx_area_fk100', '').strip()
        if not next_key: break
        time.sleep(0.2)

    # (2) 배당 내역 조회
    headers['tr_id'] = "TTTS3031R"
    div_list = []
    
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
        res_div = requests.get(f"{base_url}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers=headers, params=params_div)
        data_div = res_div.json()
        
        if data_div['rt_cd'] == '0':
            for item in data_div['output']:
                if "배당" in item['tr_nm'] and float(item['frcr_amt']) > 0:
                    dt_str = item['tr_dt']
                    date_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                    ticker = item['ovrs_pdno']
                    amount = float(item['frcr_amt'])
                    
                    ex_rate = 1450.0
                    if ticker == 'O' and '2026-01-1' in date_fmt:
                        ex_rate = 1469.7
                    
                    div_id = f"{item['tr_dt']}_{item['tr_no']}"
                    div_list.append([date_fmt, div_id, ticker, amount, ex_rate, "API_Init"])
    except Exception as e:
        st.error(f"배당 내역 조회 중 오류: {e}")
    
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
        
        # Trade_Log 덮어쓰기
        ws_trade = sh.worksheet("Trade_Log")
        ws_trade.clear() # 전체 삭제
        # 헤더 다시 쓰기
        ws_trade.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Exchange_Rate", "Note"])
        if trade_data:
            ws_trade.append_rows(trade_data)
        
        # Dividend_Log 덮어쓰기
        ws_div = sh.worksheet("Dividend_Log")
        ws_div.clear()
        ws_div.append_row(["Date", "Order_ID", "Ticker", "Amount_USD", "Ex_Rate", "Note"])
        if div_data:
            ws_div.append_rows(div_data)
            
        return True
    except Exception as e:
        st.error(f"구글 시트 저장 오류: {e}")
        return False

# -----------------------------------------------------------
# 3. UI 구성
# -----------------------------------------------------------
if st.button("1. KIS API 데이터 불러오기 (미리보기)"):
    with st.spinner("API 조회 중..."):
        t_data, d_data = fetch_api_data()
        
        if t_data is not None:
            st.success("조회 성공!")
            
            st.subheader(f"📋 매매 내역 ({len(t_data)}건)")
            df_t = pd.DataFrame(t_data, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Rate", "Note"])
            st.dataframe(df_t)
            
            st.subheader(f"💰 배당 내역 ({len(d_data)}건)")
            if d_data:
                df_d = pd.DataFrame(d_data, columns=["Date", "ID", "Ticker", "Amount", "Rate", "Note"])
                st.dataframe(df_d)
            else:
                st.info("조회된 배당 내역이 없습니다.")
            
            # 세션에 데이터 임시 저장
            st.session_state['mig_trade'] = t_data
            st.session_state['mig_div'] = d_data

if st.button("2. 구글 시트에 덮어쓰기 (실행)"):
    if 'mig_trade' in st.session_state and st.session_state['mig_trade'] is not None:
        with st.spinner("데이터 저장 중..."):
            if save_to_sheet(st.session_state['mig_trade'], st.session_state['mig_div']):
                st.success("✅ DB 교체 완료! 이제 Dashboard.py를 원래대로(Step 3) 복구하세요.")
                st.balloons()
    else:
        st.warning("먼저 '데이터 불러오기'를 실행해주세요.")
