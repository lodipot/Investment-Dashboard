import streamlit as st
import pandas as pd
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import KIS_API_Manager as kis

st.set_page_config(page_title="Dollar Reservoir Builder", page_icon="💧", layout="wide")
st.title("💧 달러 저수지(Dollar Reservoir) 재구축")
st.caption("수기 데이터와 API 데이터를 결합하고, '이동평균 환율'을 정밀하게 재계산하여 DB를 동기화합니다.")

# -----------------------------------------------------------
# 0. 하드코딩된 과거 데이터 (1월 17일까지)
# -----------------------------------------------------------
# 구조: [Date, Order_ID, Category, Type, Ticker, Qty, Price, Amount, Rate, Note]
# 수정사항: 배당금 3.24 -> 2.75 (세후) 반영
past_data_source = [
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
    # [수정] 배당금 3.24 -> 2.75 (세후 반영)
    ['2026-01-16', '20260126024542', 'Dividend', 'Dividend', 'O', 0.0, 0.0, 2.75, 1469.7, '카톡파싱'],
    ['2026-01-16', '20260126024335', 'Trade', 'Buy', 'JEPQ', 4.0, 59.01, 0.0, 0.0, '카톡파싱'],
    ['2026-01-17', '20260126024934', 'Trade', 'Buy', 'GOOGL', 1.0, 329.7, 0.0, 0.0, '카톡파싱'],
    ['2026-01-17', '20260126025018', 'Trade', 'Buy', 'JEPI', 6.0, 58.41, 0.0, 0.0, '카톡파싱']
]

