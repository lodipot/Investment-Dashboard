import streamlit as st
import pandas as pd
import requests
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import KIS_API_Manager as kis

# 1. 설정
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="📈")
BENCHMARK_RATE = 0.035
SECTORS = {
    'SEMICON': {'emoji': '💾', 'name': '반도체', 'tickers': ['NVDA', 'AMD', 'TSM', 'INTC']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크', 'tickers': ['MSFT', 'GOOGL', 'AAPL', 'TSLA', 'AMZN']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당/방어', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'O', 'KO']},
    'REITS': {'emoji': '🏢', 'name': '리츠', 'tickers': ['PLD', 'AMT']},
    'CASH': {'emoji': '💵', 'name': '현금', 'tickers': ['💵 USD CASH']}
}

# 스타일
st.markdown("""
<style>
    .kpi-container { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }
    .kpi-cube { background-color: var(--secondary-background-color); border: 1px solid rgba(128,128,128,0.2); border-radius: 12px; padding: 15px; text-align: center; }
    .kpi-value { font-size: 1.8rem; font-weight: 800; margin: 5px 0; }
    .stock-card { background-color: var(--secondary-background-color); border: 1px solid rgba(128,128,128,0.2); border-radius: 12px; padding: 15px; margin-bottom: 10px; }
    .c-red { color: #FF5252 !important; } .c-blue { color: #448AFF !important; }
</style>
""", unsafe_allow_html=True)

# 2. 데이터 로드
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = dict(st.secrets["gcp_service_account"])
    return gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)).open("Investment_Dashboard_DB")

@st.cache_data(ttl=60)
def load_db():
    try:
        sh = get_client()
        # get_all_records() 대신 get_values()로 가져와 DataFrame 생성 (안정성)
        trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        exchange = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        dividend = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        
        # 숫자 변환
        for df in [trade, exchange, dividend]:
            for col in df.columns:
                if 'Qty' in col or 'Price' in col or 'Amount' in col or 'Rate' in col:
                     df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        return trade, exchange, dividend
    except: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# 3. 로직
def calculate_portfolio(trade_df, div_df, ex_df, current_prices, current_fx):
    rows = []
    
    # 주식
    for ticker, group in trade_df.groupby('Ticker'):
        buy = group[group['Type'] == 'Buy']
        sell = group[group['Type'] == 'Sell']
        
        qty = buy['Qty'].sum() - sell['Qty'].sum()
        if qty <= 0: continue
        
        # 평단가 (Ex_Avg_Rate 사용)
        total_buy_krw = (buy['Qty'] * buy['Price_USD'] * buy['Ex_Avg_Rate']).sum()
        avg_krw_unit = total_buy_krw / buy['Qty'].sum() if buy['Qty'].sum() > 0 else 0
        principal = avg_krw_unit * qty
        
        cur_p = current_prices.get(ticker, buy['Price_USD'].iloc[-1])
        eval_krw = qty * cur_p * current_fx
        
        div_usd = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() if not div_df.empty else 0
        div_krw = div_usd * current_fx
        
        total_profit = (eval_krw - principal) + div_krw
        
        # 안전마진
        bep = (principal - div_krw) / (qty * cur_p) if (qty * cur_p) > 0 else 0
        margin = current_fx - bep

        rows.append({
            'Ticker': ticker, 'Name': group['Name'].iloc[0], 'Qty': qty,
            'Principal': principal, 'Eval': eval_krw, 'Profit': total_profit,
            'Div': div_krw, 'Margin': margin
        })
        
    # 현금 (Exchange_Log 기준)
    if not ex_df.empty:
        last = ex_df.iloc[-1]
        cash_usd = last['Balance']
        cash_rate = last['Avg_Rate']
        
        rows.append({
            'Ticker': '💵 USD CASH', 'Name': '달러예수금', 'Qty': cash_usd,
            'Principal': cash_usd * cash_rate, 'Eval': cash_usd * current_fx,
            'Profit': (cash_usd * current_fx) - (cash_usd * cash_rate),
            'Div': 0, 'Margin': 9999
        })
        
    return pd.DataFrame(rows)

