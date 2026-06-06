import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import re
import hashlib
import yfinance as yf
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# [1] 설정 및 CSS (에러 박스 숨김 포함)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="🏦")

if 'price_cache' not in st.session_state: st.session_state['price_cache'] = {}
if 'needs_fetch' not in st.session_state: st.session_state['needs_fetch'] = True
if 'parsed_data' not in st.session_state: st.session_state['parsed_data'] = []

st.markdown("""
<style>
    div[data-testid="stModal"], div[data-testid="stConnectionStatus"] { display: none !important; }
    .stock-card { background-color: #18181A; border-radius: 16px; padding: 20px; margin-bottom: 16px; border: 1px solid #444746; border-left: 6px solid #555; }
    .card-up { border-left-color: #FF5252 !important; }
    .card-down { border-left-color: #448AFF !important; }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .card-ticker { font-size: 1.4rem; font-weight: 900; color: #E3E3E3; }
    .card-main-val { font-size: 1.6rem; font-weight: 800; color: #E3E3E3; text-align: right; }
    .input-card { background-color: #1E1E1E; padding: 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #333; }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------------
# [2] 통합 데이터 처리 엔진 (Single Engine)
# -------------------------------------------------------------------
def generate_pk(date, ticker, t_type):
    return "K-" + hashlib.md5(f"{date}_{ticker}_{t_type}".encode()).hexdigest()[:8]

@st.cache_resource
def get_gsheet_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']))

@st.cache_data
def load_unified_ledger():
    sh = get_gsheet_client().open("Investment_Dashboard_DB")
    ws = sh.worksheet("Global_Unified_Ledger")
    df = pd.DataFrame(ws.get_all_records())
    return df

def run_unified_engine(df):
    # 각 통화별 지표 초기화
    cash = {'USD': 0.0, 'JPY': 0.0, 'KRW': 0.0}
    avg_rate = {'USD': 0.0, 'JPY': 0.0}
    port = {} # {ticker: {qty, invested_k, invested_f, ...}}
    
    # 시간순 정렬 후 엔진 구동
    df['Date_Obj'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date_Obj')
    
    for _, row in df.iterrows():
        c, cat, typ, tkr = row['Currency'], row['Category'], row['Type'].lower(), row['Ticker']
        qty, price, amt_l, amt_k = float(row['Qty']), float(row['Price']), float(row['Amount_Local']), float(row['Amount_KRW'])
        
        if tkr not in port and tkr != '-':
            port[tkr] = {'qty': 0, 'invested_k': 0, 'invested_f': 0, 'realized_k': 0, 'div_f': 0, 'currency': c}
        
        # [Money] 로직
        if cat == 'Money':
            if typ == 'deposit': cash[c] += amt_k if c == 'KRW' else amt_l
            elif typ == 'krw_to_usd': # 예시 환전
                avg_rate['USD'] = ((cash['USD'] * avg_rate['USD']) + amt_k) / (cash['USD'] + amt_l)
                cash['USD'] += amt_l; cash['KRW'] -= amt_k
            # ... (환전, 배당, 입출금 로직을 통화별로 확장)
            
        # [Trade] 로직
        elif cat == 'Trade':
            # ... (매수/매도 시 포트폴리오 데이터 갱신)
            pass
            
    return cash, port

# -------------------------------------------------------------------
# [3] Main UI (국가별 KPI 큐브 중심)
# -------------------------------------------------------------------
def main():
    df = load_unified_ledger()
    # 엔진 호출 및 결과 대시보드 반영...
    st.title("🚀 Global Unified Dashboard")
    
    # 5대 KPI 큐브 배치
    col1, col2, col3, col4, col5 = st.columns(5)
    # 각 큐브에 자산/손익/상세 버튼 배치
    
    # 기존 대시보드 탭 로직 호출
    
if __name__ == "__main__":
    main()
