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
        """공통 헤더 생성"""
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
        [TTTS3035R] 해외주식 체결내역 (한투 공식 권장 API)
        """
        if not self.token:
            return pd.DataFrame()

        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-ccnl"
        headers = self._get_common_headers("TTTS3035R")
        
        # 🔴 KIS 담당자가 확인해준 "작동 보장 파라미터 셋" 적용
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:],
            "PDNO": "%",              # 🔴 ""(공란) 대신 "%" 적용 (전체조회 힌트)
            "ORD_STRT_DT": start_date,
            "ORD_END_DT": end_date,
            "SLL_BUY_DVSN_CD": "00",  # 00: 전체
            "CCLD_NCCS_DVSN": "00",   # 🔴 "01"(체결) 대신 "00"(전체) 적용 (작동 사례 반영)
            "OVRS_EXCG_CD": market_code, # 외부에서 주입 (NASD, NYSE 등)
            "SORT_SQN": "DS",         
            "ORD_DT": "",             # 작동 사례대로 공란 유지
            "BRKR_ORD_SEQ": "",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

        res = requests.get(url, headers=headers, params=params)
        res_json = res.json()
        
        # 에러 발생 시 로그 출력
        if res_json.get("rt_cd") != "0":
            st.error(f"[{market_code}] KIS API 에러: {res_json.get('msg1')}")
            return pd.DataFrame()

        data = res_json.get("output", [])
        if not data:
            return pd.DataFrame()

        processed_data = []
        for item in data:
            # 🔴 미체결 건이 섞여 들어올 수 있으므로 자체 필터링
            qty = float(item.get("ccld_qty", 0))
            if qty == 0: 
                continue # 체결 수량이 0이면 스킵

            raw_date = item.get("ord_dt", "") 
            raw_time = item.get("ord_tmd", "000000") 
            if not raw_date: continue
            
            dt_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]} {raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:]}"
            
            sll_buy_dvsn = item.get("sll_buy_dvsn_cd") 
            trade_type = "Buy" if sll_buy_dvsn == "02" else "Sell" if sll_buy_dvsn == "01" else "Unknown"
            if trade_type == "Unknown": continue

            currency = "JPY" if market_code == "TYO" else ("HKD" if market_code == "SEHK" else "USD")

            processed_data.append({
                "Date": dt_str,
                "PK_HASH": "", 
                "Source": "API",
                "Currency": currency,
                "Category": "Trade",
                "Type": trade_type,
                "Ticker": item.get("pdno"),
                "Name": item.get("prdt_name", item.get("pdno")),
                "Qty": qty,
                "Price": float(item.get("ft_ccld_unpr3", 0)), 
                "Amount_Local": 0.0,
                "Amount_KRW": 0.0,
                "Note": f"{market_code} 체결"
            })

        return pd.DataFrame(processed_data)



    # ==========================================
    # 2. Audit (검증) 계층
    # ==========================================
    def fetch_settled_balance(self, market_code="NASD"):
        """[CTRP6010R] 해외주식 결제기준 잔고"""
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
        """[TTTC2101R] 해외증거금 통화별 조회"""
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
