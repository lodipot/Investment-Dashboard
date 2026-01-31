import streamlit as st
import pandas as pd
import requests
import KIS_API_Manager as kis

st.set_page_config(page_title="잔고 조회 테스트", page_icon="💰", layout="wide")
st.title("💰 실시간 잔고(Balance) 조회 테스트")

token = kis.get_access_token()
base_url = st.secrets["kis_api"]["URL_BASE"]
if base_url.endswith("/"): base_url = base_url[:-1]

app_key = st.secrets["kis_api"]["APP_KEY"]
app_secret = st.secrets["kis_api"]["APP_SECRET"]
cano = st.secrets["kis_api"]["CANO"]
acnt_prdt_cd = st.secrets["kis_api"]["ACNT_PRDT_CD"]

if st.button("내 계좌 잔고 가져오기"):
    # 해외주식 잔고 조회 (TTTS3012R)
    path = "/uapi/overseas-stock/v1/trading/inquire-present-balance"
    full_url = f"{base_url}{path}"
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "TTTS3012R" # 실시간 잔고
    }
    
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "WCRC_FRCR_DVSN_CD": "02", # 01:원화, 02:외화
        "NATN_CD": "840",          # 840:미국
        "TR_MKET_CD": "00",        # 전체
        "INQR_DVSN_CD": "00"       # 전체
    }
    
    try:
        res = requests.get(full_url, headers=headers, params=params)
        data = res.json()
        
        if res.status_code == 200 and data['rt_cd'] == '0':
            st.success("🎉 잔고 조회 성공! (API 권한 살아있음)")
            
            # 1. 주식 잔고
            if 'output1' in data:
                rows = []
                for item in data['output1']:
                    rows.append({
                        "종목": item['ovrs_pdno'],     # 티커
                        "명칭": item['ovrs_item_name'], # 종목명
                        "수량": item['ovrs_cblc_qty'],  # 잔고수량
                        "평가손익": item['frcr_evlu_pfls_amt'], # 외화평가손익
                        "수익률": item['evlu_pfls_rt']  # 수익률
                    })
                st.subheader("1. 보유 주식")
                st.dataframe(pd.DataFrame(rows))
                
            # 2. 예수금(현금) 잔고
            if 'output2' in data:
                cash = data['output2']
                st.subheader("2. 계좌 현황")
                st.write(f"💵 외화 예수금: **${float(cash['frcr_dncl_amt_2']):,.2f}**")
                st.write(f"📅 조회 기준일: {cash['tr_dt']}")
                
        else:
            st.error(f"❌ 조회 실패: {data['msg1']} (Code: {data['msg_cd']})")
            st.warning("👉 이 경우 '해외주식 주문/조회' 서비스 신청이 안 된 상태입니다.")
            st.info("해결책: KIS Developers 사이트 > 마이페이지 > API 키 삭제 후 '재발급' (주문/조회 권한 체크)")
            
    except Exception as e:
        st.error(f"오류 발생: {e}")
