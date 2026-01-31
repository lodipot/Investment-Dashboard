import streamlit as st
import requests
import KIS_API_Manager as kis

st.set_page_config(page_title="KIS API 정밀진단", page_icon="🚑", layout="wide")
st.title("🚑 KIS API 접속 정밀 진단")

# 1. 설정값 검증
st.subheader("1. 설정값 검증 (secrets.toml)")

try:
    base_url = st.secrets["kis_api"]["URL_BASE"].strip() # 공백 제거
    app_key = st.secrets["kis_api"]["APP_KEY"].strip()
    app_secret = st.secrets["kis_api"]["APP_SECRET"].strip()
    cano = str(st.secrets["kis_api"]["CANO"]).strip() # 문자열 강제 변환
    acnt_prdt_cd = str(st.secrets["kis_api"]["ACNT_PRDT_CD"]).strip()
    
    # URL 끝 슬래시 제거
    if base_url.endswith("/"): base_url = base_url[:-1]
    
    st.write(f"🔹 **URL_BASE:** `{base_url}`")
    st.write(f"🔹 **계좌번호:** `{cano}-{acnt_prdt_cd}`")
    st.success("✅ 설정값 포맷은 정상입니다.")
    
except Exception as e:
    st.error(f"❌ 설정 불러오기 실패: {e}")
    st.stop()

# 2. 토큰 상태 확인
st.subheader("2. 접근 토큰 상태")
token = kis.get_access_token()
if token:
    st.success(f"✅ 토큰 확보 완료 (앞 10자리: {token[:10]}...)")
else:
    st.error("❌ 토큰 발급 실패. 앱 키/시크릿을 확인하세요.")
    st.stop()

# 3. API 강제 호출 (가장 기본적인 URL)
st.subheader("3. 서버 응답 테스트")

# 테스트할 정확한 경로 (해외주식 기간별 체결내역)
path = "/uapi/overseas-stock/v1/trading/inquire-period-ccld"
full_url = f"{base_url}{path}"

st.write(f"📡 **요청 주소:** `{full_url}`")

headers = {
    "content-type": "application/json",
    "authorization": f"Bearer {token}",
    "appkey": app_key,
    "appsecret": app_secret,
    "tr_id": "TTTS3035R" # 실전투자용 TR ID
}

params = {
    "CANO": cano,
    "ACNT_PRDT_CD": acnt_prdt_cd,
    "STRT_DT": "20250101",
    "END_DT": "20250131",
    "SLL_BUY_DVSN_CD": "00",
    "CCLD_DVSN": "00",
    "CTX_AREA_FK100": "",
    "CTX_AREA_NK100": ""
}

if st.button("🚨 진단 요청 보내기"):
    try:
        res = requests.get(full_url, headers=headers, params=params)
        
        st.write(f"**상태 코드:** `{res.status_code}`")
        
        if res.status_code == 200:
            st.success("🎉 성공! 데이터가 들어왔습니다.")
            st.json(res.json())
        else:
            st.error("❌ 요청 실패")
            st.write("▼ **서버가 보낸 응답 본문 (Raw Text):**")
            st.code(res.text) # 여기에 진짜 에러 원인이 적혀 있음
            
            st.write("▼ **응답 헤더 (Headers):**")
            st.json(dict(res.headers))
            
    except Exception as e:
        st.error(f"통신 에러 발생: {e}")
