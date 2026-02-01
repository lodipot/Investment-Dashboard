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
    /* Global Font */
    html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; }

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
    .kpi-main { font-size: 2rem; font-weight: 800; color: #FFFFFF; }
    .kpi-sub { font-size: 1.1rem; margin-top: 5px; font-weight: 600; }
    
    /* Colors */
    .txt-red { color: #FF5252 !important; }
    .txt-blue { color: #448AFF !important; }
    .bg-red { background-color: rgba(255, 82, 82, 0.15) !important; }
    .bg-blue { background-color: rgba(68, 138, 255, 0.15) !important; }
    .txt-orange { color: #FF9800 !important; }
    
    /* Stock Card */
    .stock-card {
        background-color: #262626;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 16px;
        border-left: 6px solid #555;
        transition: transform 0.2s;
    }
    .stock-card:hover { transform: translateY(-3px); }
    .card-up { border-left-color: #FF5252 !important; }
    .card-down { border-left-color: #448AFF !important; }
    
    .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
    .card-ticker { font-size: 1.4rem; font-weight: 900; color: #FFF; }
    .card-price { font-size: 1.0rem; font-weight: 500; color: #BBB; }
    
    .card-main-val { font-size: 1.6rem; font-weight: 800; color: #FFF; text-align: right; letter-spacing: -0.5px; }
    .card-sub-box { text-align: right; margin-top: -2px; }
    .pl-amt { font-size: 1.1rem; font-weight: 700; margin-right: 6px; }
    .pl-pct { font-size: 0.95rem; font-weight: 500; opacity: 0.9; }
    
    /* Detail Table inside Card */
    .detail-table { width: 100%; font-size: 0.85rem; color: #DDD; margin-top: 12px; border-top: 1px solid #444; }
    .detail-table td { padding: 5px 0; border-bottom: 1px solid #333; }
    .detail-table tr:last-child td { border-bottom: none; }
    .text-right { text-align: right; }
    
    /* Integrated Table (HTML) */
    .int-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; text-align: right; color: #EEE; }
    .int-table th { background-color: #333; color: #FFF; padding: 12px 8px; text-align: right; border-bottom: 2px solid #555; }
    .int-table th:first-child { text-align: left; }
    .int-table td { padding: 10px 8px; border-bottom: 1px solid #444; }
    .int-table td:first-child { text-align: left; font-weight: bold; color: #FFF; }
    .row-total { background-color: #333; font-weight: bold; border-top: 2px solid #666; }
    .row-cash { background-color: #252525; font-style: italic; color: #AAA; }
</style>
""", unsafe_allow_html=True)

# 섹터 정의
SECTOR_MAP = {
    'NVDA': '테크', 'AMD': '테크', 'TSM': '테크', 'AVGO': '테크', 'SOXL': '테크', 'GOOGL': '테크', 'MSFT': '테크', 'AAPL': '테크', 'AMZN': '테크', 'TSLA': '테크',
    'O': '배당', 'KO': '배당', 'SCHD': '배당', 'JEPQ': '배당', 'JEPI': '배당', 'MAIN': '배당',
    'PLD': '리츠', 'AMT': '리츠'
}

# 정렬 순서 (커스텀)
SORT_ORDER = ['O', 'JEPI', 'JEPQ', 'GOOGL', 'NVDA', 'AMD', 'TSM']

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
    df_money = pd.DataFrame(sh.worksheet("Money_Log").get_all_records())
    df_trade = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
    
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
# [3] 달러 저수지 엔진 (Logic)
# -------------------------------------------------------------------
def process_timeline(df_trade, df_money):
    df_money['Source'] = 'Money'
    df_trade['Source'] = 'Trade'
    
    if 'Order_ID' not in df_money.columns: df_money['Order_ID'] = 0
    if 'Order_ID' not in df_trade.columns: df_trade['Order_ID'] = 0
    
    timeline = pd.concat([df_money, df_trade], ignore_index=True)
    timeline['Order_ID'] = pd.to_numeric(timeline['Order_ID'], errors='coerce').fillna(999999)
    timeline = timeline.sort_values(by=['Order_ID', 'Date'])
    
    current_balance = 0.0
    current_avg_rate = 0.0
    
    portfolio = {} 
    
    for idx, row in timeline.iterrows():
        source = row['Source']
        t_type = str(row.get('Type', '')).lower()
        
        if source == 'Money':
            usd_amt = safe_float(row.get('USD_Amount'))
            krw_amt = safe_float(row.get('KRW_Amount'))
            ticker = str(row.get('Ticker', '')).strip()
            if ticker == '' or ticker == '-': ticker = 'Cash'
            
            # 배당금 집계
            if 'dividend' in t_type or '배당' in t_type:
                if ticker != 'Cash':
                    if ticker not in portfolio: portfolio[ticker] = {'qty':0, 'invested_krw':0, 'realized_krw':0, 'accum_div_usd':0}
                    portfolio[ticker]['accum_div_usd'] += usd_amt
            
            # 저수지 계산
            current_balance += usd_amt
            if current_balance > 0.0001:
                prev_val = (current_balance - usd_amt) * current_avg_rate
                added_val = 0 if ('dividend' in t_type or '배당' in t_type) else krw_amt
                current_avg_rate = (prev_val + added_val) / current_balance
                
            # 빈칸 채우기 (메모리)
            df_money.loc[df_money['Order_ID'] == row['Order_ID'], 'Avg_Rate'] = current_avg_rate
            df_money.loc[df_money['Order_ID'] == row['Order_ID'], 'Balance'] = current_balance

        elif source == 'Trade':
            qty = safe_float(row.get('Qty'))
            price = safe_float(row.get('Price_USD'))
            amount = qty * price
            ticker = str(row.get('Ticker', '')).strip()
            
            if ticker not in portfolio: portfolio[ticker] = {'qty':0, 'invested_krw':0, 'realized_krw':0, 'accum_div_usd':0}
            
            if 'buy' in t_type or '매수' in t_type:
                current_balance -= amount
                # 매수 시점의 환율 확정 (Ex_Avg_Rate)
                ex_rate = safe_float(row.get('Ex_Avg_Rate'))
                if ex_rate == 0: 
                    ex_rate = current_avg_rate
                    df_trade.loc[df_trade['Order_ID'] == row['Order_ID'], 'Ex_Avg_Rate'] = ex_rate
                
                portfolio[ticker]['qty'] += qty
                portfolio[ticker]['invested_krw'] += (amount * ex_rate)
                
            elif 'sell' in t_type or '매도' in t_type:
                current_balance += amount
                # 실현손익 계산 (KRW 기준) - 매도 시점의 저수지 평단으로 환산
                sell_val_krw = amount * current_avg_rate 
                
                if portfolio[ticker]['qty'] > 0:
                    avg_unit_invest = portfolio[ticker]['invested_krw'] / portfolio[ticker]['qty']
                    cost_krw = qty * avg_unit_invest
                    
                    pl_krw = sell_val_krw - cost_krw
                    portfolio[ticker]['realized_krw'] += pl_krw
                    
                    portfolio[ticker]['qty'] -= qty
                    portfolio[ticker]['invested_krw'] -= cost_krw

    return df_trade, df_money, current_balance, current_avg_rate, portfolio

# -------------------------------------------------------------------
# [4] Sync Logic
# -------------------------------------------------------------------
def sync_api_data(sheet_instance, df_trade, df_money):
    ws_trade = sheet_instance.worksheet("Trade_Log")
    ws_money = sheet_instance.worksheet("Money_Log")
    
    max_id = max(pd.to_numeric(df_trade['Order_ID'], errors='coerce').max(), pd.to_numeric(df_money['Order_ID'], errors='coerce').max())
    next_order_id = int(max_id) + 1 if not pd.isna(max_id) else 1
    
    last_date_str = "20260101"
    if not df_trade.empty:
        last_date = pd.to_datetime(df_trade['Date']).max()
        last_date_str = last_date.strftime("%Y%m%d")
    end_date_str = datetime.now().strftime("%Y%m%d")
    
    with st.spinner(f"API 데이터 수신 중..."):
        res = kis.get_trade_history(last_date_str, end_date_str)
        
    if res and res.get('output1'):
        new_rows = []
        keys = set(f"{r['Date']}_{r['Ticker']}_{safe_float(r['Qty'])}" for _, r in df_trade.iterrows())
        for item in reversed(res['output1']):
            dt = datetime.strptime(item['dt'], "%Y%m%d").strftime("%Y-%m-%d")
            tk = item['pdno']
            qty = int(item['ccld_qty'])
            price = float(item['ft_ccld_unpr3'])
            side = "Buy" if item['sll_buy_dvsn_cd'] == '02' else "Sell"
            if f"{dt}_{tk}_{float(qty)}" in keys: continue
            new_rows.append([dt, next_order_id, tk, item['prdt_name'], side, qty, price, "", "API_Auto"])
            next_order_id += 1
            
        if new_rows:
            ws_trade.append_rows(new_rows)
            df_trade = pd.DataFrame(ws_trade.get_all_records())
            st.success(f"{len(new_rows)}건 업데이트")
            
    # Recalc & Update
    u_trade, u_money, _, _, _ = process_timeline(df_trade, df_money)
    ws_trade.update([u_trade.columns.values.tolist()] + u_trade.astype(str).values.tolist())
    ws_money.update([u_money.columns.values.tolist()] + u_money.astype(str).values.tolist())
    
    st.toast("동기화 완료")
    time.sleep(1)
    st.rerun()

# -------------------------------------------------------------------
# [5] 메인 앱
# -------------------------------------------------------------------
def main():
    try:
        df_trade, df_money, sheet_instance = load_data()
    except:
        st.error("DB 연결 실패.")
        st.stop()
        
    # 엔진 가동
    u_trade, u_money, cur_bal, cur_rate, portfolio = process_timeline(df_trade, df_money)
    cur_real_rate = get_realtime_rate()
    
    # 현재가 조회
    tickers = list(portfolio.keys())
    prices = {}
    if tickers:
        with st.spinner("시장가 조회 중..."):
            for t in tickers:
                prices[t] = kis.get_current_price(t)
    
    # 전체 자산 계산
    total_stock_val_krw = 0.0
    total_input_principal = df_money[df_money['Type'] == 'KRW_to_USD']['KRW_Amount'].apply(safe_float).sum()
    
    for tk, data in portfolio.items():
        if data['qty'] > 0:
            val_usd = data['qty'] * prices.get(tk, 0)
            total_stock_val_krw += (val_usd * cur_real_rate)

    total_asset_krw = total_stock_val_krw + (cur_bal * cur_real_rate)
    total_pl_krw = total_asset_krw - total_input_principal
    total_pl_pct = (total_pl_krw / total_input_principal * 100) if total_input_principal > 0 else 0
    
    total_realized_krw = sum(d['realized_krw'] for d in portfolio.values())
    total_div_usd = sum(d['accum_div_usd'] for d in portfolio.values())
    
    bep_numerator = total_input_principal - total_realized_krw - (total_div_usd * cur_real_rate) 
    total_usd_assets = (total_stock_val_krw / cur_real_rate) + cur_bal
    bep_rate = bep_numerator / total_usd_assets if total_usd_assets > 0 else 0
    safety_margin = cur_real_rate - bep_rate

    # UI Rendering
    c1, c2 = st.columns([3, 1])
    now = datetime.now()
    status = "🟢 Live" if (23 <= now.hour or now.hour < 6) else "🔴 Closed"
    with c1:
        st.title("🚀 Investment Command Center")
        st.caption(f"{status} | Last Update: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    with c2:
        if st.button("🔄 API Sync"):
            sync_api_data(sheet_instance, u_trade, u_money)

    # KPI Cube (Updated)
    kpi_html = f"""
    <div class="kpi-container">
        <div class="kpi-card">
            <div class="kpi-title">총 자산 (Total Assets)</div>
            <div class="kpi-main">₩ {total_asset_krw:,.0f}</div>
            <div class="kpi-sub {'txt-red' if total_pl_krw >= 0 else 'txt-blue'}">
                {'▲' if total_pl_krw >= 0 else '▼'} {abs(total_pl_krw):,.0f} &nbsp; {total_pl_pct:+.2f}%
            </div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">달러 잔고 (USD Balance)</div>
            <div class="kpi-main">$ {cur_bal:,.2f}</div>
            <div class="kpi-sub">매수환율: ₩ {cur_rate:,.2f}</div>
            <div style="color: #FF9800; font-size: 0.9rem; margin-top: 4px;">현재환율: ₩ {cur_real_rate:,.2f}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">안전마진 (Safety Margin)</div>
            <div class="kpi-main {'txt-red' if safety_margin >= 0 else 'txt-blue'}">{safety_margin:+.2f} 원</div>
            <div class="kpi-sub">BEP: ₩ {bep_rate:,.2f}</div>
        </div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 대시보드", "📋 통합 상세", "📜 통합 로그", "🕹️ 입력 매니저"])
    
    # [Tab 1] 대시보드 (카드)
    with tab1:
        st.write("### 💳 Portfolio Status")
        for sec in ['배당', '테크', '리츠', '기타']:
            target_tickers = []
            if sec in SECTOR_MAP.values():
                target_tickers = [k for k, v in SECTOR_MAP.items() if v == sec and k in portfolio and portfolio[k]['qty'] > 0]
            elif sec == '기타':
                target_tickers = [k for k in portfolio.keys() if k not in SECTOR_MAP and portfolio[k]['qty'] > 0]
            if not target_tickers: continue
            
            st.caption(f"**{sec}** Sector")
            cols = st.columns(4)
            for idx, tk in enumerate(target_tickers):
                data = portfolio[tk]
                qty = data['qty']
                cur_p = prices.get(tk, 0)
                val_krw = qty * cur_p * cur_real_rate
                
                div_krw = data['accum_div_usd'] * cur_real_rate
                total_pl_tk = val_krw - data['invested_krw'] + data['realized_krw'] + div_krw
                total_ret = (total_pl_tk / data['invested_krw'] * 100) if data['invested_krw'] > 0 else 0
                
                bep_rate_tk = (data['invested_krw'] - data['realized_krw'] - div_krw) / (qty * cur_p) if (qty*cur_p) > 0 else 0
                margin_tk = cur_real_rate - bep_rate_tk
                
                is_plus = total_pl_tk >= 0
                color_cls = "card-up" if is_plus else "card-down"
                txt_cls = "txt-red" if is_plus else "txt-blue"
                arrow = "▲" if is_plus else "▼"
                sign = "+" if is_plus else ""
                
                html = f"""
                <div class="stock-card {color_cls}">
                    <div class="card-header">
                        <span class="card-ticker">{tk}</span>
                        <span class="card-price">${cur_p:.2f}</span>
                    </div>
                    <div class="card-main-val">₩ {val_krw:,.0f}</div>
                    <div class="card-sub-box {txt_cls}">
                        <span class="pl-amt">{arrow} {abs(total_pl_tk):,.0f}</span>
                        <span class="pl-pct">{sign}{total_ret:.1f}%</span>
                    </div>
                    <details>
                        <summary style="text-align:right; font-size:0.8rem; color:#888; cursor:pointer; margin-top:5px;">상세 내역</summary>
                        <table class="detail-table">
                            <tr><td>보유수량</td><td class="text-right">{qty:,.0f}</td></tr>
                            <tr><td>투자원금</td><td class="text-right">₩ {data['invested_krw']:,.0f}</td></tr>
                            <tr><td>누적실현</td><td class="text-right">₩ {data['realized_krw']:,.0f}</td></tr>
                            <tr><td>누적배당</td><td class="text-right">₩ {div_krw:,.0f}</td></tr>
                            <tr><td style="color:#AAA">안전마진</td><td class="text-right {txt_cls}">{margin_tk:+.1f} 원</td></tr>
                        </table>
                    </details>
                </div>
                """
                with cols[idx % 4]:
                    st.markdown(html, unsafe_allow_html=True)
                idx += 1

    # [Tab 2] Integrated Table (HTML)
    with tab2:
        table_html = """
        <table class="int-table">
            <thead>
                <tr>
                    <th>종목</th>
                    <th>평가액 (₩)</th>
                    <th>평가손익</th>
                    <th>환손익</th>
                    <th>실현+배당</th>
                    <th>총 손익 (Total)</th>
                    <th>안전마진</th>
                </tr>
            </thead>
            <tbody>
        """
        
        def sort_key(tk):
            if tk in SORT_ORDER: return SORT_ORDER.index(tk)
            return 999
        
        sorted_tickers = sorted(list(portfolio.keys()), key=sort_key)
        
        sum_eval_krw = 0
        sum_eval_pl = 0
        sum_realized = 0
        sum_total_pl = 0
        
        for tk in sorted_tickers:
            if tk == 'Cash': continue
            data = portfolio[tk]
            qty = data['qty']
            cur_p = prices.get(tk, 0)
            
            eval_krw = qty * cur_p * cur_real_rate
            invested_krw = data['invested_krw']
            div_krw = data['accum_div_usd'] * cur_real_rate
            
            total_pl = eval_krw - invested_krw + data['realized_krw'] + div_krw
            unrealized_pl = eval_krw - invested_krw 
            realized_total = data['realized_krw'] + div_krw
            
            bep_tk = (invested_krw - realized_total) / (qty * cur_p) if (qty*cur_p) > 0 else 0
            margin_tk = cur_real_rate - bep_tk if qty > 0 else 0
            
            cls_pl = "txt-red" if unrealized_pl >= 0 else "txt-blue"
            cls_tot = "txt-red" if total_pl >= 0 else "txt-blue"
            bg_cls = "bg-red" if total_pl >= 0 else "bg-blue"
            
            sum_eval_krw += eval_krw
            sum_eval_pl += unrealized_pl
            sum_realized += realized_total
            sum_total_pl += total_pl
            
            row_html = f"<tr><td>{tk}</td><td>{eval_krw:,.0f}</td><td class='{cls_pl}'>{unrealized_pl:,.0f}</td><td>-</td><td>{realized_total:,.0f}</td><td class='{cls_tot} {bg_cls}'><b>{total_pl:,.0f}</b></td><td>{margin_tk:+.1f}</td></tr>"
            table_html += row_html
            
        cash_krw = cur_bal * cur_real_rate
        final_pl_calc = (sum_eval_krw + cash_krw) - total_input_principal
        cls_fin = "txt-red" if final_pl_calc >= 0 else "txt-blue"
        
        table_html += f"<tr class='row-cash'><td>Cash (USD)</td><td>{cash_krw:,.0f}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
        table_html += f"<tr class='row-total'><td>TOTAL</td><td>{(sum_eval_krw + cash_krw):,.0f}</td><td>{sum_eval_pl:,.0f}</td><td>-</td><td>{sum_realized:,.0f}</td><td class='{cls_fin}'>{final_pl_calc:,.0f}</td><td>{safety_margin:+.1f}</td></tr>"
        table_html += "</tbody></table>"
        
        st.markdown(table_html, unsafe_allow_html=True)

    # [Tab 3] 통합 로그
    with tab3:
        merged_log = pd.concat([u_money, u_trade], ignore_index=True)
        merged_log['Order_ID'] = pd.to_numeric(merged_log['Order_ID']).fillna(0)
        merged_log = merged_log.sort_values(['Order_ID', 'Date'], ascending=[False, False])
        st.dataframe(merged_log.fillna(''), use_container_width=True)

    # [Tab 4] 입력 매니저
    with tab4:
        st.subheader("📝 환전 & 배당 입력")
        with st.form("input_form"):
            c1, c2 = st.columns(2)
            i_type = c1.radio("구분", ["KRW_to_USD", "Dividend"], horizontal=True)
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
                    rate, "", "", i_note
                ])
                st.success("저장되었습니다! (Sync 버튼을 눌러 반영하세요)")

if __name__ == "__main__":
    main()
