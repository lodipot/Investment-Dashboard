import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import re
import yfinance as yf

st.set_page_config(page_title="Data Input Manager", layout="wide", initial_sidebar_state="collapsed")
st.title("📝 데이터 입력 매니저")

# DB 연결
try:
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sh = client.open("Investment_Dashboard_DB")
except Exception as e:
    st.error(f"DB 연결 실패: {e}")
    st.stop()

# -------------------------------------------------------------------
# 평단/잔고 자동 계산 로직 (8자리 정밀도)
# -------------------------------------------------------------------
def calculate_metrics(sh):
    try:
        ex_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        tr_df = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        div_df = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        
        # 통합 타임라인 생성
        timeline = []
        
        def clean(x): return float(str(x).replace(',','')) if str(x).replace(',','').replace('.','').isdigit() else 0
        
        for _, r in ex_df.iterrows():
            timeline.append({'date': r['Date'], 'type': 'exchange', 'usd': clean(r['USD_Amount']), 'krw': clean(r['KRW_Amount']), 'rate': 0})
        for _, r in div_df.iterrows():
            # 배당은 USD 유입, KRW 비용은 당시 환율(Ex_Rate)로 계산
            ex_rate = clean(r['Ex_Rate'])
            amt = clean(r['Amount_USD'])
            timeline.append({'date': r['Date'], 'type': 'dividend', 'usd': amt, 'krw': amt * ex_rate, 'rate': ex_rate})
        for _, r in tr_df.iterrows():
            # 매수는 USD 유출 (비용은 평단으로 차감)
            cost = clean(r['Qty']) * clean(r['Price_USD'])
            timeline.append({'date': r['Date'], 'type': 'trade', 'usd': -cost, 'krw': 0, 'rate': 0})
            
        # 정렬: 날짜 > 배당 > 환전 > 매수
        prio = {'dividend':1, 'exchange':2, 'trade':3}
        timeline.sort(key=lambda x: (x['date'], prio.get(x['type'], 9)))
        
        curr_usd = 0.0
        curr_krw = 0.0
        
        for item in timeline:
            if item['type'] in ['exchange', 'dividend']:
                curr_usd += item['usd']
                curr_krw += item['krw']
            elif item['type'] == 'trade':
                if curr_usd > 0:
                    avg_rate = curr_krw / curr_usd
                    used_krw = abs(item['usd']) * avg_rate
                    curr_krw -= used_krw
                curr_usd += item['usd'] # negative
                
        # 최종 평단
        final_rate = (curr_krw / curr_usd) if curr_usd > 0 else 1450.0
        return round(final_rate, 8)
        
    except Exception as e:
        return 1450.0

# -------------------------------------------------------------------
# 입력 UI
# -------------------------------------------------------------------
tab_katalk, tab_manual = st.tabs(["💬 카톡 파싱", "✍️ 수동 입력"])

with tab_katalk:
    st.info("💡 배당 입력 시, 환율이 없으면 오늘 날짜 기준 환율을 자동 제안합니다.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        input_date = st.date_input("거래 날짜", datetime.now())
        # [NEW] 배당용 환율 수동 입력
        is_dividend = st.checkbox("배당금 입력 모드")
        if is_dividend:
            # 기본값: 오늘 환율 조회
            try:
                today_rate = yf.Ticker("USDKRW=X").history(period="1d")['Close'].iloc[-1]
            except: today_rate = 1450.0
            manual_rate = st.number_input("적용 환율 (배당용)", value=float(round(today_rate, 2)), step=0.1, format="%.2f")
    
    with col2:
        raw_text = st.text_area("메시지 붙여넣기", height=150)
    
    if st.button("분석 및 저장", type="primary"):
        if raw_text:
            try:
                # 0. 현재 평단 계산 (매수용)
                current_avg_rate = calculate_metrics(sh)
                ts = datetime.now().strftime('%Y%m%d%H%M%S') # Order ID용
                
                # 1. 배당 (Dividend)
                if "배당" in raw_text or is_dividend:
                    ticker_match = re.search(r'([A-Z]+)/', raw_text)
                    usd_match = re.search(r'USD ([\d,.]+)', raw_text)
                    
                    ticker = ticker_match.group(1) if ticker_match else "UNKNOWN"
                    amt = float(usd_match.group(1).replace(',','')) if usd_match else 0
                    
                    if amt > 0:
                        ws = sh.worksheet("Dividend_Log")
                        # [Date, Order_ID, Ticker, Amount_USD, Ex_Rate, Note]
                        ws.append_row([str(input_date), ts, ticker, amt, manual_rate, "카톡파싱"])
                        st.success(f"💰 {ticker} 배당 저장 완료! (${amt} @ {manual_rate}원)")
                    else:
                        st.warning("배당 정보를 찾을 수 없습니다. (직접 입력 모드 사용 권장)")

                # 2. 환전
                elif "외화매수환전" in raw_text:
                    krw_match = re.search(r'￦([\d,]+)', raw_text)
                    usd_match = re.search(r'USD ([\d,.]+)', raw_text)
                    if krw_match and usd_match:
                        krw = int(krw_match.group(1).replace(',',''))
                        usd = float(usd_match.group(1).replace(',',''))
                        rate = krw / usd
                        
                        ws = sh.worksheet("Exchange_Log")
                        # [Date, Order_ID, Type, KRW, USD, Ex_Rate, Avg, Bal, Note]
                        ws.append_row([str(input_date), ts, "KRW_to_USD", krw, usd, rate, "", "", "카톡파싱"])
                        st.success(f"💱 환전 기록 완료! (${usd})")
                        st.info("※ 잔고 및 평단은 다음 조회 시 자동 갱신됩니다.")

                # 3. 매수
                elif "체결안내" in raw_text:
                    ticker_match = re.search(r'\*종목명:([A-Z]+)/', raw_text)
                    qty_match = re.search(r'\*체결수량:([\d]+)', raw_text)
                    price_match = re.search(r'\*체결단가:USD ([\d.]+)', raw_text)
                    
                    if ticker_match:
                        t = ticker_match.group(1)
                        q = int(qty_match.group(1))
                        p = float(price_match.group(1))
                        
                        ws = sh.worksheet("Trade_Log")
                        # [Date, Order_ID, Ticker, Name, Type, Qty, Price, Ex_Rate, Note]
                        # 여기서 Ex_Rate는 '매수 시점의 평단가(current_avg_rate)'를 저장
                        ws.append_row([str(input_date), ts, t, t, "Buy", q, p, current_avg_rate, "카톡파싱"])
                        st.success(f"🛒 {t} 매수 저장 완료! (적용평단: {current_avg_rate:.2f}원)")
                        
                else:
                    st.error("지원하지 않는 메시지 형식입니다.")
            except Exception as e:
                st.error(f"오류: {e}")

with tab_manual:
    st.write("구글 시트에서 직접 입력해주세요.")
