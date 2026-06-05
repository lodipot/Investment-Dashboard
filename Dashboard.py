import streamlit as st
import pandas as pd
from datetime import datetime
import KIS_API_Manager as kis
import Data_Ingestion as di  # 신규 모듈 임포트

# --- (기존 st.set_page_config 및 CSS 유지) ---

# [1] 통합 원장 불러오기 & 필터링 (기존 코드를 이것으로 대체)
def load_unified_ledger():
    client = kis.get_sheet_client() # 기존 KIS 매니저의 gspread 클라이언트 재사용
    ws = client.open("Investment_Dashboard_DB").worksheet("Unified_Ledger")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    
    # 정렬: 소수점 ID 꼼수 없이 Timestamp 기준으로 완벽하게 정렬됩니다.
    if not df.empty:
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df = df.sort_values(by='Timestamp').reset_index(drop=True)
    return df, client

df_ledger, g_client = load_unified_ledger()

# 기존 로직과 완벽 호환되도록 DataFrame 분리
usd_df = df_ledger[df_ledger['Currency'] == 'USD'].copy()
jpy_df = df_ledger[df_ledger['Currency'] == 'JPY'].copy()
krw_df = df_ledger[df_ledger['Currency'] == 'KRW'].copy()

# --- (기존 JPY_Trade_Log, USD_Money_Log를 처리하던 PnL 계산 로직 그대로 유지) ---


# [2] 사이드바: 데이터 수동 파싱 스테이션
with st.sidebar:
    st.header("📥 Data Entry Station")
    
    tab1, tab2 = st.tabs(["💬 카톡 알림 파싱", "💰 원화 입출금"])
    
    with tab1:
        kakao_text = st.text_area("카카오톡 알림을 붙여넣으세요:", height=200)
        if st.button("파싱 및 적재", use_container_width=True):
            if kakao_text:
                events = di.parse_kakao_alert(kakao_text)
                count = di.insert_events_to_sheet(g_client, events)
                st.success(f"{count}건의 데이터가 신통합원장에 임시(Pending) 적재되었습니다.")
                st.rerun() # 화면 새로고침하여 즉시 반영

    with tab2:
        entry_date = st.date_input("날짜", datetime.now())
        entry_time = st.time_input("시간", datetime.now().time())
        io_type = st.radio("구분", ["입금", "출금"], horizontal=True)
        krw_amt = st.number_input("원화 금액", min_value=0, step=10000)
        krw_note = st.text_input("출처/메모", placeholder="ex) 국민은행 이체")
        
        if st.button("원장에 기록", use_container_width=True):
            if krw_amt > 0:
                dt_combined = datetime.combine(entry_date, entry_time)
                # 출금이면 음수로 변환
                final_amt = krw_amt if io_type == "입금" else -krw_amt
                di.manual_krw_entry(g_client, dt_combined, io_type, final_amt, krw_note)
                st.success("입출금 내역이 원장에 기록되었습니다.")
                st.rerun()

    # KIS API 동기화 버튼
    st.divider()
    if st.button("🔄 API 체결내역 보완/동기화", type="primary", use_container_width=True):
        with st.spinner("API 데이터 대조 및 Upsert 중..."):
            kis.sync_api_to_ledger(g_client, df_ledger)
        st.success("데이터 무결성 검증 및 업데이트 완료!")
        st.rerun()
