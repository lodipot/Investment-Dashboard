import streamlit as st
import requests
import KIS_API_Manager as kis
import time

st.set_page_config(page_title="KIS API 마스터키", page_icon="🔑", layout="wide")
st.title("🔑 API 주소/ID 전수 조사 (Master Key)")

# 1. 토큰 확보
token = kis.get_access_token()
if not token:
    st.error("❌ 토큰 발급 실패")
    st.stop()

base_url = st.secrets["kis_api"]["URL_BASE"].strip()
if base_url.endswith("/"): base_url = base_url[:-1]

app_key = st.secrets["kis_api"]["APP_KEY"]
app_secret = st.secrets["kis_api"]["APP_SECRET"]
cano = st.secrets["kis_api"]["CANO"]
acnt_prdt_cd = st.secrets["kis_api"]["ACNT_PRDT_CD"]

# 2. 테스트할 조합 (가능성 높은 순서대로)
combinations = [
    # [조합 1] 체결내역(CCLD) - v1
    {"desc": "체결내역(v1)", "ver": "v1", "url": "/trading/inquire-period-ccld", "tr_id": "TTTS3035R"},
    # [조합 2] 체결내역(CCLD) - v2 (가능성 높음)
    {"desc": "체결내역(v2)", "ver": "v2", "url": "/trading/inquire-period-ccld", "tr_id": "TTTS3035R"},
    # [조합 3] 거래내역(TRANS) - v1
    {"desc": "거래내역(v1)", "ver": "v1", "url": "/trading/inquire-period-trans", "tr_id": "TTTS3031R"},
    # [조합 4] 거래내역(TRANS) - ID 변형 (혹시?)
    {"desc": "거래내역(J-ID)", "ver": "v1", "url": "/trading/inquire-period-trans", "tr_id": "JTTT3001R"},
    # [조합 5] 일별 체결내역 - v1
    {"desc": "일별체결(v1)", "ver": "v1", "url": "/trading/inquire-ccld", "tr_id": "TTTS3035R"},
]

if st.button("🚀 마스터키 실행 (전수 조사)"):
    st.write("진단을 시작합니다... (약 5초 소요)")
    found_any = False
    
    for combo in combinations:
        # URL 조립
        path = f"/uapi/overseas-stock/{combo['ver']}{combo['url']}"
        full_url = f"{base_url}{path}"
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": combo['tr_id']
        }
        
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "STRT_DT": "20250120", # 최근 1주일
            "END_DT": "20250131",
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "ERNG_DVSN_CD": "01", # 거래내역용
            "WCRC_FRCR_DVSN_CD": "02" # 거래내역용
        }
        
        try:
            res = requests.get(full_url, headers=headers, params=params)
            
            # 결과 분석
            status = res.status_code
            try:
                data = res.json()
                rt_cd = data.get('rt_cd', '?')
                msg = data.get('msg1', '')
            except:
                rt_cd = 'Err'
                msg = res.text[:50]

            # 404면 주소 없음, 200이어도 rt_cd가 0이 아니면 실패
            if status == 200 and rt_cd == '0':
                st.success(f"🎉 **찾았다! [{combo['desc']}]**")
                st.write(f"👉 **URL:** `{path}`")
                st.write(f"👉 **TR_ID:** `{combo['tr_id']}`")
                st.json(data) # 데이터 보여주기
                found_any = True
                break # 찾으면 즉시 중단
            
            elif status == 200:
                st.warning(f"⚠️ [{combo['desc']}] 접속은 되나 에러: {msg} (코드: {rt_cd})")
                # st.write(f"URL: {path}")
            
            else:
                st.caption(f"❌ [{combo['desc']}] 실패 ({status})")
                
        except Exception as e:
            st.error(f"통신 오류: {e}")
            
        time.sleep(0.5)
        
    if not found_any:
        st.error("🚫 모든 조합이 실패했습니다. (API 서비스 신청 상태를 다시 확인해야 할 수도 있습니다.)")
    else:
        st.balloons()
