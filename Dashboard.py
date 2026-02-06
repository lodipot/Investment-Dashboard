    # [진단 키트 시작] -------------------------------------------------------
    with st.expander("🩺 API 데이터 엑스레이 (디버깅용)", expanded=True):
        col_d1, col_d2 = st.columns([1, 3])
        if col_d1.button("데이터 강제 조회"):
            # 1. 토큰 확보
            token = kis.get_access_token()
            st.write(f"🔑 토큰 상태: {'확보 완료' if token else '실패'}")
            
            # 2. 헤더 및 요청 설정 (TTTS3012R - 기간별 체결)
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {token}",
                "appkey": st.secrets["kis_api"]["APP_KEY"],
                "appsecret": st.secrets["kis_api"]["APP_SECRET"],
                "tr_id": "TTTS3012R",  # 기간별 체결내역
                "custtype": "P"
            }
            
            # 3. 날짜 설정 (2월 1일부터 오늘까지 강제 지정)
            params = {
                "CANO": st.secrets["kis_api"]["CANO"],
                "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"],
                "ORD_DT_S": "20260201", # 2월 1일부터
                "ORD_DT_E": datetime.now().strftime("%Y%m%d"), # 오늘까지
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            
            # 4. 실제 호출
            url = f"{st.secrets['kis_api']['URL_BASE']}/uapi/overseas-stock/v1/trading/inquire-period-ccld"
            st.code(f"GET {url}")
            
            res = requests.get(url, headers=headers, params=params)
            
            # 5. 결과 출력 (Raw JSON)
            if res.status_code == 200:
                data = res.json()
                st.success("✅ 호출 성공! 원본 데이터를 확인하세요.")
                st.json(data) # <--- 여기에 데이터가 있는지 없는지 나옵니다!
            else:
                st.error(f"❌ 호출 실패: {res.status_code}")
                st.text(res.text)
    # [진단 키트 끝] ---------------------------------------------------------
