import requests
import json
import pandas as pd
import streamlit as st
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

class KIS_API_Manager:
    def __init__(self, app_key, app_secret, account_no):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.base_url = "https://openapi.koreainvestment.com:9443" # 실전투자 URL
        
        # 단순 발급이 아닌, 구글 시트를 거치는 토큰 캐싱 매서드로 교체
        self.token = self._get_valid_token()

    # ==========================================
    # 0. 토큰 스토리지 (캐싱) 및 공통 헤더 계층
    # ==========================================
    def _get_sheet_client(self):
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)

    def _get_valid_token(self):
        """구글 시트(Token_Storage)에서 토큰을 읽어오고 만료되었으면 갱신합니다."""
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
                    # 유효기간 24시간: 안전하게 23시간 이내면 기존 토큰 재사용
                    if (datetime.now() - issued_time).total_seconds() < 23 * 3600:
                        return saved_token
                        
            return self._issue_new_token(ws)
        except Exception as e:
            st.error(f"토큰 스토리지 접근 오류 (시트가 없거나 권한 문제): {e}")
            return None

def _issue_new_token(self, ws):
        """KIS API에 새 토큰을 요청하고 구글 시트에 저장합니다."""
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
            # 시트에 엎어치기로 저장 (이때 카톡 알림 1회 발송됨)
            ws.clear()
            ws.update([["Token", "Issued_Time"], [token, issued_time]])
            return token
        else:
            # 🔴 여기서 한투 서버가 뱉어내는 '진짜 거절 사유'를 화면에 띄웁니다.
            error_detail = res.json().get('msg1', res.text)
            st.error(f"🚫 KIS API 토큰 발급 거절 사유: {error_detail}")
            return None

    def _get_common_headers(self, tr_id):
        """공통 헤더 생성 (PM님 원본 유지)"""
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P" # 개인
        }

    # ==========================================
    # 1. 원장 생성 계층 (Unified Ledger용)
    # ==========================================
    def fetch_trade_history(self, start_date, end_date, market_code="NASD"):
        """
        [CTOS4001R] 해외주식 일별거래내역 (PM님 원본 유지)
        Unified_Ledger 13개 스키마에 완벽히 맞춘 DataFrame 반환
        """
        if not self.token:
            return pd.DataFrame()

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-period-trans"
        headers = self._get_common_headers("CTOS4001R")
        
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:]
        
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "INQR_STRT_DT": start_date,
            "INQR_END_DT": end_date,
            "SHTN_PDNO": "",
            "ORD_ENX_DVSN_CD": market_code, 
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

        res = requests.get(url, headers=headers, params=params)
        
        if res.status_code != 200:
            return pd.DataFrame()

        data = res.json().get("output", [])
        if not data:
            return pd.DataFrame()

        processed_data = []
        for item in data:
            # 거래 일자 및 시간 포맷팅 (시간 정보가 있으면 살리고 없으면 00:00:00)
            raw_date = item.get("ord_dt", "") # YYYYMMDD
            raw_time = item.get("ord_tmd", "000000") # HHMMSS
            if not raw_date: continue
            
            dt_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]} {raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:]}"
            
            sll_buy_dvsn = item.get("sll_buy_dvsn_cd") 
            trade_type = "Buy" if sll_buy_dvsn == "02" else "Sell" if sll_buy_dvsn == "01" else "Unknown"
            
            if trade_type == "Unknown": continue

            currency = "JPY" if market_code == "TYO" else ("HKD" if market_code == "SEHK" else "USD")

            # 13개 RAW DB 스키마에 정확히 매핑
            processed_data.append({
                "Date": dt_str,
                "PK_HASH": "", # Dashboard.py에서 나중에 해시 생성됨
                "Source": "API",
                "Currency": currency,
                "Category": "Trade",
                "Type": trade_type,
                "Ticker": item.get("pdno"),
                "Name": item.get("prdt_name"),
                "Qty": float(item.get("ccld_qty", 0)),
                "Price": float(item.get("ft_ccld_unpr3", 0)),
                "Amount_Local": 0.0,
                "Amount_KRW": 0.0,
                "Note": f"{market_code} 자동동기화"
            })

        return pd.DataFrame(processed_data)

    # ==========================================
    # 2. Audit (검증) 계층 (PM님 원본 유지)
    # ==========================================
    def fetch_settled_balance(self, market_code="NASD"):
        """
        [CTRP6010R] 해외주식 결제기준 잔고
        DB 원장의 보유 수량과 증권사 실제 결제 수량을 대조하기 위한 용도
        """
        if not self.token: return []
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
        headers = self._get_common_headers("CTRP6010R")
        
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:],
            "WCRC_FRCR_DVSN_CD": "02", 
            "NATN_CD": "840" if market_code != "TYO" else "392", 
            "TR_MKET_CD": "00", 
            "INQR_DVSN_CD": "00"
        }

        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200:
            return res.json().get("output1", [])
        return []

    def fetch_foreign_currency_balance(self):
        """
        [TTTC2101R] 해외증거금 통화별 조회
        USD 저수지와 JPY 저수지의 실제 예수금(Cash) 현황을 각각 분리하여 가져옴
        """
        if not self.token: return []
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-margin"
        headers = self._get_common_headers("TTTC2101R")
        
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:],
            "TR_CRCY_CD": "" 
        }

        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200:
            return res.json().get("output1", [])
        return []
