import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import textwrap
import re

# [NEW] KIS API 매니저 불러오기
import KIS_API_Manager as kis

# -------------------------------------------------------------------
# 1. 초기 설정 & 스타일
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

if 'input_log' not in st.session_state: st.session_state['input_log'] = []

st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none; }
    div[data-testid="stTabs"] > div:first-child {
        position: sticky; top: 0; z-index: 1000;
        background-color: var(--background-color);
        padding-top: 1rem; border-bottom: 1px solid rgba(128,128,128,0.2);
    }
    .kpi-container {
        display: grid; grid-template-columns: repeat(4, 1fr);
        gap: 8px; margin-bottom: 20px;
    }
    .kpi-cube {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.2);
        border-radius: 12px; padding: 10px;
        text-align: center; display: flex; flex-direction: column; justify-content: center;
        aspect-ratio: 1 / 0.8; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .kpi-title { font-size: 0.8rem; opacity: 0.7; font-weight: 600; white-space: nowrap; }
    .kpi-value { font-size: clamp(12px, 2vw, 24px); font-weight: 800; margin: 4px 0; }
    .kpi-sub { font-size: 0.7rem; opacity: 0.8; }
    
    .stock-card {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.2);
        border-radius: 12px; padding: 16px; margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .card-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
    .ticker-name { font-size: 1.1rem; font-weight: 700; color: var(--text-color); }
    .full-name { font-size: 0.8rem; opacity: 0.6; margin-left: 6px; }
    .main-val { font-size: 1.4rem; font-weight: 800; margin-bottom: 6px; }
    .profit-line { display: flex; align-items: baseline; gap: 8px; font-weight: 700; }
    .profit-amt { font-size: 1.0rem; }
    .profit-rate { font-size: 0.9rem; opacity: 0.9; }
    
    .badge-margin { display: inline-block; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; color: #333; margin-top: 8px; }
    
    div[data-testid="stPopover"] > button {
        width: 100%;
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.2);
        color: transparent !important;
        -webkit-text-fill-color: transparent !important;
        text-shadow: 0 0 0 var(--text-color);
        height: 38px; overflow: hidden;
    }
    div[data-testid="stPopover"] > button p { font-family: sans-serif !important; }

    .c-red { color: #FF5252 !important; }
    .c-blue { color: #448AFF !important; }
    .c-gray { color: #9E9E9E !important; }
    .bg-red-light { background-color: rgba(255, 82, 82, 0.2) !important; color: #FF5252 !important; }
    .bg-green-light { background-color: rgba(105, 240, 174, 0.2) !important; color: #69F0AE !important; }
    .bg-gray-light { background-color: rgba(158, 158, 158, 0.2) !important; color: #9E9E9E !important; }
    .table-row { border-bottom: 1px solid rgba(128,128,128,0.1); }
</style>
""", unsafe_allow_html=True)

BENCHMARK_RATE = 0.035
SECTORS = {
    'REITS': {'emoji': '🏢', 'name': '리츠', 'tickers': ['O', 'PLD']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'KO']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크', 'tickers': ['MSFT', 'GOOGL']},
    'VOL_TECH': {'emoji': '🚀', 'name': '성장주', 'tickers': ['NVDA', 'TSLA', 'AMD']},
    'CASH': {'emoji': '💵', 'name': '현금', 'tickers': ['💵 USD CASH']}
}
SORT_ORDER = ['O', 'PLD', 'JEPI', 'JEPQ', 'KO', 'SCHD', 'GOOGL', 'MSFT', 'AMD', 'NVDA', 'TSLA', '💵 USD CASH']

# -------------------------------------------------------------------
# 2. 데이터 로드 및 전처리
# -------------------------------------------------------------------
def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open("Investment_Dashboard_DB")

def clean_currency(series):
    return pd.to_numeric(series.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

@st.cache_data(ttl=60)
def load_data():
    try:
        sh = get_client()
        trade_df = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        exchange_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        krw_assets_df = pd.DataFrame(sh.worksheet("KRW_Assets").get_all_records())
        etf_df = pd.DataFrame(sh.worksheet("Domestic_ETF").get_all_records())
        try: div_df = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        except: div_df = pd.DataFrame(columns=['Date', 'Ticker', 'Amount_USD', 'Note'])
        return trade_df, exchange_df, krw_assets_df, etf_df, div_df
    except: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# [수정된 함수] KIS API를 우선 사용하되, 실패 시 yfinance로 방어하는 로직
def get_market_data(tickers):
    # 1. 환율 가져오기 (안전성을 위해 yfinance 유지)
    fx = 1450.0
    fx_status = "Fallback"
    try:
        fx_hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not fx_hist.empty:
            fx = fx_hist['Close'].iloc[-1]
            fx_status = "Live (Yahoo)"
    except: pass
    
    # 2. 주식 현재가 가져오기 (KIS -> yfinance 하이브리드)
    data_map = {}
    
    if tickers:
        valid_tickers = [t for t in tickers if t != '💵 USD CASH']
        
        # 진행 상황을 보여주기 위한 빈 텍스트 상자 (선택사항)
        # prog_text = st.empty() 
        
        for t in valid_tickers:
            price = 0.0
            source = ""
            
            # [1차 시도] KIS API (실시간)
            try:
                price = kis.get_current_price(t)
                if price > 0:
                    source = "KIS"
            except:
                price = 0.0
            
            # [2차 시도] 실패했다면 yfinance (15분 지연)
            if price == 0:
                try:
                    hist = yf.Ticker(t).history(period="1d")
                    if not hist.empty:
                        price = hist['Close'].iloc[-1]
                        source = "Yahoo"
                except:
                    price = 0.0 # 정말 다 실패하면 0
            
            # 결과 저장
            if price > 0:
                data_map[t] = price
                # (디버깅용) 어떤 소스에서 가져왔는지 로그에 찍고 싶다면 아래 주석 해제
                # print(f"{t}: {price} via {source}")

    return fx, fx_status, data_map

def calculate_portfolio_state(trade_df, exchange_df, div_df):
    if not exchange_df.empty:
        exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
        exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
    if not trade_df.empty:
        trade_df['Qty'] = clean_currency(trade_df['Qty'])
        trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
    if not div_df.empty:
        div_df['Amount_USD'] = clean_currency(div_df['Amount_USD'])
        div_df['Ex_Rate'] = clean_currency(div_df['Ex_Rate'])

    timeline = []
    for _, r in exchange_df.iterrows():
        timeline.append({'date': r['Date'], 'type': 'exchange', 'usd': r['USD_Amount'], 'krw': r['KRW_Amount'], 'obj': r})
    for _, r in div_df.iterrows():
        timeline.append({'date': r['Date'], 'type': 'dividend', 'usd': r['Amount_USD'], 'krw': r['Amount_USD'] * r['Ex_Rate'], 'obj': r})
    for _, r in trade_df.iterrows():
        timeline.append({'date': r['Date'], 'type': 'trade', 'action': r['Type'], 'ticker': r['Ticker'], 
                         'qty': r['Qty'], 'price': r['Price_USD'], 'name': r.get('Name', r['Ticker'])})
    
    prio = {'dividend':1, 'exchange':2, 'trade':3}
    timeline.sort(key=lambda x: (x['date'], prio.get(x['type'], 9)))

    cash_usd = 0.0
    cash_krw_basis = 0.0
    portfolio = {}
    total_realized_pl_usd = 0.0
    total_dividend_usd = 0.0

    for item in timeline:
        if item['type'] == 'exchange':
            cash_usd += item['usd']
            cash_krw_basis += item['krw']
        elif item['type'] == 'dividend':
            cash_usd += item['usd']
            cash_krw_basis += item['krw']
            total_dividend_usd += item['usd']
        elif item['type'] == 'trade':
            ticker = item['ticker']
            qty = item['qty']
            price = item['price']
            action = item.get('action', 'Buy')
            
            if ticker not in portfolio:
                portfolio[ticker] = {'qty': 0, 'total_cost_usd': 0.0, 'total_cost_krw': 0.0, 'realized_pl_usd': 0.0, 'name': item['name']}
            
            curr_cash_rate = (cash_krw_basis / cash_usd) if cash_usd > 0 else 1450.0

            if action == 'Buy':
                cost_usd = qty * price
                cost_krw = cost_usd * curr_cash_rate
                cash_usd -= cost_usd
                cash_krw_basis -= cost_krw
                portfolio[ticker]['qty'] += qty
                portfolio[ticker]['total_cost_usd'] += cost_usd
                portfolio[ticker]['total_cost_krw'] += cost_krw
            elif action == 'Sell':
                revenue_usd = qty * price
                curr_qty = portfolio[ticker]['qty']
                if curr_qty > 0:
                    avg_cost_usd = portfolio[ticker]['total_cost_usd'] / curr_qty
                    avg_cost_krw = portfolio[ticker]['total_cost_krw'] / curr_qty
                else:
                    avg_cost_usd = 0; avg_cost_krw = 0
                
                removed_cost_usd = qty * avg_cost_usd
                removed_cost_krw = qty * avg_cost_krw
                deal_pl_usd = revenue_usd - removed_cost_usd
                
                portfolio[ticker]['qty'] -= qty
                portfolio[ticker]['total_cost_usd'] -= removed_cost_usd
                portfolio[ticker]['total_cost_krw'] -= removed_cost_krw
                portfolio[ticker]['realized_pl_usd'] += deal_pl_usd
                total_realized_pl_usd += deal_pl_usd
                
                cash_usd += revenue_usd
                cash_krw_basis += removed_cost_krw 

    cash_avg_rate = (cash_krw_basis / cash_usd) if cash_usd > 0 else 1450.0
    return cash_usd, cash_avg_rate, portfolio, total_realized_pl_usd, total_dividend_usd

# -------------------------------------------------------------------
# 3. 메인 앱 실행
# -------------------------------------------------------------------
main_tab1, main_tab2 = st.tabs(["📊 대시보드", "📝 입력 매니저"])

# [PAGE 1] 대시보드
with main_tab1:
    trade_df, exchange_df, krw_assets_df, etf_df, div_df = load_data()
    cash_usd, cash_rate, pf_data, total_realized_usd, total_div_usd = calculate_portfolio_state(trade_df, exchange_df, div_df)
    tickers = list(pf_data.keys())
    current_rate, fx_status, price_map = get_market_data(tickers)
    
    rows = []
    cash_principal_krw = cash_usd * cash_rate
    cash_eval_krw = cash_usd * current_rate
    cash_fx_profit = cash_usd * (current_rate - cash_rate)
    
    rows.append({
        'Ticker': '💵 USD CASH', 'Name': '달러예수금',
        'Principal': cash_principal_krw, 'Eval': cash_eval_krw,
        'Price_Profit': 0, 'FX_Profit': cash_fx_profit,
        'Div_Profit': 0, 'Realized_Profit': 0,
        'Total_Profit': cash_fx_profit,
        'Safety_Margin': 9999
    })
    
    for t, data in pf_data.items():
        qty = data['qty']
        if qty == 0 and data['realized_pl_usd'] == 0: continue
        
        cur_p = price_map.get(t, 0)
        if cur_p == 0 and qty > 0: cur_p = data['total_cost_usd'] / qty
        
        principal_krw = data['total_cost_krw']
        eval_usd = qty * cur_p
        eval_krw = eval_usd * current_rate
        
        d_usd = div_df[div_df['Ticker'] == t]['Amount_USD'].sum() if not div_df.empty else 0
        d_krw = d_usd * current_rate
        realized_krw = data['realized_pl_usd'] * current_rate
        unrealized_total = eval_krw - principal_krw
        
        if qty > 0:
            avg_buy_rate = principal_krw / (data['total_cost_usd']) if data['total_cost_usd'] else 0
            fx_profit = data['total_cost_usd'] * (current_rate - avg_buy_rate)
            price_profit = unrealized_total - fx_profit
            be_rate = (principal_krw - d_krw - realized_krw) / eval_usd if eval_usd > 0 else 0
        else:
            fx_profit = 0; price_profit = 0; be_rate = 0
            
        grand_total = unrealized_total + realized_krw + d_krw
        
        rows.append({
            'Ticker': t, 'Name': data['name'],
            'Principal': principal_krw, 'Eval': eval_krw,
            'Price_Profit': price_profit, 'FX_Profit': fx_profit,
            'Div_Profit': d_krw, 'Realized_Profit': realized_krw,
            'Total_Profit': grand_total,
            'Unrealized_Total': unrealized_total,
            'Safety_Margin': current_rate - be_rate if qty > 0 else 0,
            'Qty': qty
        })
        
    df_combined = pd.DataFrame(rows)
    df_combined['SortKey'] = df_combined['Ticker'].apply(lambda x: SORT_ORDER.index(x) if x in SORT_ORDER else 999)
    df_combined = df_combined.sort_values(['SortKey', 'Ticker']).drop(columns=['SortKey'])
    
    sub_kpi, sub_card, sub_html, sub_detail = st.tabs(["📊 KPI", "🗂️ 카드", "📑 통합", "📋 세부"])
    
    with sub_kpi:
        curr_principal = df_combined['Principal'].sum()
        curr_eval = df_combined['Eval'].sum()
        acc_realized_usd = total_realized_usd + total_div_usd
        acc_realized_krw = acc_realized_usd * current_rate
        curr_unrealized = curr_eval - curr_principal
        roi = (curr_unrealized / curr_principal * 100) if curr_principal else 0
        fx_sum = df_combined['FX_Profit'].sum()
        fx_roi = (fx_sum / curr_principal * 100) if curr_principal else 0
        
        st.markdown(f"""
        <div class="kpi-container">
            <div class="kpi-cube">
                <div class="kpi-title">보유 평가수익률</div>
                <div class="kpi-value {'c-red' if roi>0 else 'c-blue'}">{roi:+.2f}%</div>
                <div class="kpi-sub">vs 예금 {roi-(BENCHMARK_RATE*100):+.2f}%p</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">순수 환차익</div>
                <div class="kpi-value {'c-red' if fx_roi>0 else 'c-blue'}">{fx_roi:+.2f}%</div>
                <div class="kpi-sub">환율 변동 효과</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">💰 누적 실현수익</div>
                <div class="kpi-value {'c-red' if acc_realized_krw>0 else 'c-blue'}">{acc_realized_krw/10000:,.0f}만</div>
                <div class="kpi-sub">매도차익 + 배당금</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">현재 환율</div>
                <div class="kpi-value">{current_rate:,.0f}원</div>
                <div class="kpi-sub">{fx_status}</div>
            </div>
        </div>""", unsafe_allow_html=True)
        
    with sub_card:
        st.caption("📌 보유 종목 현황")
        active_df = df_combined[df_combined['Qty'] > 0] if 'Qty' in df_combined.columns else df_combined
        
        sec_cols = st.columns(len(SECTORS))
        def get_sector(t):
            for c, i in SECTORS.items():
                if t in i['tickers']: return c
            return 'ETC'
        active_df['Sector'] = active_df['Ticker'].apply(get_sector)
        
        for i, (code, info) in enumerate(SECTORS.items()):
            s_df = active_df[active_df['Sector'] == code]
            s_prof = s_df['Unrealized_Total'].sum() if not s_df.empty else 0
            s_princ = s_df['Principal'].sum() if not s_df.empty else 0
            s_roi = s_prof / s_princ * 100 if s_princ else 0
            
            with sec_cols[i]:
                c = "c-red" if s_prof > 0 else "c-blue" if s_prof < 0 else "c-gray"
                st.markdown(f"""
                <div style="text-align:center; padding:5px; background:var(--secondary-background-color); border-radius:8px; border:1px solid rgba(128,128,128,0.2);">
                    <div style="font-size:0.8rem; opacity:0.8;">{info['emoji']} {info['name'].split(' ')[0]}</div>
                    <div class="{c}" style="font-size:0.9rem; font-weight:bold;">{s_prof:+,.0f}</div>
                    <div class="{c}" style="font-size:0.75rem;">({s_roi:+.1f}%)</div>
                </div>""", unsafe_allow_html=True)
        
        st.markdown("---")
        cols = st.columns(4)
        for idx, row in enumerate(active_df.itertuples()):
            with cols[idx % 4]:
                profit = row.Unrealized_Total
                roi_val = profit / row.Principal * 100 if row.Principal else 0
                c = "c-red" if profit > 0 else "c-blue" if profit < 0 else "c-gray"
                sym = "▲" if profit > 0 else "▼" if profit < 0 else "-"
                
                if row.Ticker=='💵 USD CASH': margin_html = f'<span class="badge-margin bg-gray-light">∞</span>'
                elif row.Safety_Margin > 0: margin_html = f'<span class="badge-margin bg-green-light">안전 +{row.Safety_Margin:,.0f}</span>'
                else: margin_html = f'<span class="badge-margin bg-red-light">위험 {row.Safety_Margin:,.0f}</span>'
                
                st.markdown(f"""
                <div class="stock-card">
                    <div class="card-header"><span class="ticker-name">{row.Ticker}</span><span class="full-name">{row.Name}</span></div>
                    <div class="main-val">{row.Eval:,.0f}</div>
                    <div class="profit-line {c}">
                        <span class="profit-amt">{sym} {abs(profit):,.0f}</span>
                        <span class="profit-rate">{roi_val:+.1f}%</span>
                    </div>
                    <div style="text-align:right;">{margin_html}</div>
                </div>""", unsafe_allow_html=True)
                
                with st.popover("🔍", use_container_width=True):
                    st.markdown(f"**{row.Ticker} 상세 분석**")
                    st.divider()
                    st.write(f"💰 원금: {row.Principal:,.0f}")
                    st.write(f"💵 평가: {row.Eval:,.0f}")
                    st.write(f"📉 평가손익: {row.Unrealized_Total:,.0f} (미실현)")
                    st.divider()
                    st.write(f"🏦 배당수익: {row.Div_Profit:,.0f}")
                    st.write(f"💵 실현손익: {row.Realized_Profit:,.0f} (매도)")
                    st.divider()
                    st.write(f"🏆 총 누적손익: {row.Total_Profit:,.0f}")

    with sub_html:
        def make_html(df):
            rows = ""
            for _, row in df.iterrows():
                op = "1.0" if row['Qty'] > 0 else "0.5"
                c = "c-red" if row['Total_Profit'] > 0 else "c-blue" if row['Total_Profit'] < 0 else "c-gray"
                rows += f"<tr class='table-row' style='opacity:{op}'><td style='text-align:left'><b>{row['Ticker']}</b></td>"
                rows += f"<td>{row['Eval']:,.0f}</td>"
                rows += f"<td><span class='{c}'>{row['Unrealized_Total']:,.0f}</span></td>"
                rows += f"<td>{row['FX_Profit']:,.0f}</td>"
                rows += f"<td><b>{row['Realized_Profit']:,.0f}</b></td>"
                rows += f"<td><span class='{c}'><b>{row['Total_Profit']:,.0f}</b></span></td>"
                rows += f"<td>{row['Safety_Margin']:+.1f}</td></tr>"
            
            s_t = df['Total_Profit'].sum()
            s_r = df['Realized_Profit'].sum()
            rows += f"<tr style='background:rgba(128,128,128,0.1); border-top:2px solid rgba(128,128,128,0.3); font-weight:bold;'><td style='text-align:left'>🔴 TOTAL</td><td>-</td><td>-</td><td>-</td><td>{s_r:,.0f}</td><td>{s_t:,.0f}</td><td>-</td></tr>"
            return f"""<style>.c-red{{color:#FF5252}}.c-blue{{color:#448AFF}}.c-gray{{color:#9E9E9E}}table{{width:100%;border-collapse:collapse;font-size:0.85em;color:var(--text-color)}}th{{background:var(--secondary-background-color);padding:8px;text-align:right;border-bottom:2px solid rgba(128,128,128,0.3);position:sticky;top:0;white-space:nowrap}}td{{padding:8px;border-bottom:1px solid rgba(128,128,128,0.1);text-align:right}}</style><table><thead><tr><th style='text-align:left'>종목</th><th>평가액</th><th>평가손익</th><th>환손익</th><th>실현손익</th><th>총손익</th><th>안전마진</th></tr></thead><tbody>{rows}</tbody></table>"""
        st.markdown(make_html(df_combined), unsafe_allow_html=True)
        
    with sub_detail:
        st.dataframe(df_combined, use_container_width=True)

# [PAGE 2] 입력 매니저
with main_tab2:
    # [NEW] API 연결 테스트 섹션 (여기만 추가됨)
    st.subheader("🛠️ API 연결 테스트")
    if st.button("KIS API로 '리얼티인컴(O)' 가격 가져오기"):
        try:
            price = kis.get_current_price("O")
            if price > 0:
                st.success(f"✅ 성공! 리얼티인컴(O) 현재가: ${price}")
            else:
                st.error("❌ 실패: 장 운영시간이 아니거나, secrets.toml 설정을 확인해주세요.")
        except Exception as e:
            st.error(f"⚠️ 오류 발생: {e}")
    st.divider()

    # (기존 입력 매니저 로직 그대로 유지)
    st.subheader("데이터 입력")
    if st.session_state['input_log']:
        st.info("📋 세션 입력 내역")
        for l in st.session_state['input_log']: st.caption(f"✅ {l}")
        st.divider()

    c1, c2 = st.columns([1, 2])
    with c1:
        date_val = st.date_input("기준 날짜", datetime.now())
        mode = st.radio("입력 모드", ["자동(카톡 뭉치)", "수동 매수", "수동 매도", "수동 배당", "수동 환전"])
        
        m_ticker, m_qty, m_price = None, 0, 0.0
        d_ticker, d_amount, d_rate = None, 0.0, 0.0
        e_krw, e_usd = 0, 0.0

        if "매수" in mode or "매도" in mode:
            m_ticker = st.text_input("종목코드 (예: O)")
            m_qty = st.number_input("수량", min_value=1, step=1)
            m_price = st.number_input("단가 ($)", min_value=0.01, step=0.01, format="%.2f")
        elif "배당" in mode:
            d_ticker = st.text_input("배당 종목 (예: O)")
            d_amount = st.number_input("배당금 ($)", min_value=0.01, step=0.01, format="%.2f")
            try: cur_rate = yf.Ticker("USDKRW=X").history(period="1d")['Close'].iloc[-1]
            except: cur_rate = 1450.0
            d_rate = st.number_input("적용 환율 (KRW/USD)", value=float(round(cur_rate, 2)), step=0.1, format="%.2f")
        elif "환전" in mode:
            e_krw = st.number_input("보낸 원화 (KRW)", min_value=1000, step=1000)
            e_usd = st.number_input("받은 달러 (USD)", min_value=1.0, step=1.0)
            if e_usd > 0: st.caption(f"💡 적용 환율: {e_krw/e_usd:,.2f} 원/$")
            
    with c2:
        if "자동" in mode:
            raw_text = st.text_area("카톡 내용 붙여넣기 (광고, 잡담 섞여도 OK)", height=400)
        else:
            st.info("👈 왼쪽에서 정보를 입력해주세요.")
            if "배당" in mode: st.write("※ 배당금은 '세후' 실제 입금액 기준으로 넣는 것을 추천합니다.")
        
    if st.button("저장 실행", type="primary"):
        try:
            sh = get_client()
            ts_base = datetime.now().strftime('%Y%m%d%H%M%S')
            log_list = []
            
            if ("매수" in mode or "매도" in mode) and m_ticker and m_qty > 0:
                type_str = "Sell" if "매도" in mode else "Buy"
                sh.worksheet("Trade_Log").append_row([str(date_val), ts_base, m_ticker.upper(), m_ticker.upper(), type_str, m_qty, m_price, 0, "수동"])
                log_list.append(f"{type_str}: {m_ticker} {m_qty}주 (@${m_price})")

            elif "배당" in mode and d_ticker and d_amount > 0:
                sh.worksheet("Dividend_Log").append_row([str(date_val), ts_base, d_ticker.upper(), d_amount, d_rate, "수동"])
                log_list.append(f"🏦 배당: {d_ticker} ${d_amount} (@{d_rate}원)")

            elif "환전" in mode and e_krw > 0 and e_usd > 0:
                rate = e_krw / e_usd
                sh.worksheet("Exchange_Log").append_row([str(date_val), ts_base, "KRW_to_USD", e_krw, e_usd, rate, "", "", "수동"])
                log_list.append(f"💱 환전: ${e_usd} (@{rate:.1f}원)")

            elif "자동" in mode and raw_text:
                ex_matches = re.findall(r'외화매수환전.*?￦([\d,]+).*?USD ([\d,.]+)', raw_text, re.DOTALL)
                for idx, (krw_str, usd_str) in enumerate(ex_matches):
                    k_val = int(krw_str.replace(',','')); u_val = float(usd_str.replace(',',''))
                    sh.worksheet("Exchange_Log").append_row([str(date_val), f"{ts_base}_EX_{idx}", "KRW_to_USD", k_val, u_val, k_val/u_val, "", "", "카톡일괄"])
                    log_list.append(f"💱 환전: ${u_val:,.2f}")

                div_matches = re.findall(r'([A-Z]+)/.*?\s+USD ([\d,.]+).*?세전배당입금', raw_text, re.DOTALL)
                for idx, (tk, amt_str) in enumerate(div_matches):
                    sh.worksheet("Dividend_Log").append_row([str(date_val), f"{ts_base}_DIV_{idx}", tk, float(amt_str.replace(',','')), 1450, "카톡일괄"])
                    log_list.append(f"🏦 배당: {tk} ${amt_str}")

                if "체결안내" in raw_text:
                    blocks = raw_text.split("한국투자증권 체결안내")
                    t_cnt = 0
                    for block in blocks:
                        if "종목명" not in block: continue
                        type_match = re.search(r'\*매매구분:(매수|매도)', block)
                        tk_match = re.search(r'\*종목명:([A-Z]+)', block)
                        qt_match = re.search(r'\*체결수량:([\d]+)', block)
                        pr_match = re.search(r'\*체결단가:USD ([\d.]+)', block)
                        
                        if type_match and tk_match and qt_match and pr_match:
                            t_type = "Buy" if type_match.group(1) == "매수" else "Sell"
                            sh.worksheet("Trade_Log").append_row([str(date_val), f"{ts_base}_TR_{t_cnt}", tk_match.group(1), tk_match.group(1), t_type, int(qt_match.group(1)), float(pr_match.group(1)), 0, "카톡일괄"])
                            log_list.append(f"🛒 {t_type}: {tk_match.group(1)}")
                            t_cnt += 1

            if log_list:
                st.session_state['input_log'].extend(log_list)
                st.success(f"✅ 저장 완료! ({len(log_list)}건)")
                st.balloons()
                st.cache_data.clear()
            else: st.error("입력 정보를 확인해주세요.")
            
        except Exception as e: st.error(f"오류: {str(e)}")
