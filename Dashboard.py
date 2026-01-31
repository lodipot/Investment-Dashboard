import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import KIS_API_Manager as kis

st.set_page_config(page_title="DB Recovery Final", page_icon="🚑", layout="wide")
st.title("🚑 DB 복구 (오류 수정 및 파싱 완료)")
st.caption("성공한 신규 ID(CTOS4001R)를 사용하여 데이터를 수집하고 파싱합니다.")

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
# 1. 데이터 수집 함수 (버그 수정판)
# -----------------------------------------------------------
def fetch_final_data():
    trade_rows = []
    div_rows = []
    
    # [1] 거래 내역 (CTOS4001R) - 드디어 성공한 그 녀석
    st.info("📡 1. 일별 거래내역(CTOS4001R) 조회 및 파싱 중...")
    
    path_hist = "/uapi/overseas-stock/v1/trading/inquire-period-trans"
    headers['tr_id'] = "CTOS4001R" 
    
    # 조회 기간: 넉넉하게 2024년 1월 1일부터
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
            st.success(f"✅ 거래내역 조회 성공! (총 {len(data['output1'])}건 발견)")
            
            for item in data['output1']:
                # 날짜 포맷 (YYYYMMDD -> YYYY-MM-DD)
                dt_str = item['trad_dt'] # 필드명 주의 (tr_dt가 아니라 trad_dt 일 수 있음)
                if not dt_str: dt_str = item.get('tr_dt', datetime.now().strftime("%Y%m%d"))
                dt_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                
                # 공통 정보
                ticker = item.get('pdno', '') # 종목코드
                name = item.get('ovrs_item_name', '') # 종목명
                
                # 구분 (매수/매도/배당)
                # sll_buy_dvsn_cd: 01(매도), 02(매수)
                dvsn = item.get('sll_buy_dvsn_cd', '')
                tr_name = item.get('tr_nm', '') # 거래명 (배당 확인용)
                
                # --- A. 매매 내역 파싱 ---
                if dvsn in ['01', '02']: 
                    t_type = "Buy" if dvsn == '02' else "Sell"
                    
                    # [수정] float 변환 후 int (3.0000 -> 3)
                    qty_raw = item.get('ccld_qty', '0')
                    qty = int(float(qty_raw))
                    
                    price_raw = item.get('ft_ccld_unpr3', '0') # 체결단가
                    if float(price_raw) == 0: price_raw = item.get('ovrs_stck_ccld_unpr', '0')
                    price = float(price_raw)
                    
                    if qty > 0:
                        trade_rows.append([
                            dt_fmt,
                            f"{dt_str}_{ticker}_{qty}", # 임시 ID
                            ticker,
                            name,
                            t_type,
                            qty,
                            price,
                            0,
                            "API_History"
                        ])

                # --- B. 배당 내역 파싱 ---
                # (CTOS4001R에 배당이 같이 나오는지 확인 필요, 보통은 같이 나옴)
                # 만약 안 나오면 아래 잔고 조회 로직은 유지
                if "배당" in tr_name: # 거래명에 '배당'이 있으면
                    amt_raw = item.get('frcr_amt', '0') # 외화금액
                    if float(amt_raw) == 0: amt_raw = item.get('tr_frcr_amt', '0')
                    amount = float(amt_raw)
                    
                    if amount > 0:
                        ex_rate = 1450.0
                        # [하드코딩] 리얼티인컴
                        if ticker == 'O' and '2026-01-1' in dt_fmt: ex_rate = 1469.7
                        
                        div_rows.append([
                            dt_fmt,
                            f"{dt_str}_{ticker}_DIV",
                            ticker,
                            amount,
                            ex_rate,
                            "API_History"
                        ])
                        
        else:
            st.warning(f"거래내역 응답 코드 확인 필요: {data.get('msg1')}")

    except Exception as e:
        st.error(f"거래내역 파싱 오류: {e}")

    # [2] 잔고 조회 (CTRP6504R) - 만약 내역이 비었을 때를 대비한 보험
    if not trade_rows:
        st.warning("⚠️ 거래내역이 없거나 파싱되지 않아 '잔고'로 대체합니다.")
        st.info("📡 2. 체결기준 잔고(CTRP6504R) 조회 중...")
        
        path_bal = "/uapi/overseas-stock/v1/trading/inquire-present-balance"
        headers['tr_id'] = "CTRP6504R"
        
        params_bal = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
            "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "840",
            "TR_MKET_CD": "00", "INQR_DVSN_CD": "00"
        }
        
        try:
            res = requests.get(f"{base_url}{path_bal}", headers=headers, params=params_bal)
            data = res.json()
            
            if data['rt_cd'] == '0':
                today = datetime.now().strftime("%Y-%m-%d")
                for item in data['output1']:
                    # [수정] 여기서 에러 났던 부분! (int 형변환 수정)
                    qty_raw = item.get('ccld_qty_smtl1', '0')
                    qty = int(float(qty_raw)) # 3.0000 -> 3.0 -> 3
                    
                    if qty > 0:
                        # 매입금액 / 수량 = 평단가
                        buy_amt = float(item.get('frcr_pchs_amt1', '0'))
                        avg_price = buy_amt / qty if qty > 0 else 0
                        
                        trade_rows.append([
                            today,
                            f"INIT_BAL_{item['std_pdno']}",
                            item['std_pdno'],
                            item['prdt_name'],
                            "Buy",
                            qty,
                            avg_price,
                            0,
                            "Snapshot_Auto"
                        ])
                        
        except Exception as e:
            st.error(f"잔고 조회 오류: {e}")

    return trade_rows, div_rows

# -----------------------------------------------------------
# 2. 저장 함수
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
        
        ws_div = sh.worksheet("Dividend_Log")
        ws_div.clear()
        ws_div.append_row(["Date", "Order_ID", "Ticker", "Amount_USD", "Ex_Rate", "Note"])
        if d_data: ws_div.append_rows(d_data)
        
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# -----------------------------------------------------------
# 3. UI 실행
# -----------------------------------------------------------
if st.button("🚀 최종 데이터 불러오기"):
    t_data, d_data = fetch_final_data()
    
    if t_data:
        st.success(f"🎉 성공! 매매 데이터 {len(t_data)}건 확보.")
        st.dataframe(pd.DataFrame(t_data, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Rate", "Note"]))
        st.session_state['rec_t'] = t_data
        st.session_state['rec_d'] = d_data
        
        if d_data:
            st.info(f"💰 배당 데이터 {len(d_data)}건 확보.")
            st.dataframe(pd.DataFrame(d_data, columns=["Date", "ID", "Ticker", "Amount", "Rate", "Note"]))
    else:
        st.error("🚫 데이터 확보 실패. (로그를 확인해주세요)")

if st.button("💾 구글 시트에 저장 (복구 완료)"):
    if 'rec_t' in st.session_state:
        if save_to_sheet(st.session_state['rec_t'], st.session_state['rec_d']):
            st.balloons()
            st.success("🏆 DB 복구 및 재구축이 완료되었습니다! 이제 Dashboard.py를 STEP 3로 교체하세요.")
    else:
        st.warning("데이터를 먼저 불러와주세요.")