# 4. API 동기화
def sync_data():
    try:
        sh = get_client()
        trade_ws = sh.worksheet("Trade_Log")
        existing_ids = pd.DataFrame(trade_ws.get_all_records())['Order_ID'].astype(str).tolist()
        
        # 평단가 가져오기
        ex_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        cur_rate = float(ex_df['Avg_Rate'].iloc[-1]) if not ex_df.empty else 1450.0

        # API 호출
        token = kis.get_access_token()
        headers = {"content-type":"application/json", "authorization":f"Bearer {token}", "appkey":st.secrets["kis_api"]["APP_KEY"], "appsecret":st.secrets["kis_api"]["APP_SECRET"], "tr_id":"CTOS4001R"}
        params = {"CANO": st.secrets["kis_api"]["CANO"], "ACNT_PRDT_CD": st.secrets["kis_api"]["ACNT_PRDT_CD"], "ERLM_STRT_DT": "20260125", "ERLM_END_DT": datetime.now().strftime("%Y%m%d"), "SLL_BUY_DVSN_CD": "00", "CCLD_DVSN": "00", "OVRS_EXCG_CD": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
        
        res = requests.get(f"{st.secrets['kis_api']['URL_BASE']}/uapi/overseas-stock/v1/trading/inquire-period-trans", headers=headers, params=params)
        data = res.json()
        
        new_rows = []
        if data['rt_cd'] == '0':
            for item in data['output1']:
                if '매수' in item['sll_buy_dvsn_name'] or '매도' in item['sll_buy_dvsn_name']:
                    qty = int(float(item['ccld_qty']))
                    oid = f"API_{item['trad_dt']}_{item['pdno']}_{qty}"
                    if qty > 0 and oid not in existing_ids:
                        price = float(item.get('ft_ccld_unpr2', 0)) or float(item.get('ovrs_stck_ccld_unpr', 0))
                        new_rows.append([
                            f"{item['trad_dt'][:4]}-{item['trad_dt'][4:6]}-{item['trad_dt'][6:]}",
                            oid, item['pdno'], item['ovrs_item_name'],
                            'Buy' if '매수' in item['sll_buy_dvsn_name'] else 'Sell',
                            qty, price, cur_avg_rate, "API_Sync"
                        ])
        
        if new_rows:
            new_rows.sort(key=lambda x: x[0])
            trade_ws.append_rows(new_rows)
            return True, f"{len(new_rows)}건 업데이트"
        return True, "최신 상태"
    except Exception as e: return False, str(e)

# 5. UI 실행
tab1, tab2 = st.tabs(["📊 대시보드", "⚙️ 관리"])

with tab1:
    trade, ex, div = load_db()
    if trade.empty: st.error("DB 연결 실패")
    else:
        # 시세 조회 (간략화)
        try: fx = yf.Ticker("KRW=X").history(period="1d")['Close'].iloc[-1]
        except: fx = 1450.0
        
        prices = {}
        for t in trade['Ticker'].unique():
            if t != '💵 USD CASH':
                try: prices[t] = kis.get_current_price(t)
                except: pass
                
        pf = calculate_portfolio(trade, div, ex, prices, fx)
        
        # KPI
        tot_eval = pf['Eval'].sum()
        roi = pf['Profit'].sum() / pf['Principal'].sum() * 100 if pf['Principal'].sum() else 0
        
        st.markdown(f"""
        <div class="kpi-container">
            <div class="kpi-cube"><div class="kpi-title">총 평가액</div><div class="kpi-value">{tot_eval/10000:,.0f}만</div></div>
            <div class="kpi-cube"><div class="kpi-title">수익률</div><div class="kpi-value {'c-red' if roi>0 else 'c-blue'}">{roi:+.2f}%</div><div class="kpi-sub">Benchmark {BENCHMARK_RATE*100}%</div></div>
            <div class="kpi-cube"><div class="kpi-title">환율</div><div class="kpi-value">{fx:,.1f}원</div></div>
        </div>""", unsafe_allow_html=True)
        
        st.dataframe(pf)

with tab2:
    if st.button("🔄 동기화"):
        res, msg = sync_data()
        if res: st.success(msg); time.sleep(1); st.rerun()
        else: st.error(msg)
