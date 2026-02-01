import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import time
import yfinance as yf
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# [1] 설정 & 스타일
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Command", layout="wide", page_icon="🏦")

st.markdown("""
<style>
    /* KPI Grid */
    .kpi-container {
        display: grid;
        grid-template-columns: 2fr 1.5fr 1.5fr;
        gap: 15px;
        margin-bottom: 20px;
    }
    .kpi-card {
        background-color: #1E1E1E;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #333;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .kpi-title { font-size: 1rem; color: #AAAAAA; margin-bottom: 5px; }
    .kpi-main { font-size: 2rem; font-weight: bold; color: #FFFFFF; }
    .kpi-sub { font-size: 1rem; margin-top: 5px; font-weight: 500; }
    .kpi-red { color: #FF5252; }
    .kpi-blue { color: #448AFF; }
    
    /* Stock Card */
    .stock-card {
        background-color: #262626;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 15px;
        border-left: 5px solid #555;
    }
    .card-up { border-left-color: #FF5252 !important; }
    .card-down { border-left-color: #448AFF !important; }
    
    .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
    .card-ticker { font-size: 1.4rem; font-weight: 800; color: #FFF; }
    .card-main-val { font-size: 1.5rem; font-weight: bold; color: #FFF; text-align: right; }
    .card-sub-val { font-size: 0.95rem; text-align: right; margin-top: -5px;}
    
    /* Expander Table inside Card */
    .detail-table { width: 100%; font-size: 0.85rem; color: #DDD; margin-top: 10px; border-top: 1px solid #444; }
    .detail-table td { padding: 4px 0; }
    .text-right { text-align: right; }
    
    /* Global Badges */
    .badge { padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; color: #fff;}
    .badge-buy { background-color: #FF5252; }
    .badge-sell { background-color: #448AFF; }
    .badge-div { background-color: #4CAF50; }
    .badge-ex { background-color: #757575; }
</style>
""", unsafe_allow_html=True)

# 섹터 및 순서 정의
SECTOR_ORDER = {
    '배당': ['O', 'JEPI', 'JEPQ', 'SCHD', 'MAIN', 'KO'],
    '테크': ['GOOGL', 'NVDA', 'AMD', 'TSM', 'MSFT', 'AAPL', 'AMZN', 'TSLA', 'AVGO', 'SOXL'],
    '리츠': ['PLD', 'AMT'],
    '기타': []
}

# -------------------------------------------------------------------
# [2] 데이터 로드 및 유틸리티
# -------------------------------------------------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def safe_float(val):
    if pd.isna(val) or val == '' or val == '-': return 0.0
    try: return float(str(val).replace(',', '').strip())
    except: return 0.0

def load_data():
    client = get_gsheet_client()
    sh = client.open("Investment_Dashboard_DB")
    
    # Money_Log 통합 (Exchange + Dividend)
    df_money = pd.DataFrame(sh.worksheet("Money_Log").get_all_records())
    df_trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
    
    # 공백 제거
    df_money.columns = df_money.columns.str.strip()
    df_trade.columns = df_trade.columns.str.strip()
    
    return df_trade, df_money, sh

def get_realtime_rate():
    try:
        ticker = yf.Ticker("KRW=X")
        data = ticker.history(period="1d")
        if not data.empty:
            return data['Close'].iloc[-1]
    except:
        pass
    return 1450.0

