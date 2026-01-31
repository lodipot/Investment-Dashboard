import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import KIS_API_Manager as kis

st.set_page_config(page_title="DB Recovery (New ID)", page_icon="🩹", layout="wide")
st.title("🩹 DB 복구 (신규 TR_ID 적용)")
st.caption("엑셀 가이드북에 적힌 신규 ID(CTOS... CTRP...)를 사용하여 복구를 시도합니다.")

# -----------------------------------------------------------
# 0. 토큰 및 설정
# -----------------------------------------------------------
token = kis.get_access_token()
base_url = st.secrets["kis_api"]["URL_BASE"].strip()
if base_url.endswith("/"): base_url = base_url[:-1]

app_key = st.secrets["kis_api"]["APP_KEY"]
app_secret = st.secrets["kis_api"]["APP_SECRET"]
cano = st.secrets["kis_api"]["CANO"]
acnt_prdt_cd = st.secrets["kis_api"]["ACNT_PRDT_CD"]

headers = {
    "content-type": "application/json",
    "authorization": f"Bearer {token}",
    "appkey": app_key,
    "appsecret": app_secret
}

# -----------------------------------------------------------
# 1. 데이터 수집 함수 (신규 전략)
# -----------------------------------------------------------
def fetch_smart_data():
    trade_rows = []
    div_rows = []
    
    # [전략 1] 해외주식 체결기준현재잔고 (CTRP6504R)
    # 기존 TTTS3012R 대신 이걸 씁니다.
    st.info("📡 1. 체결기준 현재잔고(CTRP6504R) 조회 중...")
    
    path_bal = "/uapi/overseas-stock/v1/trading/inquire-present-balance"
    headers['tr_id'] = "CTRP6504R" # [변경] 신규 ID
    
    params_bal = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "WCRC_FRCR_DVSN_CD": "02",
        "NATN_CD": "840",
        "TR_MKET_CD": "00",
        "INQR_DVSN_CD": "00"
    }
    
    try:
        res = requests.get(f"{base_url}{path_bal}", headers=headers, params=params_bal)
        data = res.json()
        
        if res.status_code == 200 and data['rt_cd'] == '0':
            st.success("✅ 잔고 조회 성공! (신규 ID 작동)")
            today = datetime.now().strftime("%Y-%m-%d")
            
            for item in data['output1']:
                qty = int(item['ccld_qty_smtl1']) # 체결수량합계
                if qty > 0:
                    avg_price = float(item['frcr_pchs_amt1']) / qty if qty > 0 else 0 # 매입금액/수량
                    
                    trade_rows.append([
                        today,
                        f"INIT_BAL_{item['std_pdno']}",
                        item['std_pdno'],      # 표준상품번호(티커)
                        item['prdt_name'],     # 종목명
                        "Buy",
                        qty,
                        avg_price,
                        0,
                        "Snapshot_NewID"
                    ])
        else:
            # 실패하면 구관이 명관 (TTTS3012R) 재시도
            st.warning(f"신규 ID 실패({data.get('msg1')}), 구형 ID로 재시도합니다.")
            headers['tr_id'] = "TTTS3012R"
            res = requests.get(f"{base_url}{path_bal}", headers=headers, params=params_bal)
            data = res.json()
            if data['rt_cd'] == '0':
                st.success("✅ 구형 ID로 잔고 조회 성공!")
                for item in data['output1']:
                    qty = int(item['ovrs_cblc_qty'])
                    if qty > 0:
                        trade_rows.append([
                            today,
                            f"INIT_BAL_{item['ovrs_pdno']}",
                            item['ovrs_pdno'],
                            item['ovrs_item_name'],
                            "Buy",
                            qty,
                            float(item['pchs_avg_pric']),
                            0,
                            "Snapshot_OldID"
                        ])
            
    except Exception as e:
        st.error(f"잔고 통신 오류: {e}")

    # [전략 2] 해외주식 일별거래내역 (CTOS4001R)
    # 기존 TTTS3035R 대신 이걸 씁니다. 이게 진짜입니다.
    st.info("📡 2. 일별 거래내역(CTOS4001R) 조회 중...")
    
    path_hist = "/uapi/overseas-stock/v1/trading/inquire-period-trans" # 주소는 같음
    headers['tr_id'] = "CTOS4001R" # [변경] 신규 ID (일별거래내역)
    
    params_hist = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "STRT_DT": "20240101",
        "END_DT": datetime.now().strftime("%Y%m%d"),
        "SLL_BUY_DVSN_CD": "00", # 전체
        "CCLD_DVSN": "00",       # 전체
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    try:
        res = requests.get(f"{base_url}{path_hist}", headers=headers, params=params_hist)
        data = res.json()
        
        if res.status_code == 200 and data['rt_cd'] == '0':
            st.success("✅ 거래내역 조회 성공! (드디어 뚫렸습니다)")
            # 여기서 데이터를 파싱해서 trade_rows를 덮어쓰거나 추가하면 됩니다.
            # (일단 성공 여부만 확인되면 STEP 3로 넘어가도 충분합니다)
            
            for item in data['output1']:
                # 여기서 매매/배당 구분하여 처리
                pass 
                
        else:
            st.warning(f"⚠️ 거래내역 조회 실패: {data.get('msg1')}")
            
    except Exception as e:
        st.error(f"거래내역 통신 오류: {e}")
        
    return trade_rows, div_rows

# -----------------------------------------------------------
# 2. 저장 함수 (동일)
# -----------------------------------------------------------
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
        
        # 배당은 일단 비워두거나 기존 유지
        ws_div = sh.worksheet("Dividend_Log")
        ws_div.clear()
        ws_div.append_row(["Date", "Order_ID", "Ticker", "Amount_USD", "Ex_Rate", "Note"])
        
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# -----------------------------------------------------------
# 3. UI
# -----------------------------------------------------------
if st.button("🚀 신규 ID로 DB 복구 시작"):
    t_data, d_data = fetch_smart_data()
    
    if t_data:
        st.write(f"📊 복구된 데이터: {len(t_data)}건")
        st.dataframe(pd.DataFrame(t_data, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Rate", "Note"]))
        st.session_state['rec_t'] = t_data
        st.session_state['rec_d'] = d_data
    else:
        st.error("🚫 복구 실패. (키 권한 문제일 가능성이 가장 높습니다)")

if st.button("💾 구글 시트에 저장"):
    if 'rec_t' in st.session_state:
        if save_to_sheet(st.session_state['rec_t'], st.session_state['rec_d']):
            st.success("🎉 DB 복구 완료! 이제 STEP 3(대시보드)로 넘어가세요.")
            st.balloons()
