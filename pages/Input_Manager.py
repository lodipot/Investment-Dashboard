import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import re

st.set_page_config(page_title="Data Input Manager", layout="wide")
st.title("📝 데이터 입력 매니저")

# 구글 시트 연결
try:
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sh = client.open("Investment_Dashboard_DB")
except Exception as e:
    st.error(f"DB 연결 실패: {e}")
    st.stop()

tab_katalk, tab_manual = st.tabs(["💬 카톡 파싱 입력", "✍️ 수동 입력"])

with tab_katalk:
    st.subheader("한국투자증권 알림톡 붙여넣기")
    input_date = st.date_input("거래 날짜", datetime.now())
    raw_text = st.text_area("메시지 내용 (환전, 체결, 배당)", height=150)
    
    if st.button("분석 및 저장"):
        if raw_text:
            try:
                # 1. 배당금 (입금) 파싱
                # 예: O/리얼티 인컴 ... USD 3.24
                if "배당" in raw_text:
                    ticker_match = re.search(r'([A-Z]+)/', raw_text)
                    usd_match = re.search(r'USD ([\d,.]+)', raw_text)
                    
                    if ticker_match and usd_match:
                        ticker = ticker_match.group(1)
                        raw_amount = float(usd_match.group(1).replace(',', ''))
                        
                        # 세후 추정 (15% 차감) - 실제 입금액과 다를 수 있으므로 추정치 제시
                        net_amount = raw_amount * 0.85
                        
                        ws = sh.worksheet("Dividend_Log")
                        ws.append_row([str(input_date), ticker, net_amount, "카톡파싱(세후추정)"])
                        st.success(f"💰 {ticker} 배당 저장 완료! (세전 ${raw_amount} -> 세후 ${net_amount:.2f})")
                    else:
                        st.warning("배당 정보를 읽을 수 없습니다.")

                # 2. 환전 (외화매수)
                elif "외화매수환전" in raw_text:
                    krw_match = re.search(r'￦([\d,]+)', raw_text)
                    usd_match = re.search(r'USD ([\d,.]+)', raw_text)
                    
                    if krw_match and usd_match:
                        krw_amt = int(krw_match.group(1).replace(',', ''))
                        usd_amt = float(usd_match.group(1).replace(',', ''))
                        rate = krw_amt / usd_amt # 역산
                        
                        ws = sh.worksheet("Exchange_Log")
                        ws.append_row([str(input_date), "KRW_to_USD", krw_amt, usd_amt, rate, "카톡파싱"])
                        st.success(f"💱 환전 기록 완료! (${usd_amt})")
                        
                # 3. 매수 체결
                elif "체결안내" in raw_text:
                    ticker_match = re.search(r'\*종목명:([A-Z]+)/', raw_text)
                    qty_match = re.search(r'\*체결수량:([\d]+)', raw_text)
                    price_match = re.search(r'\*체결단가:USD ([\d.]+)', raw_text)
                    
                    if ticker_match and qty_match and price_match:
                        ticker = ticker_match.group(1)
                        qty = int(qty_match.group(1))
                        price = float(price_match.group(1))
                        
                        ws = sh.worksheet("Trade_Log")
                        # 환율은 0으로 넣고 나중에 보정하거나, 최근 환율 조회 로직 추가 필요. 일단 1450
                        ws.append_row([str(input_date), ticker, ticker, "Buy", qty, price, 1450.0, "카톡파싱"])
                        st.success(f"🛒 {ticker} 매수 저장 완료!")
                        st.warning("※ 매수 시 적용 환율은 1450원으로 임시 저장되었습니다. 구글 시트에서 수정해주세요.")
                
                else:
                    st.error("지원하지 않는 메시지 형식입니다.")
                    
            except Exception as e:
                st.error(f"오류: {e}")

with tab_manual:
    st.write("준비 중입니다. (구글 시트 직접 편집 권장)")
