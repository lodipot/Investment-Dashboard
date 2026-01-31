import streamlit as st
import requests
import KIS_API_Manager as kis
import time

st.set_page_config(page_title="KIS API 탐색기", page_icon="🧭", layout="wide")
st.title("🧭 해외주식 API 주소 정밀 탐색")

# 1. 토큰 확보
st.subheader("1. 접속 권한 확인")
token = kis.get_access_token()
if not token:
    st.error("❌ 토큰 발급 실패")
    st.stop()
else:
    st.success("✅ 토큰 확보 완료")

# 2. 주소 탐색 시작
st.subheader("2. 유효한 거래내역 주소 찾기")

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
    "appsecret": app_secret,
    "tr_id": "TTTS3035R" # 기본 ID
}

# 테스트할 주소 후보군 (가능성 높은 순)
candidates = [
    # [A] 기간별 체결내역 (가장 유력)
    ("/uapi/overseas-stock/v1/trading/inquire-period-ccld", "TTTS3035R", "기간별 체결내역"),
    
    # [B] 일별 체결내역 (대안)
    ("/uapi/overseas-stock/v1/trading/inquire-ccld", "TTTS3035R", "일별 체결내역(CCLD)"),
    
    # [C] 거래내역 (입출금/배당 등) - TR_ID 다름
    ("/uapi/overseas-stock/v1/trading/inquire-period-trans", "TTTS3031R", "기간별 거래내역(TRANS)"),
    
    # [D] 잔고 조회 (이건 되나?)
    ("/uapi/overseas-stock/v1/trading/inquire-present-balance", "TTTS3012R", "실시간 잔고"),
    
    # [E] 현재가 (대조군 - 이건 돼야 정상)
    ("/uapi/overseas-price/v1/quotations/price", "HHDFS00000300", "현재가(Price)"),
]

if st.button("🚀 주소 전수 조사 시작"):
    success_count = 0
    
    for path, tr_id, desc in candidates:
        full_url = f"{base_url}{path}"
        
        # TR_ID 교체
        headers['tr_id'] = tr_id
        
        # 파라미터 (공통적으로 쓰이는 것들)
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "STRT_DT": "20250129", # 최근 평일
            "END_DT": "20250130",
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            # 현재가용 파라미터
            "AUTH": "", "EXCD": "NAS", "SYMB": "AAPL",
            # 잔고용 파라미터
            "WCRC_FRCR_DVSN_CD": "02", "OVRS_EXCG_CD": "NAS"
        }
        
        try:
            res = requests.get(full_url, headers=headers, params=params)
            
            st.write(f"📡 **[{desc}]** 시도 중...")
            st.caption(f"주소: `{path}`")
            
            if res.status_code == 200:
                st.success(f"🎉 **성공! (200 OK)**")
                st.json(res.json()) # 데이터 확인
                success_count += 1
            elif res.status_code == 404:
                st.error("❌ 실패 (404 Not Found) - 주소 없음")
            else:
                st.warning(f"⚠️ 접근 가능하나 에러 ({res.status_code})")
                st.write(f"메시지: {res.text}")
                
        except Exception as e:
            st.error(f"통신 오류: {e}")
            
        st.divider()
        time.sleep(0.5)
        
    if success_count == 0:
        st.error("🚫 모든 주소가 실패했습니다. 계좌가 '해외주식 거래' 미등록 상태이거나 API 설정 문제입니다.")
    else:
        st.balloons()
        st.success("✅ 유효한 주소를 찾았습니다! 위에서 '성공'한 주소를 기억해주세요.")
