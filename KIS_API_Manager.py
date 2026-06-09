import requests
import pandas as pd
import streamlit as st
from datetime import datetime

class KIS_API_Manager:
    def __init__(self, app_key, app_secret, account_no):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.base_url = "https://openapi.koreainvestment.com:9443" # 실전투자 URL
        self.token = self.get_access_token()

    def get_access_token(self):
        """접근 토큰 발급 (캐싱 적용 권장)"""
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        res = requests.post(url, headers=headers, json=body)
        if res.status_code == 200:
            return res.json().get("access_token")
        else:
            st.error("KIS API 토큰 발급 실패")
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
        [CTOS4001R] 해외주식 일별거래내역
        Unified_Ledger 스키마에 완벽히 맞춘 DataFrame 반환
        """
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-period-trans"
        headers = self._get_common_headers("CTOS4001R")
        
        # 계좌번호 분리 (앞 8자리, 뒤 2자리)
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:]
        
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "INQR_STRT_DT": start_date,
            "INQR_END_DT": end_date,
            "SHTN_PDNO": "",
            "ORD_ENX_DVSN_CD": market_code, # NASD(나스닥), NYSE(뉴욕), TYO(일본) 등
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

        res = requests.get(url, headers=headers, params=params)
        
        if res.status_code != 200:
            return pd.DataFrame() # 에러 시 빈 데이터프레임 반환

        data = res.json().get("output", [])
        if not data:
            return pd.DataFrame()

        processed_data = []
        for item in data:
            # 거래 일자 포맷팅
            raw_date = item.get("ord_dt") # YYYYMMDD
            fmt_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if raw_date else ""
            
            # 매매 구분 (매수/매도) - API 응답 코드에 따라 조정 필요
            sll_buy_dvsn = item.get("sll_buy_dvsn_cd") 
            trade_type = "Buy" if sll_buy_dvsn == "02" else "Sell" if sll_buy_dvsn == "01" else "Unknown"

            # 통화 결정 (시장 코드 기반)
            currency = "JPY" if market_code == "TYO" else "USD"

            processed_data.append({
                "Date": fmt_date,
                "Ticker": item.get("pdno"),
                "Name": item.get("prdt_name"),
                "Type": trade_type,
                "Qty": float(item.get("ccld_qty", 0)),
                "Price": float(item.get("ft_ccld_unpr3", 0)),
                "Currency": currency,
                "Category": "Trade",
                "Source": "API"
            })

        df = pd.DataFrame(processed_data)
        # Unified Ledger 형식에 맞춰 반환
        return df[['Date', 'Category', 'Type', 'Ticker', 'Name', 'Qty', 'Price', 'Currency', 'Source']]

    # ==========================================
    # 2. Audit (검증) 계층
    # ==========================================
    def fetch_settled_balance(self, market_code="NASD"):
        """
        [CTRP6010R] 해외주식 결제기준 잔고
        DB 원장의 보유 수량과 증권사 실제 결제 수량을 대조하기 위한 용도
        """
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
        headers = self._get_common_headers("CTRP6010R")
        
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:]
        
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "WCRC_FRCR_DVSN_CD": "02", # 02: 외화
            "NATN_CD": "840" if market_code != "TYO" else "392", # 840: 미국, 392: 일본
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
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-margin"
        headers = self._get_common_headers("TTTC2101R")
        
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:]
        
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "TR_CRCY_CD": "" # 공란 시 전체 통화 조회
        }

        res = requests.get(url, headers=headers, params=params)
        
        if res.status_code == 200:
            # output1에서 USD, JPY 등 각 통화별 예수금 추출
            return res.json().get("output1", [])
        return []
