import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import KIS_API_Manager as kis

st.set_page_config(page_title="DB Recovery Real-Final", page_icon="🚑", layout="wide")
st.title("🚑 DB 복구 (필드명 정밀 수정)")
st.caption("발견된 36건의 데이터를 정확한 필드명으로 파싱하여 복구합니다.")

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
# 1. 데이터 수집 함수 (필드명 교체 적용)
# -----------------------------------------------------------
def fetch_final_data():
    trade_rows = []
    
    st.info("📡 1. 일별 거래내역(CTOS4001R) 조회 및 파싱 중...")
    
    path_hist = "/uapi/overseas-stock/v1/trading/inquire-period-trans"
    headers['tr_id'] = "CTOS4001R" 
    
    params_hist = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "ERLM_STRT_DT": "20240101", # 시작일
        "ERLM_END_DT": datetime.now().strftime("%Y%m%d"), # 종료일
        "SLL_BUY_DVSN_CD": "00", # 전체
        "CCLD_DVSN": "00",       # 전체
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    try:
        res = requests.get(f"{base_url}{path_hist}", headers=headers, params=params_hist)
        data = res.json()
        
        if res.status_code == 200 and data['rt_cd'] == '0':
            items = data['output1']
            st.success(f"✅ 거래내역 조회 성공! (총 {len(items)}건 발견)")
            
            # [디버깅] 첫 번째 데이터 구조 확인용 (필요시 주석 해제)
            # if items: st.write("첫 번째 데이터 샘플:", items[0])

            for item in items:
                # 1. 날짜 (trad_dt 우선 사용)
                dt_str = item.get('trad_dt')
                if not dt_str: dt_str = item.get('tr_dt') # 혹시 몰라 예비용
                if not dt_str: dt_str = datetime.now().strftime("%Y%m%d") # 최악의 경우 오늘
                
                dt_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                
                # 2. 거래 구분 (매수/매도)
                # sll_buy_dvsn_cd: 01(매도), 02(매수)
                dvsn_cd = item.get('sll_buy_dvsn_cd', '')
                dvsn_name = item.get('sll_buy_dvsn_name', '') # 매수/매도 텍스트
                
                # 3. 상세 정보
                ticker = item.get('pdno', '')
                name = item.get('ovrs_item_name', '')
                
                # 수량 (ccld_qty)
                qty = int(float(item.get('ccld_qty', '0')))
                
                # 단가 (ft_ccld_unpr2 또는 ovrs_stck_ccld_unpr)
                price = float(item.get('ft_ccld_unpr2', '0'))
                if price == 0: price = float(item.get('ovrs_stck_ccld_unpr', '0'))
                
                # 환율 (일단 0으로, 추후 보정 가능)
                rate = 0.0 

                # DB 행 생성 (매수/매도인 경우만 Trade_Log에 추가)
                if dvsn_cd in ['01', '02'] or '매수' in dvsn_name or '매도' in dvsn_name:
                    type_str = "Buy" if (dvsn_cd == '02' or '매수' in dvsn_name) else "Sell"
                    
                    trade_rows.append([
                        dt_fmt,
                        f"{dt_str}_{ticker}_{qty}", # 고유 ID (날짜_티커_수량)
                        ticker,
                        name,
                        type_str,
                        qty,
                        price,
                        rate,
                        f"API_{dvsn_name}" # 비고란에 원문 기록
                    ])
                    
        else:
            st.error(f"API 응답 오류: {data.get('msg1')}")
            st.write(data) # 에러 시 내용 출력

    except Exception as e:
        st.error(f"파싱 중 오류 발생: {e}")

    # [비상대책] 거래내역이 비어있으면 잔고라도 가져옴 (CTRP6504R)
    if not trade_rows:
        st.warning("⚠️ 거래내역 파싱 실패. '현재 잔고'를 가져옵니다.")
        headers['tr_id'] = "CTRP6504R"
        params_bal = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
            "WCRC_FRCR_DVSN_CD": "02", "NATN_CD": "840", "TR_MKET_CD": "00", "INQR_DVSN_CD": "00"
        }
        try:
            res = requests.get(f"{base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance", headers=headers, params=params_bal)
            data = res.json()
            if data['rt_cd'] == '0':
                today = datetime.now().strftime("%Y-%m-%d")
                for item in data['output1']:
                    qty = int(float(item.get('ccld_qty_smtl1', '0')))
                    if qty > 0:
                        buy_amt = float(item.get('frcr_pchs_amt1', '0'))
                        avg_price = buy_amt / qty if qty > 0 else 0
                        trade_rows.append([
                            today, f"INIT_BAL_{item['std_pdno']}", item['std_pdno'], 
                            item['prdt_name'], "Buy", qty, avg_price, 0, "Snapshot_Auto"
                        ])
        except: pass

    return trade_rows

# -----------------------------------------------------------
# 2. 저장 함수 (구글 시트)
# -----------------------------------------------------------
def save_to_sheet(t_data):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")
        
        ws_trade = sh.worksheet("Trade_Log")
        ws_trade.clear()
        ws_trade.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Exchange_Rate", "Note"])
        
        if t_data: 
            ws_trade.append_rows(t_data)
        
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# -----------------------------------------------------------
# 3. UI 실행
# -----------------------------------------------------------
if st.button("🚀 데이터 불러오기 (최종 검증)"):
    t_data = fetch_final_data()
    
    if t_data:
        # 데이터프레임으로 변환하여 예쁘게 보여줌
        df = pd.DataFrame(t_data, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Rate", "Note"])
        st.success(f"🎉 데이터 {len(t_data)}건 확보 완료!")
        st.dataframe(df) # 여기서 눈으로 확인하세요!
        
        # 세션에 저장 (저장 버튼 활성화용)
        st.session_state['rec_t'] = t_data
    else:
        st.error("데이터를 가져오지 못했습니다.")

if st.button("💾 구글 시트에 저장 (실행)"):
    if 'rec_t' in st.session_state:
        if save_to_sheet(st.session_state['rec_t']):
            st.balloons()
            st.success("🏆 DB 복구 완료! 이제 대시보드를 완성(STEP 3)하세요.")
    else:
        st.warning("먼저 '데이터 불러오기'를 눌러 확인해주세요.")
