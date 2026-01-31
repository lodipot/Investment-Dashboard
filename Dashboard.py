import streamlit as st
import pandas as pd
import requests
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import KIS_API_Manager as kis

st.set_page_config(page_title="DB Migration (Hardcoded Patch)", page_icon="🧬", layout="wide")
st.title("🧬 DB 마이그레이션 (과거 내역 + API 최신)")
st.caption("1월 17일까지의 수기 데이터(하드코딩)와 그 이후의 API 데이터를 결합하여 DB를 재구축합니다.")

# -----------------------------------------------------------
# 0. 하드코딩된 과거 데이터 (1월 17일까지)
# -----------------------------------------------------------
# [Date, Order_ID, Category, Type, Ticker, Qty, Price, Amount, Rate, Note]
past_data_list = [
    ['2025-12-30', '1', 'Exchange', 'KRW_to_USD', 'USD', 691.8, 0.0, 691.8, 1445.49, '카톡일괄입력'],
    ['2025-12-31', '2', 'Exchange', 'KRW_to_USD', 'USD', 690.87, 0.0, 690.87, 1447.44, '카톡일괄입력'],
    ['2025-12-31', '3', 'Trade', 'Buy', 'O', 12.0, 57.01, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-01', '4', 'Trade', 'Buy', 'O', 11.0, 56.79, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-05', '5', 'Exchange', 'KRW_to_USD', 'USD', 2070.9, 0.0, 2070.9, 1448.64, '카톡일괄입력'],
    ['2026-01-06', '6', 'Exchange', 'KRW_to_USD', 'USD', 3459.39, 0.0, 3459.39, 1445.34, '카톡일괄입력'],
    ['2026-01-07', '7', 'Exchange', 'KRW_to_USD', 'USD', 3448.06, 0.0, 3448.06, 1450.09, '카톡일괄입력'],
    ['2026-01-07', '8', 'Exchange', 'KRW_to_USD', 'USD', 3448.77, 0.0, 3448.77, 1449.79, '카톡일괄입력'],
    ['2026-01-07', '10', 'Trade', 'Buy', 'KO', 20.0, 68.1, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-07', '11', 'Trade', 'Buy', 'O', 17.0, 57.12, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-07', '9', 'Trade', 'Buy', 'PLD', 3.0, 127.54, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-08', '12', 'Trade', 'Buy', 'MSFT', 4.0, 482.87, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-08', '13', 'Trade', 'Buy', 'GOOGL', 2.0, 319.14, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-08', '14', 'Trade', 'Buy', 'PLD', 3.0, 127.81, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-09', '15', 'Trade', 'Buy', 'GOOGL', 2.0, 322.1, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-09', '16', 'Trade', 'Buy', 'NVDA', 2.0, 185.71, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-09', '17', 'Trade', 'Buy', 'PLD', 5.0, 126.9, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-09', '18', 'Trade', 'Buy', 'JEPI', 6.0, 58.0, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-09', '19', 'Trade', 'Buy', 'AMD', 3.0, 208.75, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-09', '20', 'Trade', 'Buy', 'MSFT', 1.0, 483.19, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-10', '21', 'Trade', 'Buy', 'JEPI', 10.0, 58.13, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-10', '22', 'Trade', 'Buy', 'SCHD', 32.0, 28.47, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-10', '23', 'Trade', 'Buy', 'O', 2.0, 58.29, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-12', '24', 'Exchange', 'KRW_to_USD', 'USD', 680.1, 0.0, 680.1, 1470.36, '카톡일괄입력'],
    ['2026-01-13', '25', 'Exchange', 'KRW_to_USD', 'USD', 2037.11, 0.0, 2037.11, 1472.67, '카톡일괄입력'],
    ['2026-01-13', '26', 'Trade', 'Buy', 'GOOGL', 3.0, 327.16, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-14', '20260126023549', 'Trade', 'Buy', 'GOOGL', 1.0, 334.5, 0.0, 0.0, '카톡파싱'],
    ['2026-01-14', '20260126023624', 'Trade', 'Buy', 'JEPI', 11.0, 58.17, 0.0, 0.0, '카톡파싱'],
    ['2026-01-14', '27', 'Trade', 'Buy', 'JEPQ', 24.0, 59.13, 0.0, 0.0, '카톡파싱'],
    ['2026-01-16', '20260126024542', 'Dividend', 'Dividend', 'O', 0.0, 0.0, 3.24, 1469.7, '카톡파싱'],
    ['2026-01-16', '20260126024335', 'Trade', 'Buy', 'JEPQ', 4.0, 59.01, 0.0, 0.0, '카톡파싱'],
    ['2026-01-17', '20260126024934', 'Trade', 'Buy', 'GOOGL', 1.0, 329.7, 0.0, 0.0, '카톡파싱'],
    ['2026-01-17', '20260126025018', 'Trade', 'Buy', 'JEPI', 6.0, 58.41, 0.0, 0.0, '카톡파싱']
]

# -----------------------------------------------------------
# 1. API 설정
# -----------------------------------------------------------
token = kis.get_access_token()
base_url = st.secrets["kis_api"]["URL_BASE"].strip()
if base_url.endswith("/"): base_url = base_url[:-1]

app_key = st.secrets["kis_api"]["APP_KEY"]
app_secret = st.secrets["kis_api"]["APP_SECRET"]
cano = st.secrets["kis_api"]["CANO"]
acnt_prdt_cd = st.secrets["kis_api"]["ACNT_PRDT_CD"]

# -----------------------------------------------------------
# 2. API 데이터 수집 (2026-01-18 이후)
# -----------------------------------------------------------
def fetch_recent_api_data():
    trade_list = []
    
    path = "/uapi/overseas-stock/v1/trading/inquire-period-trans"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "CTOS4001R"
    }
    
    # [중요] 1월 17일 이후부터 조회
    params = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
        "ERLM_STRT_DT": "20260118", "ERLM_END_DT": datetime.now().strftime("%Y%m%d"),
        "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00",
        "OVRS_EXCG_CD": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    try:
        res = requests.get(f"{base_url}{path}", headers=headers, params=params)
        data = res.json()
        
        if res.status_code == 200 and data['rt_cd'] == '0':
            for item in data['output1']:
                dvsn_name = item.get('sll_buy_dvsn_name', '')
                if '매수' in dvsn_name or '매도' in dvsn_name:
                    # 날짜
                    dt_str = item.get('trad_dt') or item.get('tr_dt')
                    dt_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                    
                    ticker = item.get('pdno', '')
                    name = item.get('ovrs_item_name', '')
                    qty = int(float(item.get('ccld_qty', '0')))
                    price = float(item.get('ft_ccld_unpr2', '0'))
                    if price == 0: price = float(item.get('ovrs_stck_ccld_unpr', '0'))
                    
                    t_type = "Buy" if "매수" in dvsn_name else "Sell"
                    order_id = f"API_{dt_str}_{ticker}_{qty}"
                    
                    # [Date, Order_ID, Category, Type, Ticker, Qty, Price, Amount, Rate, Note]
                    trade_list.append([
                        dt_fmt, order_id, 'Trade', t_type, ticker, qty, price, 0.0, 0.0, 'API_Update'
                    ])
    except Exception as e:
        st.error(f"API 조회 중 오류: {e}")
        
    return trade_list

# -----------------------------------------------------------
# 3. 데이터 병합 및 시트 저장
# -----------------------------------------------------------
def migrate_data():
    # 1. 과거 데이터 로드
    df_past = pd.DataFrame(past_data_list, columns=[
        'Date', 'Order_ID', 'Category', 'Type', 'Ticker', 'Qty', 'Price', 'Amount', 'Rate', 'Note'
    ])
    
    # 2. 최신 API 데이터 로드 (역순 정렬 방지)
    api_data = fetch_recent_api_data()
    # API 데이터는 최신순으로 올 수 있으므로 날짜순 정렬 필요
    api_data.sort(key=lambda x: x[0]) 
    
    df_new = pd.DataFrame(api_data, columns=df_past.columns)
    
    # 3. 병합
    df_final = pd.concat([df_past, df_new], ignore_index=True)
    
    # 4. 시트별 분리
    # Trade_Log: Category == 'Trade'
    df_trade = df_final[df_final['Category'] == 'Trade'].copy()
    # 필요한 컬럼만 선택 및 이름 변경 (Amount는 Trade에서 안 씀, Rate는 Exchange_Rate)
    df_trade = df_trade[['Date', 'Order_ID', 'Ticker', 'Ticker', 'Type', 'Qty', 'Price', 'Rate', 'Note']] 
    # Ticker가 두 번 들어갔는데 하나는 Name 자리. Name을 API에서 가져오거나 수기 데이터에 있으니 그걸 써야 함.
    # 수기 데이터에는 Ticker가 코드고 Name이 없음 (위 리스트에서 Ticker 자리에 코드가 들어감).
    # 위 리스트 구조: [Date, Order_ID, Category, Type, Ticker, Qty, Price, Amount, Rate, Note]
    # Trade_Log 구조: [Date, Order_ID, Ticker, Name, Type, Qty, Price_USD, Exchange_Rate, Note]
    # 위 리스트엔 Name이 없습니다. Name은 비워두거나 Ticker로 채웁니다.
    
    trade_rows = []
    for _, row in df_final[df_final['Category'] == 'Trade'].iterrows():
        trade_rows.append([
            row['Date'], row['Order_ID'], row['Ticker'], row['Ticker'], # Name 대신 Ticker 임시 사용
            row['Type'], row['Qty'], row['Price'], row['Rate'], row['Note']
        ])
        
    # Exchange_Log
    # 구조: [Date, Order_ID, Type, KRW_Amount, USD_Amount, Ex_Rate, Avg_Rate, Balance, Note]
    # 위 리스트 Exchange: [Date, Order_ID, 'Exchange', 'KRW_to_USD', 'USD', Qty(USD), 0, Amount(USD), Rate, Note]
    exchange_rows = []
    for _, row in df_final[df_final['Category'] == 'Exchange'].iterrows():
        usd_amt = row['Amount']
        krw_amt = usd_amt * row['Rate'] # 역산 (정확하진 않지만 근사치)
        exchange_rows.append([
            row['Date'], row['Order_ID'], row['Type'], 
            int(krw_amt), usd_amt, row['Rate'], 0, 0, row['Note'] # Avg_Rate, Balance는 추후 계산
        ])
        
    # Dividend_Log
    # 구조: [Date, Order_ID, Ticker, Amount_USD, Ex_Rate, Note]
    div_rows = []
    for _, row in df_final[df_final['Category'] == 'Dividend'].iterrows():
        div_rows.append([
            row['Date'], row['Order_ID'], row['Ticker'], row['Amount'], row['Rate'], row['Note']
        ])

    # 5. 구글 시트 저장
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")
        
        # Trade_Log
        ws_t = sh.worksheet("Trade_Log")
        ws_t.clear()
        ws_t.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Exchange_Rate", "Note"])
        if trade_rows: ws_t.append_rows(trade_rows)
        
        # Exchange_Log
        ws_e = sh.worksheet("Exchange_Log")
        ws_e.clear()
        ws_e.append_row(["Date", "Order_ID", "Type", "KRW_Amount", "USD_Amount", "Ex_Rate", "Avg_Rate", "Balance", "Note"])
        if exchange_rows: ws_e.append_rows(exchange_rows)
        
        # Dividend_Log
        ws_d = sh.worksheet("Dividend_Log")
        ws_d.clear()
        ws_d.append_row(["Date", "Order_ID", "Ticker", "Amount_USD", "Ex_Rate", "Note"])
        if div_rows: ws_d.append_rows(div_rows)
        
        return True, len(trade_rows), len(exchange_rows), len(div_rows)
        
    except Exception as e:
        st.error(f"시트 저장 실패: {e}")
        return False, 0, 0, 0

# -----------------------------------------------------------
# 4. UI
# -----------------------------------------------------------
if st.button("🚀 DB 마이그레이션 실행 (Hardcode + API)"):
    with st.spinner("데이터 병합 및 저장 중..."):
        success, t_cnt, e_cnt, d_cnt = migrate_data()
        
    if success:
        st.balloons()
        st.success("✅ DB 재구축 완료!")
        st.write(f"- Trade_Log: {t_cnt}건")
        st.write(f"- Exchange_Log: {e_cnt}건")
        st.write(f"- Dividend_Log: {d_cnt}건")
        st.info("이제 Dashboard.py를 STEP 3(최종 대시보드) 코드로 교체하세요.")