# -------------------------------------------------------------------
# [3] 달러 저수지 엔진 (Fill-Forward Logic)
# -------------------------------------------------------------------
def process_timeline(df_trade, df_money, sheet_instance):
    """
    모든 거래를 Order_ID 순으로 나열하고, 
    빈칸(Rate, Balance)을 순차적으로 계산하여 채움 + 포트폴리오 집계
    """
    # 1. 타임라인 병합
    df_money['Source'] = 'Money'
    df_trade['Source'] = 'Trade'
    
    if 'Order_ID' not in df_money.columns: df_money['Order_ID'] = 0
    if 'Order_ID' not in df_trade.columns: df_trade['Order_ID'] = 0
    
    timeline = pd.concat([df_money, df_trade], ignore_index=True)
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    timeline = timeline.sort_values(by=['Order_ID', 'Date'])
    
    # 2. 순차 계산
    current_balance = 0.0
    current_avg_rate = 0.0
    total_krw_invested = 0.0 
    
    # 포트폴리오 집계용
    portfolio = {} # {tk: {'qty':, 'invested_usd':, 'realized_pl':, 'accum_div':}}
    
    for idx, row in timeline.iterrows():
        source = row['Source']
        
        # --- [A] Money Log ---
        if source == 'Money':
            t_type = str(row.get('Type', '')).lower()
            usd_amt = safe_float(row.get('USD_Amount'))
            krw_amt = safe_float(row.get('KRW_Amount'))
            ticker = str(row.get('Ticker', '')).strip()
            
            # 배당금 집계 (종목별)
            if 'dividend' in t_type or '배당' in t_type:
                if ticker and ticker != '-':
                    if ticker not in portfolio: portfolio[ticker] = {'qty':0, 'invested_usd':0, 'realized_pl':0, 'accum_div':0}
                    portfolio[ticker]['accum_div'] += usd_amt
                
            # 잔고/평단 계산
            current_balance += usd_amt
            
            if 'dividend' not in t_type and '배당' not in t_type:
                total_krw_invested += krw_amt
                
            if current_balance > 0.0001:
                prev_val = (current_balance - usd_amt) * current_avg_rate
                added_val = 0 if ('dividend' in t_type or '배당' in t_type) else krw_amt
                current_avg_rate = (prev_val + added_val) / current_balance
            
            # 빈칸 채우기 (메모리상) - 실제 업데이트는 나중에
            df_money.loc[df_money['Order_ID'] == row['Order_ID'], 'Avg_Rate'] = current_avg_rate
            df_money.loc[df_money['Order_ID'] == row['Order_ID'], 'Balance'] = current_balance
            
        # --- [B] Trade Log ---
        elif source == 'Trade':
            t_type = str(row.get('Type', '')).lower()
            qty = safe_float(row.get('Qty'))
            price = safe_float(row.get('Price_USD'))
            amount = qty * price
            ticker = str(row.get('Ticker', '')).strip()
            
            if ticker not in portfolio: portfolio[ticker] = {'qty':0, 'invested_usd':0, 'realized_pl':0, 'accum_div':0}
            
            if 'buy' in t_type or '매수' in t_type:
                current_balance -= amount
                # 포트폴리오 업데이트
                portfolio[ticker]['qty'] += qty
                portfolio[ticker]['invested_usd'] += amount
                
                # Ex_Avg_Rate 채우기
                if safe_float(row.get('Ex_Avg_Rate')) == 0:
                    df_trade.loc[df_trade['Order_ID'] == row['Order_ID'], 'Ex_Avg_Rate'] = current_avg_rate
                    
            elif 'sell' in t_type or '매도' in t_type:
                current_balance += amount
                # 실현손익 계산 (평단 기준)
                if portfolio[ticker]['qty'] > 0:
                    avg_price = portfolio[ticker]['invested_usd'] / portfolio[ticker]['qty']
                    pl = (price - avg_price) * qty
                    portfolio[ticker]['realized_pl'] += pl
                    
                    portfolio[ticker]['qty'] -= qty
                    portfolio[ticker]['invested_usd'] -= (qty * avg_price)

    return df_trade, df_money, current_balance, current_avg_rate, total_krw_invested, portfolio

