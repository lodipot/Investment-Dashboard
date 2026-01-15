import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import re

st.set_page_config(page_title="데이터 입력", layout="wide")

st.title("📝 데이터 입력 매니저")

# 구글 시트 연결
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds_dict = dict(st.secrets["gcp_service_account"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sh = client.open("Investment_Dashboard_DB")

# 탭 구성
tab_katalk, tab_manual = st.tabs(["💬 카톡 파싱 입력", "✍️ 수동 입력"])

with tab_katalk:
    st.subheader("카카오톡 알림톡 붙여넣기")
    st.info("한국투자증권 '체결안내' 또는 '외화매수환전' 메시지를 붙여넣으세요.")
    
    # 날짜 강제 지정 기능
    input_date = st.date_input("거래 날짜 지정 (메시지에 날짜가 없을 경우 사용)", datetime.now())
    raw_text = st.text_area("메시지 입력", height=200)
    
    if st.button("파싱 및 저장"):
        if raw_text:
            lines = raw_text.split('\n')
            
            # 케이스 분류 및 파싱
            try:
                # 1. 환전 (외화매수환전)
                if "외화매수환전" in raw_text:
                    # 정규표현식으로 추출
                    krw_match = re.search(r'￦([\d,]+)', raw_text)
                    usd_match = re.search(r'USD ([\d,.]+)', raw_text)
                    rate_match = re.search(r'@([\d,.]+)', raw_text)
                    
                    if krw_match and usd_match and rate_match:
                        krw_amt = int(krw_match.group(1).replace(',', ''))
                        usd_amt = float(usd_match.group(1).replace(',', ''))
                        rate = float(rate_match.group(1).replace(',', ''))
                        
                        # 시트에 추가
                        ws = sh.worksheet("Exchange_Log")
                        ws.append_row([str(input_date), "KRW_to_USD", krw_amt, usd_amt, rate, "카톡파싱"])
                        st.success(f"✅ 환전 내역 저장 완료! (￦{krw_amt:,} -> ${usd_amt})")
                    else:
                        st.error("환전 정보를 찾을 수 없습니다. 형식을 확인해주세요.")

                # 2. 주식 체결 (체결안내)
                elif "체결안내" in raw_text:
                    # *종목명:KO/코카콜라
                    ticker_match = re.search(r'\*종목명:([A-Z]+)/', raw_text)
                    # *체결수량:20주
                    qty_match = re.search(r'\*체결수량:([\d]+)', raw_text)
                    # *체결단가:USD 68.10
                    price_match = re.search(r'\*체결단가:USD ([\d.]+)', raw_text)
                    
                    if ticker_match and qty_match and price_match:
                        ticker = ticker_match.group(1)
                        qty = int(qty_match.group(1))
                        price = float(price_match.group(1))
                        
                        # 환율은 최근 환전 내역 참조 (여기선 1400 임시 혹은 수동)
                        # *개선: 가장 최근 환율 가져오기 로직 추가 가능
                        
                        ws = sh.worksheet("Trade_Log")
                        ws.append_row([str(input_date), ticker, ticker, "Buy", qty, price, 1450.0, "카톡파싱"]) 
                        st.success(f"✅ 매수 체결 저장 완료! ({ticker} {qty}주 @ ${price})")
                        st.warning("⚠️ 주의: 환율은 1450원으로 임시 저장되었습니다. 구글 시트에서 정확한 환율로 수정해주세요.")
                    else:
                        st.error("체결 정보를 찾을 수 없습니다.")
                
                else:
                    st.warning("알 수 없는 메시지 형식입니다.")
                    
            except Exception as e:
                st.error(f"오류 발생: {e}")

with tab_manual:
    st.write("준비 중입니다. 구글 시트에 직접 입력해주세요.")
