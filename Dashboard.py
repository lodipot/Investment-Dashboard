import streamlit as st
import pandas as pd
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import KIS_API_Manager as kis
import yfinance as yf

st.set_page_config(page_title="DB Emergency Restore", page_icon="🚑")
st.title("🚑 DB 데이터 긴급 복구")

# 1. 1월 17일까지의 수기 데이터 (배당 2.75 수정됨)
past_data = [
    ['2025-12-30', '1', 'O', '리얼티인컴', 'Buy', 12, 57.01, 1445.49, '카톡일괄'],
    ['2025-12-31', '3', 'O', '리얼티인컴', 'Buy', 11, 56.79, 1446.464344, '카톡일괄'],
    ['2026-01-07', '9', 'PLD', '프로로지스', 'Buy', 3, 127.54, 1448.857205, '카톡일괄'],
    ['2026-01-07', '10', 'KO', '코카콜라', 'Buy', 20, 68.1, 1446.574266, '카톡일괄'],
    ['2026-01-07', '11', 'O', '리얼티인컴', 'Buy', 17, 57.12, 1446.574266, '카톡일괄'],
    ['2026-01-08', '12', 'MSFT', '마이크로소프트', 'Buy', 4, 482.87, 1448.857205, '카톡일괄'],
    ['2026-01-08', '13', 'GOOGL', '알파벳 A', 'Buy', 2, 319.14, 1448.857205, '카톡일괄'],
    ['2026-01-08', '14', 'PLD', '프로로지스', 'Buy', 3, 127.81, 1448.857205, '카톡일괄'],
    ['2026-01-09', '15', 'GOOGL', '알파벳 A', 'Buy', 2, 322.1, 1448.857205, '카톡일괄'],
    ['2026-01-09', '16', 'NVDA', '엔비디아', 'Buy', 2, 185.71, 1448.857205, '카톡일괄'],
    ['2026-01-09', '17', 'PLD', '프로로지스', 'Buy', 5, 126.9, 1448.857205, '카톡일괄'],
    ['2026-01-09', '18', 'JEPI', 'JPMORGANEQUITY', 'Buy', 6, 58.0, 1448.857205, '카톡일괄'],
    ['2026-01-09', '19', 'AMD', 'AMD', 'Buy', 3, 208.75, 1448.857205, '카톡일괄'],
    ['2026-01-09', '20', 'MSFT', '마이크로소프트', 'Buy', 1, 483.19, 1448.857205, '카톡일괄'],
    ['2026-01-10', '21', 'JEPI', 'JPMORGANEQUITY', 'Buy', 10, 58.13, 1448.857205, '카톡일괄'],
    ['2026-01-10', '22', 'SCHD', 'SCHD', 'Buy', 32, 28.47, 1448.857205, '카톡일괄'],
    ['2026-01-10', '23', 'O', '리얼티인컴', 'Buy', 2, 58.29, 1448.857205, '카톡일괄'],
    ['2026-01-13', '26', 'GOOGL', '알파벳 A', 'Buy', 3, 327.16, 1461.920553, '카톡일괄'],
    ['2026-01-14', '20260126023549', 'GOOGL', '알파벳 A', 'Buy', 1, 334.5, 1461.920553, '카톡파싱'],
    ['2026-01-14', '20260126023624', 'JEPI', 'JPMORGANEQUITY', 'Buy', 11, 58.17, 1461.920553, '카톡파싱'],
    ['2026-01-14', '27', 'JEPQ', 'JP MORGAN', 'Buy', 24, 59.13, 1461.734, '카톡파싱'],
    ['2026-01-16', '20260126024335', 'JEPQ', 'JP MORGAN', 'Buy', 4, 59.01, 1461.733634, '카톡파싱'],
    ['2026-01-17', '20260126024934', 'GOOGL', '알파벳 A', 'Buy', 1, 329.7, 1461.751299, '카톡파싱'],
    ['2026-01-17', '20260126025018', 'JEPI', 'JPMORGANEQUITY', 'Buy', 6, 58.41, 1461.751299, '카톡파싱']
]

def restore_db():
    # 1. API로 1/18 이후 데이터 가져오기
    token = kis.get_access_token()
    headers = {"content-type":"application/json", "authorization":f"Bearer {token}", "appkey":st.secrets["kis_api"]["APP_KEY"], "appsecret":st.secrets["kis_api"]["APP_SECRET"], "tr_id":"CTOS4001R"}
    params = {
        "CANO": st.secrets["kis_api"]["CANO"], "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"],
        "ERLM_STRT_DT": "20260118", "ERLM_END_DT": datetime.now().strftime("%Y%m%d"),
        "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00", "OVRS_EXCG_CD": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    api_rows = []
    try:
        res = requests.get(f"{kis.URL_BASE}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers=headers, params=params)
        data = res.json()
        if data['rt_cd'] == '0':
            for item in data['output1']:
                if '매수' in item['sll_buy_dvsn_name'] or '매도' in item['sll_buy_dvsn_name']:
                    dt = item['trad_dt']
                    dt_fmt = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}"
                    qty = int(float(item['ccld_qty']))
                    if qty > 0:
                        price = float(item.get('ft_ccld_unpr2', 0))
                        if price == 0: price = float(item.get('ovrs_stck_ccld_unpr', 0))
                        
                        # API 데이터는 최근 환율(1461.xx) 유지
                        api_rows.append([
                            dt_fmt, f"API_{dt}_{item['pdno']}_{qty}", item['pdno'], item['ovrs_item_name'],
                            'Buy' if '매수' in item['sll_buy_dvsn_name'] else 'Sell',
                            qty, price, 1461.75129912, 'API_Restored'
                        ])
    except Exception as e:
        st.error(f"API 오류: {e}")

    # 2. 병합 및 저장
    total_rows = past_data + api_rows
    total_rows.sort(key=lambda x: x[0]) # 날짜순 정렬

    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = dict(st.secrets["gcp_service_account"])
        client = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds, scope))
        sh = client.open("Investment_Dashboard_DB")
        
        ws = sh.worksheet("Trade_Log")
        ws.clear()
        ws.append_row(["Date", "Order_ID", "Ticker", "Name", "Type", "Qty", "Price_USD", "Ex_Avg_Rate", "Note"])
        ws.append_rows(total_rows)
        st.success(f"✅ Trade_Log 복구 완료! (총 {len(total_rows)}건)")
        st.dataframe(pd.DataFrame(total_rows, columns=["Date", "ID", "Ticker", "Name", "Type", "Qty", "Price", "Rate", "Note"]))
        
    except Exception as e:
        st.error(f"구글 시트 저장 실패: {e}")

if st.button("🚨 Trade_Log 긴급 복구 실행"):
    restore_db()