# -------------------------------------------------------------------
# [4] API 동기화 및 저장 (Sync)
# -------------------------------------------------------------------
def sync_api_data(sheet_instance, df_trade, df_money):
    ws_trade = sheet_instance.worksheet("Trade_Log")
    ws_money = sheet_instance.worksheet("Money_Log")
    
    # Next Order ID
    max_id = max(pd.to_numeric(df_trade['Order_ID'], errors='coerce').max(), pd.to_numeric(df_money['Order_ID'], errors='coerce').max())
    next_order_id = int(max_id) + 1 if not pd.isna(max_id) else 1
    
    # Last Date
    last_date_str = "20260101"
    if not df_trade.empty:
        last_date = pd.to_datetime(df_trade['Date']).max()
        last_date_str = last_date.strftime("%Y%m%d")
        
    end_date_str = datetime.now().strftime("%Y%m%d")
    
    # API Call
    with st.spinner(f"API 데이터 수신 중..."):
        res = kis.get_trade_history(last_date_str, end_date_str)
        
    if not res: return
    
    api_list = res.get('output1', [])
    if api_list:
        new_rows = []
        keys = set(f"{r['Date']}_{r['Ticker']}_{safe_float(r['Qty'])}" for _, r in df_trade.iterrows())
        
        for item in reversed(api_list):
            dt = datetime.strptime(item['dt'], "%Y%m%d").strftime("%Y-%m-%d")
            tk = item['pdno']
            qty = int(item['ccld_qty'])
            price = float(item['ft_ccld_unpr3'])
            side = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
            
            key = f"{dt}_{tk}_{float(qty)}"
            if key in keys: continue
            
            new_rows.append([
                dt, next_order_id, tk, item['prdt_name'], side, qty, price, "", "API_Auto"
            ])
            next_order_id += 1
            
        if new_rows:
            ws_trade.append_rows(new_rows)
            st.success(f"{len(new_rows)}건 업데이트 완료")
            df_trade = pd.DataFrame(ws_trade.get_all_records()) # Reload for calc
            
    # Recalculate & Fill Blanks
    updated_trade, updated_money, _, _, _, _ = process_timeline(df_trade, df_money, sheet_instance)
    
    # Update Google Sheets (Full Update for safety)
    ws_trade.update([updated_trade.columns.values.tolist()] + updated_trade.astype(str).values.tolist())
    ws_money.update([updated_money.columns.values.tolist()] + updated_money.astype(str).values.tolist())
    
    st.toast("동기화 및 재계산 완료!")
    time.sleep(1)
    st.rerun()

