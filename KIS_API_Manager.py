import requests
import json
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

class KIS_API_Manager:
    def __init__(self, app_key, app_secret, account_no):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.token = self._get_valid_token()

    def _get_sheet_client(self):
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)

    def _get_valid_token(self):
        try:
            client = self._get_sheet_client()
            sh = client.open("Investment_Dashboard_DB")
            ws = sh.worksheet("Token_Storage")
            
            records = ws.get_all_records()
            if records:
                token_info = records[0]
                issued_time_str = token_info.get("Issued_Time", "")
                saved_token = token_info.get("Token", "")
                
                if issued_time_str and saved_token:
                    issued_time = datetime.strptime(issued_time_str, "%Y-%m-%d %H:%M:%S")
                    if (datetime.now() - issued_time).total_seconds() < 23 * 3600:
                        return saved_token
            return self._issue_new_token(ws)
        except Exception as e:
            st.error(f"토큰 스토리지 오류: {e}")
            return None

    def _issue_new_token(self, ws):
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        res = requests.post(url, headers=headers, json=body)
        if res.status_code == 200:
            token = res.json().get("access_token")
            issued_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ws.clear()
            ws.update([["Token", "Issued_Time"], [token, issued_time]])
            return token
        else:
            error_detail = res.json().get('msg1', res.text)
            st.error(f"🚫 KIS API 토큰 발급 거절 사유: {error_detail}")
            return None

    def _get_common_headers(self, tr_id):
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P"
        }

    def fetch_trade_history(self, start_date, end_date):
        """
        [CTOS4001R] 해외주식 일별거래내역 (장기 데이터 영구 보존용)
        - 시장 구분 없이(00) 한 번에 30일 단위로 싹쓸이
        """
        if not self.token:
            return pd.DataFrame()

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-period-trans"
        headers = self._get_common_headers("CTOS4001R")
        
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        
        processed_data = []
        current_start = start_dt
        
        while current_start <= end_dt:
            current_end = min(current_start + timedelta(days=30), end_dt)
            
            params = {
                "CANO": self.account_no[:8],
                "ACNT_PRDT_CD": self.account_no[8:],
                "INQR_STRT_DT": current_start.strftime("%Y%m%d"),
                "INQR_END_DT": current_end.strftime("%Y%m%d"),
                "SHTN_PDNO": "",              # 한투 공식 가이드: 공란 시 전체 종목
                "ORD_ENX_DVSN_CD": "00",      # 00: 전체 국가/시장 한 번에 조회
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": ""
            }

            res = requests.get(url, headers=headers, params=params)
            res_json = res.json()
            
            # 눈으로 직접 확인할 수 있도록 디버그 패널 출력 (정상/실패 모두 노출)
            with st.expander(f"🔍 [디버그] 통합조회 ({current_start.strftime('%Y-%m-%d')} ~ {current_end.strftime('%Y-%m-%d')})"):
                st.write(f"**요청 파라미터:** {params}")
                st.json(res_json)
            
            if res_json.get("rt_cd") == "0":
                data = res_json.get("output", [])
                for item in data:
                    # CTOS4001R은 시간 제공을 안하므로 00:00:00 으로 기록
                    raw_date = item.get("trad_dt", "") 
                    if not raw_date: continue
                    dt_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]} 00:00:00"
                    
                    sll_buy_dvsn = item.get("sll_buy_dvsn_cd") 
                    trade_type = "Buy" if sll_buy_dvsn == "02" else "Sell" if sll_buy_dvsn == "01" else "Unknown"
                    if trade_type == "Unknown": continue

                    ticker = item.get("pdno", "")
                    currency = "JPY" if ticker.isdigit() else "USD"

                    processed_data.append({
                        "Date": dt_str,
                        "PK_HASH": "", 
                        "Source": "API",
                        "Currency": currency,
                        "Category": "Trade",
                        "Type": trade_type,
                        "Ticker": ticker,
                        "Name": item.get("ovrs_item_name", ticker),
                        "Qty": float(item.get("ccld_qty", 0)),
                        "Price": float(item.get("ft_ccld_unpr2", 0)), 
                        "Amount_Local": 0.0,
                        "Amount_KRW": 0.0,
                        "Note": "API 자동동기화"
                    })

            current_start = current_end + timedelta(days=1)

        return pd.DataFrame(processed_data)