# -----------------------------------------------------------
# 1. API 데이터 수집 (전체 구간)
# -----------------------------------------------------------
def fetch_all_trades():
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
    
    params = {
        "CANO": st.secrets["kis_api"]["CANO"],
        "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"],
        "ERLM_STRT_DT": "20240101", 
        "ERLM_END_DT": datetime.now().strftime("%Y%m%d"),
        "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00", "OVRS_EXCG_CD": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    trade_list = []
    
    try:
        # 페이지네이션 처리 (거래가 많을 수 있으므로)
        while True:
            res = requests.get(f"{base_url}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers=headers, params=params)
            data = res.json()
            
            if data['rt_cd'] == '0':
                for item in data['output1']:
                    dvsn = item.get('sll_buy_dvsn_name', '')
                    if '매수' in dvsn or '매도' in dvsn:
                        dt_str = item.get('trad_dt') or item.get('tr_dt')
                        dt_fmt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
                        
                        qty = int(float(item['ccld_qty']))
                        price = float(item.get('ft_ccld_unpr2', 0))
                        if price == 0: price = float(item.get('ovrs_stck_ccld_unpr', 0))
                        
                        trade_list.append({
                            'Date': dt_fmt,
                            'Ticker': item['pdno'],
                            'Name': item['ovrs_item_name'],
                            'Type': "Buy" if "매수" in dvsn else "Sell",
                            'Qty': qty,
                            'Price': price,
                            'Raw_Date': dt_str
                        })
                
                # 다음 페이지 확인
                ctx = data.get('ctx_area_fk100', '').strip()
                if not ctx: break
                params['CTX_AREA_FK100'] = ctx
                time.sleep(0.2)
            else:
                break
                
    except Exception as e:
        st.error(f"API 조회 중 오류: {e}")
        
    return pd.DataFrame(trade_list)

# -----------------------------------------------------------
# 2. 데이터 처리 및 계산 (핵심)
# -----------------------------------------------------------
def process_data(api_df):
    # 1. 과거 데이터 DF 변환
    past_df = pd.DataFrame(past_data_source, columns=['Date', 'Order_ID', 'Category', 'Type', 'Ticker', 'Qty', 'Price', 'Amount', 'Rate', 'Note'])
    
    # 2. API 데이터 중 1월 17일 이후 것만 추출
    cutoff_date = "2026-01-17"
    new_api_df = api_df[api_df['Date'] > cutoff_date].copy()
    
    # 3. 새로운 API 데이터를 표준 포맷으로 변환
    new_rows = []
    for _, row in new_api_df.iterrows():
        order_id = f"API_{row['Raw_Date']}_{row['Ticker']}_{row['Qty']}"
        new_rows.append([
            row['Date'], order_id, 'Trade', row['Type'], row['Ticker'], 
            row['Qty'], row['Price'], 0.0, 0.0, 'API_Update'
        ])
        
    new_df = pd.DataFrame(new_rows, columns=past_df.columns)
    
    # 4. 전체 데이터 병합 및 정렬
    full_df = pd.concat([past_df, new_df], ignore_index=True)
    full_df['Date'] = pd.to_datetime(full_df['Date'])
    full_df = full_df.sort_values(['Date', 'Order_ID']).reset_index(drop=True)
    
    # 5. 달러 저수지(이동평균) 계산
    # 변수 초기화
    total_usd = 0.0
    total_krw = 0.0
    avg_rate = 0.0
    
    # 결과 저장용 리스트
    final_trade = []
    final_exchange = []
    final_dividend = []
    
    for idx, row in full_df.iterrows():
        cat = row['Category']
        qty = float(row['Qty'])
        price = float(row['Price'])
        amount = float(row['Amount'])
        rate = float(row['Rate'])
        
        # [Case A] 환전 (KRW -> USD) : 물 채우기
        if cat == 'Exchange':
            usd_in = amount # USD_Amount
            krw_in = usd_in * rate # 투입 원화 (실제 환율 적용)
            
            total_usd += usd_in
            total_krw += krw_in
            
            # 이동평균 갱신
            if total_usd > 0:
                avg_rate = total_krw / total_usd
            
            # Exchange_Log에 기록 (Avg_Rate, Balance 갱신)
            final_exchange.append([
                row['Date'].strftime('%Y-%m-%d'), row['Order_ID'], row['Type'],
                int(krw_in), usd_in, rate, round(avg_rate, 8), round(total_usd, 2), row['Note']
            ])
            
        # [Case B] 배당 (Dividend) : 물 채우기 (무상 입금 효과)
        elif cat == 'Dividend':
            usd_in = amount # 세후 배당금
            # 원화 투입은 0원으로 간주 (평단가 인하 효과)
            
            total_usd += usd_in
            # total_krw는 변하지 않음
            
            # 이동평균 갱신
            if total_usd > 0:
                avg_rate = total_krw / total_usd
                
            final_dividend.append([
                row['Date'].strftime('%Y-%m-%d'), row['Order_ID'], row['Ticker'],
                usd_in, rate, row['Note'] # Rate는 당시 환율 기록용
            ])
            
        # [Case C] 매매 (Trade) : 물 쓰기
        elif cat == 'Trade':
            if row['Type'] == 'Buy':
                buy_amt_usd = qty * price
                
                # 이동평균 환율은 '유지' (물 농도는 그대로)
                # 단, 잔고(USD, KRW)는 차감해야 함
                total_usd -= buy_amt_usd
                total_krw -= (buy_amt_usd * avg_rate) # 현재 평단가 비율대로 원화 차감
                
                # Trade_Log에 '당시 평단가(Ex_Avg_Rate)' 기록
                final_trade.append([
                    row['Date'].strftime('%Y-%m-%d'), row['Order_ID'], row['Ticker'],
                    row['Ticker'], # Name (API에서 가져오거나 Ticker로 대체)
                    row['Type'], qty, price, round(avg_rate, 8), row['Note']
                ])
                
            elif row['Type'] == 'Sell':
                sell_amt_usd = qty * price
                
                # 매도 시: 달러가 다시 들어옴 -> 이게 수익 실현인지 원금 회수인지 복잡함
                # '달러 저수지' 관점에서는: 
                # 1. 달러 잔고 증가 (+판 금액)
                # 2. 원화 잔고 증가 (+판 금액 * 당시 평단가? 아니면 판 시점 환율?)
                # 사용자 정의에 따라 다르지만, 보통 '달러 예수금'이 늘어나는 것이므로
                # 매수와 반대로 처리 (단가 변화 없음, 수량만 증가)
                
                total_usd += sell_amt_usd
                total_krw += (sell_amt_usd * avg_rate)
                
                final_trade.append([
                    row['Date'].strftime('%Y-%m-%d'), row['Order_ID'], row['Ticker'],
                    row['Ticker'], row['Type'], qty, price, round(avg_rate, 8), row['Note']
                ])

    return final_trade, final_exchange, final_dividend, api_df

# -----------------------------------------------------------
# 3. UI 실행
# -----------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    if st.button("1. 데이터 검증 (Verify)"):
        with st.spinner("API 조회 및 비교 중..."):
            api_df = fetch_all_trades()
            
            # 검증 로직: 1/17 이전 데이터 비교
            cutoff = pd.to_datetime("2026-01-17")
            api_past = api_df[pd.to_datetime(api_df['Date']) <= cutoff]
            
            st.subheader("🔎 데이터 교차 검증 결과")
            st.write(f"API에서 조회된 1/17 이전 매매 내역: **{len(api_past)}건**")
            st.dataframe(api_past)
            
            st.info("위 내역과 사용자님의 수기 내역(하드코딩)을 비교해 보세요. 일치한다면 우측 실행 버튼을 누르세요.")

with col2:
    if st.button("2. 실행 및 저장 (Execute & Save)"):
        with st.spinner("데이터 병합 및 환율 재계산 중..."):
            # API 다시 조회 (세션 없다고 가정하고 안전하게)
            api_df = fetch_all_trades()
            
            t_rows, e_rows, d_rows, _ = process_data(api_df)
            
            # 구글 시트 저장
            try:
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds_dict = dict(st.secrets["gcp_service_account"])
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
                client = gspread.authorize(creds)
                sh = client.open("Investment_Dashboard_DB")
                
                # 1. Trade_Log (Ex_Avg_Rate 적용)
                ws_t = sh.worksheet("Trade_Log")
                ws_t.clear()
                ws_t.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Ex_Avg_Rate", "Note"])
                if t_rows: ws_t.append_rows(t_rows)
                
                # 2. Exchange_Log (Avg_Rate, Balance 갱신)
                ws_e = sh.worksheet("Exchange_Log")
                ws_e.clear()
                ws_e.append_row(["Date", "Order_ID", "Type", "KRW_Amount", "USD_Amount", "Ex_Rate", "Avg_Rate", "Balance", "Note"])
                if e_rows: ws_e.append_rows(e_rows)
                
                # 3. Dividend_Log
                ws_d = sh.worksheet("Dividend_Log")
                ws_d.clear()
                ws_d.append_row(["Date", "Order_ID", "Ticker", "Amount_USD", "Ex_Rate", "Note"])
                if d_rows: ws_d.append_rows(d_rows)
                
                st.balloons()
                st.success("🏆 DB 업데이트 완료! (환율 8자리 정밀 계산 적용됨)")
                
                st.write("### 결과 미리보기 (Trade_Log)")
                st.dataframe(pd.DataFrame(t_rows, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Avg_Rate", "Note"]))
                
            except Exception as e:
                st.error(f"저장 실패: {e}")