# -------------------------------------------------------------------
# [5] 메인 앱
# -------------------------------------------------------------------
def main():
    try:
        df_trade, df_money, sheet_instance = load_data()
    except Exception as e:
        st.error(f"DB 연결 실패: {e}")
        st.stop()
        
    # 엔진 가동
    u_trade, u_money, cur_bal, cur_rate, total_krw_input, portfolio = process_timeline(df_trade, df_money, sheet_instance)
    cur_real_rate = get_realtime_rate()
    
    # 현재가 조회 (API)
    active_tickers = [t for t in portfolio if portfolio[t]['qty'] > 0]
    prices = {}
    if active_tickers:
        with st.spinner("시장가 조회 중..."):
            for t in active_tickers:
                prices[t] = kis.get_current_price(t)
                
    # 전체 자산 가치
    stock_val_usd = sum([portfolio[t]['qty'] * prices.get(t, 0) for t in active_tickers])
    total_asset_usd = stock_val_usd + cur_bal
    
    # 원화 환산
    total_asset_krw_real = total_asset_usd * cur_real_rate
    total_pl_krw = total_asset_krw_real - total_krw_input
    pl_pct = (total_pl_krw / total_krw_input * 100) if total_krw_input > 0 else 0
    
    # 안전마진
    bep_rate = total_krw_input / total_asset_usd if total_asset_usd > 0 else 0
    safety_margin = cur_real_rate - bep_rate

    # --- UI ---
    
    # Header
    c1, c2 = st.columns([3, 1])
    now = datetime.now()
    status = "🟢 Live" if (23 <= now.hour or now.hour < 6) else "🔴 Closed"
    with c1:
        st.title("🚀 Investment Command Center")
        st.caption(f"{status} | Last Update: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    with c2:
        if st.button("🔄 데이터 동기화 (Sync)", use_container_width=True):
            sync_api_data(sheet_instance, df_trade, df_money)

    # KPI Cube
    kpi_html = f"""
    <div class="kpi-container">
        <div class="kpi-card">
            <div class="kpi-title">총 자산 (Total Assets)</div>
            <div class="kpi-main">₩ {total_asset_krw_real:,.0f}</div>
            <div class="kpi-sub {'kpi-red' if total_pl_krw >= 0 else 'kpi-blue'}">
                {'▲' if total_pl_krw >= 0 else '▼'} {abs(total_pl_krw):,.0f} ({pl_pct:+.2f}%)
            </div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">달러 저수지 (Reservoir)</div>
            <div class="kpi-main">$ {cur_bal:,.2f}</div>
            <div class="kpi-sub">Avg Rate: ₩ {cur_rate:,.2f}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">안전마진 (Safety Margin)</div>
            <div class="kpi-main">{safety_margin:+.2f} 원</div>
            <div class="kpi-sub">BEP: ₩ {bep_rate:,.2f}</div>
        </div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["🕹️ 입력 매니저", "📊 대시보드", "📜 통합 로그"])
    
    # [Tab 1] 입력 매니저
    with tab1:
        st.subheader("📝 환전 & 배당 입력")
        with st.form("input_form"):
            c1, c2 = st.columns(2)
            i_type = c1.radio("유형", ["KRW_to_USD", "Dividend"], horizontal=True)
            i_date = c2.date_input("날짜")
            
            c3, c4, c5 = st.columns(3)
            i_usd = c3.number_input("금액 (USD)", min_value=0.01, step=0.01)
            i_krw = c4.number_input("원화 (KRW)", min_value=0, disabled=(i_type=="Dividend"))
            i_ticker = c5.text_input("종목코드 (배당용)", disabled=(i_type=="KRW_to_USD"))
            
            i_note = st.text_input("비고", "수기입력")
            
            if st.form_submit_button("💾 저장하기"):
                max_id = max(pd.to_numeric(u_trade['Order_ID']).max(), pd.to_numeric(u_money['Order_ID']).max())
                next_id = int(max_id) + 1
                
                rate = i_krw / i_usd if i_type=="KRW_to_USD" and i_usd > 0 else 0
                tk_val = i_ticker if i_type=="Dividend" else "-"
                
                ws_money = sheet_instance.worksheet("Money_Log")
                ws_money.append_row([
                    i_date.strftime("%Y-%m-%d"), next_id, i_type, tk_val,
                    i_krw if i_type=="KRW_to_USD" else 0, i_usd,
                    rate, "", "", i_note # Avg, Bal은 Sync시 계산
                ])
                st.success("저장되었습니다! (Sync 버튼을 눌러 반영하세요)")
                
    # [Tab 2] 대시보드 (Cards + Detail Table)
    with tab2:
        # Card View
        for cat, t_list in SECTOR_ORDER.items():
            valid_list = [t for t in t_list if t in portfolio and portfolio[t]['qty'] > 0]
            if not valid_list: continue
            
            st.subheader(f"{cat}")
            cols = st.columns(4)
            idx = 0
            for tk in valid_list:
                data = portfolio[tk]
                cur_p = prices.get(tk, 0)
                
                # 계산
                total_invested_usd = data['invested_usd'] # 매수 원금 ($)
                eval_val_usd = data['qty'] * cur_p # 현재 평가액 ($)
                
                total_pl_usd = (eval_val_usd - total_invested_usd) + data['realized_pl'] + data['accum_div']
                total_ret_pct = (total_pl_usd / total_invested_usd * 100) if total_invested_usd > 0 else 0
                
                # Style
                color = "card-up" if total_pl_usd >= 0 else "card-down"
                font_c = "#FF5252" if total_pl_usd >= 0 else "#448AFF"
                arrow = "▲" if total_pl_usd >= 0 else "▼"
                
                html = f"""
                <div class="stock-card {color}">
                    <div class="card-header">
                        <span class="card-ticker">{tk}</span>
                        <span class="card-price" style="color:#FFF">${cur_p:.2f}</span>
                    </div>
                    <div style="text-align:right; margin-bottom:10px;">
                        <div class="card-main-val">${eval_val_usd:,.2f}</div>
                        <div class="card-sub-val" style="color:{font_c}">
                            {arrow} ${abs(total_pl_usd):,.2f} ({total_ret_pct:+.1f}%)
                        </div>
                    </div>
                    <details>
                        <summary style="font-size:0.8rem; color:#888; cursor:pointer;">상세 내역 보기</summary>
                        <table class="detail-table">
                            <tr><td>보유수량</td><td class="text-right">{data['qty']:.0f}주</td></tr>
                            <tr><td>매수평단</td><td class="text-right">${(data['invested_usd']/data['qty']):.2f}</td></tr>
                            <tr><td>평가손익</td><td class="text-right">${(eval_val_usd - total_invested_usd):,.2f}</td></tr>
                            <tr><td>실현손익</td><td class="text-right">${data['realized_pl']:,.2f}</td></tr>
                            <tr><td>누적배당</td><td class="text-right">${data['accum_div']:,.2f}</td></tr>
                        </table>
                    </details>
                </div>
                """
                with cols[idx % 4]:
                    st.markdown(html, unsafe_allow_html=True)
                idx += 1
        
        st.divider()
        st.subheader("📋 통합 상세 현황 (Integrated Table)")
        
        table_rows = []
        for tk in active_tickers:
            data = portfolio[tk]
            cur_p = prices.get(tk, 0)
            
            # Values
            qty = data['qty']
            avg_usd = data['invested_usd'] / qty if qty > 0 else 0
            
            # 1. 평가손익 (주가변동) = (현재가 - 평단) * 수량 * 현재환율
            eval_pl_usd = (cur_p - avg_usd) * qty
            eval_pl_krw = eval_pl_usd * cur_real_rate
            
            # 2. 환손익 = 투자원금($) * (현재환율 - 내평단환율)
            # *내평단환율은 전체 계좌 평균(cur_rate) 사용 (저수지 모델)
            fx_pl_krw = data['invested_usd'] * (cur_real_rate - cur_rate)
            
            # 3. 총손익 (KRW) = 평가손익 + 환손익 + (배당+실현)*환율
            realized_usd = data['realized_pl'] + data['accum_div']
            total_pl_krw_tk = eval_pl_krw + fx_pl_krw + (realized_usd * cur_real_rate)
            
            # 수익률 (KRW 기준) = 총손익 / (투자원금$ * 내평단환율)
            invested_krw_basis = data['invested_usd'] * cur_rate
            ret_pct = (total_pl_krw_tk / invested_krw_basis * 100) if invested_krw_basis > 0 else 0
            
            table_rows.append({
                "종목": tk,
                "평가액(KRW)": f"₩ {(qty*cur_p*cur_real_rate):,.0f}",
                "평가손익": f"₩ {eval_pl_krw:,.0f}",
                "환손익": f"₩ {fx_pl_krw:,.0f}",
                "실현+배당": f"${realized_usd:,.2f}",
                "총 손익(KRW)": f"₩ {total_pl_krw_tk:,.0f}",
                "총 수익률": f"{ret_pct:+.2f}%"
            })
            
        st.table(pd.DataFrame(table_rows))

    # [Tab 3] 통합 로그
    with tab3:
        # 시간순 정렬 (Order_ID 기준)
        merged_log = pd.concat([u_money, u_trade], ignore_index=True)
        merged_log['Order_ID'] = pd.to_numeric(merged_log['Order_ID']).fillna(0)
        merged_log = merged_log.sort_values(['Order_ID', 'Date'], ascending=[False, False])
        
        # Display
        cols = ['Date', 'Order_ID', 'Type', 'Ticker', 'Qty', 'USD_Amount', 'KRW_Amount', 'Avg_Rate', 'Balance']
        st.dataframe(merged_log[cols].fillna(''), use_container_width=True)

if __name__ == "__main__":
    main()
