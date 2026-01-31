import streamlit as st
import pandas as pd
import requests
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import KIS_API_Manager as kis

st.set_page_config(page_title="Final Migration v2", page_icon="🧬", layout="wide")
st.title("🧬 DB 마이그레이션 (최종 보정판)")
st.caption("1월 17일까지의 수기 데이터 + 1월 31일 API 데이터(강제 조회)를 결합합니다.")

# -----------------------------------------------------------
# 0. 하드코딩된 과거 데이터 (1/17까지)
# -----------------------------------------------------------
past_data_source = [
    # ... (기존과 동일, 생략하지 않고 전체 포함)
    ['2025-12-30', '1', 'Exchange', 'KRW_to_USD', 'USD', 691.8, 0.0, 691.8, 1445.49, '카톡일괄입력'],
    ['2025-12-31', '2', 'Exchange', 'KRW_to_USD', 'USD', 690.87, 0.0, 690.87, 1447.44, '카톡일괄입력'],
    ['2025-12-31', '3', 'Trade', 'Buy', 'O', 12.0, 57.01, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-01', '4', 'Trade', 'Buy', 'O', 11.0, 56.79, 0.0, 0.0, '카톡일괄입력'],
    ['2026-01-05', '5', 'Exchange', 'KRW_to_USD', 'USD', 2070.9, 0.0, 2070.9, 1448.64, '카톡일괄입력'],
    ['2026-01-06', '6', 'Exchange', 'KRW_to_USD', 'USD', 3459.39, 0.0, 3459.39, 1445.34, '카톡일괄입력'],
    ['2026-01-06', 'O_Man', 'Trade', 'Buy', 'KO', 20.0, 68.1, 0.0, 0.0, '수기보정'],
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
    ['2026-01-16', '20260126024542', 'Dividend', 'Dividend', 'O', 0.0, 0.0, 2.75, 1469.7, '카톡파싱'],
    ['2026-01-16', '20260126024335', 'Trade', 'Buy', 'JEPQ', 4.0, 59.01, 0.0, 0.0, '카톡파싱'],
    ['2026-01-17', '20260126024934', 'Trade', 'Buy', 'GOOGL', 1.0, 329.7, 0.0, 0.0, '카톡파싱'],
    ['2026-01-17', '20260126025018', 'Trade', 'Buy', 'JEPI', 6.0, 58.41, 0.0, 0.0, '카톡파싱']
]

# -----------------------------------------------------------
# 1. API 데이터 수집 (1/18 ~ 1/31)
# -----------------------------------------------------------
def fetch_api_data():
    token = kis.get_access_token()
    base_url = st.secrets["kis_api"]["URL_BASE"].strip()
    if base_url.endswith("/"): base_url = base_url[:-1]
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": st.secrets["kis_api"]["APP_KEY"],
        "appsecret": st.secrets["kis_api"]["APP_SECRET"],
        "tr_id": "CTOS4001R"
    }
    
    # [수정] 조회 종료일을 '오늘'로 설정하여 1/31 데이터 포함 유도
    params = {
        "CANO": st.secrets["kis_api"]["CANO"],
        "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"],
        "ERLM_STRT_DT": "20260118", # 시작일
        "ERLM_END_DT": datetime.now().strftime("%Y%m%d"), # 종료일 (오늘)
        "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00", "OVRS_EXCG_CD": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    trade_list = []
    try:
        while True:
            res = requests.get(f"{base_url}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers=headers, params=params)
            data = res.json()
            if data['rt_cd'] == '0':
                for item in data['output1']:
                    dvsn = item.get('sll_buy_dvsn_name', '')
                    if '매수' in dvsn or '매도' in dvsn:
                        dt_raw = item.get('trad_dt') or item.get('tr_dt')
                        dt_fmt = f"{dt_raw[:4]}-{dt_raw[4:6]}-{dt_raw[6:]}"
                        qty = int(float(item['ccld_qty']))
                        price = float(item.get('ft_ccld_unpr2', 0))
                        if price == 0: price = float(item.get('ovrs_stck_ccld_unpr', 0))
                        
                        trade_list.append([
                            dt_fmt, f"API_{dt_raw}_{item['pdno']}_{qty}", 'Trade',
                            "Buy" if "매수" in dvsn else "Sell", item['pdno'], qty, price, 0.0, 0.0, 'API_Update'
                        ])
                
                ctx = data.get('ctx_area_fk100', '').strip()
                if not ctx: break
                params['CTX_AREA_FK100'] = ctx
                time.sleep(0.2)
            else:
                break
    except: pass
    return trade_list

# -----------------------------------------------------------
# 2. 환율 보정 (YFinance)
# -----------------------------------------------------------
def fill_exchange_rates(df):
    zero_mask = (df['Category'] == 'Trade') & (df['Rate'] == 0)
    if not zero_mask.any(): return df
    
    dates = pd.to_datetime(df.loc[zero_mask, 'Date'])
    start = (dates.min() - timedelta(days=5)).strftime('%Y-%m-%d')
    end = (dates.max() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    try:
        yf_data = yf.download("KRW=X", start=start, end=end, progress=False)
        rates = yf_data['Close']
        if isinstance(rates, pd.DataFrame): rates = rates.iloc[:, 0]
        
        def get_rate(row):
            if row['Category'] != 'Trade' or row['Rate'] > 0: return row['Rate']
            target = pd.to_datetime(row['Date'])
            for i in range(5):
                d = target - timedelta(days=i)
                if d in rates.index: return float(rates.loc[d])
            return 1450.0
        df['Rate'] = df.apply(get_rate, axis=1)
    except: pass
    return df

# -----------------------------------------------------------
# 3. 달러 저수지 로직 (이동평균 재계산)
# -----------------------------------------------------------
def calculate_reservoir(df):
    total_usd = 0.0
    total_krw = 0.0
    avg_rate = 0.0
    
    t_rows, e_rows, d_rows = [], [], []
    
    # 날짜순 정렬 (매우 중요)
    df = df.sort_values(['Date', 'Order_ID']).reset_index(drop=True)

    for _, row in df.iterrows():
        cat, typ = row['Category'], row['Type']
        qty, price, amt, rate = float(row['Qty']), float(row['Price']), float(row['Amount']), float(row['Rate'])
        
        if cat == 'Exchange':
            usd_in = amt
            krw_in = usd_in * rate
            total_usd += usd_in
            total_krw += krw_in
            if total_usd > 0: avg_rate = total_krw / total_usd
            e_rows.append([row['Date'], row['Order_ID'], typ, int(krw_in), usd_in, rate, round(avg_rate, 8), round(total_usd, 2), row['Note']])
            
        elif cat == 'Dividend':
            usd_in = amt
            total_usd += usd_in
            # KRW 투입 없음 (평단가 인하)
            if total_usd > 0: avg_rate = total_krw / total_usd
            d_rows.append([row['Date'], row['Order_ID'], row['Ticker'], usd_in, rate, row['Note']])
            
        elif cat == 'Trade':
            if typ == 'Buy':
                buy_usd = qty * price
                total_usd -= buy_usd
                total_krw -= (buy_usd * avg_rate)
                t_rows.append([row['Date'], row['Order_ID'], row['Ticker'], row['Ticker'], typ, qty, price, round(avg_rate, 8), row['Note']])
            elif typ == 'Sell':
                sell_usd = qty * price
                total_usd += sell_usd
                total_krw += (sell_usd * avg_rate)
                t_rows.append([row['Date'], row['Order_ID'], row['Ticker'], row['Ticker'], typ, qty, price, round(avg_rate, 8), row['Note']])

    return t_rows, e_rows, d_rows

# -----------------------------------------------------------
# 4. UI 실행
# -----------------------------------------------------------
if st.button("🚀 DB 최종 업데이트 (1/31 포함)"):
    with st.spinner("데이터 수집 및 병합 중..."):
        # 1. 병합
        df_past = pd.DataFrame(past_data_source, columns=['Date', 'Order_ID', 'Category', 'Type', 'Ticker', 'Qty', 'Price', 'Amount', 'Rate', 'Note'])
        api_list = fetch_api_data()
        
        if api_list:
            df_api = pd.DataFrame(api_list, columns=df_past.columns)
            df_all = pd.concat([df_past, df_api], ignore_index=True)
        else:
            st.warning("API 데이터가 없습니다. (장 종료 후 데이터 미반영 등)")
            df_all = df_past

        # 2. 환율 & 계산
        df_all['Date'] = pd.to_datetime(df_all['Date'])
        df_all = fill_exchange_rates(df_all)
        t_final, e_final, d_final = calculate_reservoir(df_all)

        # 3. 저장
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
            client = gspread.authorize(creds)
            sh = client.open("Investment_Dashboard_DB")
            
            ws_t = sh.worksheet("Trade_Log")
            ws_t.clear()
            ws_t.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Ex_Avg_Rate", "Note"])
            if t_final: ws_t.append_rows(t_final)
            
            ws_e = sh.worksheet("Exchange_Log")
            ws_e.clear()
            ws_e.append_row(["Date", "Order_ID", "Type", "KRW_Amount", "USD_Amount", "Ex_Rate", "Avg_Rate", "Balance", "Note"])
            if e_final: ws_e.append_rows(e_final)

            ws_d = sh.worksheet("Dividend_Log")
            ws_d.clear()
            ws_d.append_row(["Date", "Order_ID", "Ticker", "Amount_USD", "Ex_Rate", "Note"])
            if d_final: ws_d.append_rows(d_final)
            
            st.balloons()
            st.success("✅ 업데이트 완료! (1월 31일 거래 확인 필수)")
            
            # 결과 보여주기
            st.write("### Trade_Log 미리보기 (최신순)")
            st.dataframe(pd.DataFrame(t_final, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Avg_Rate", "Note"]).sort_values('Date', ascending=False).head(10))

        except Exception as e:
            st.error(f"저장 실패: {e}")
