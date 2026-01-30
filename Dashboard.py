import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import textwrap
import re

# -------------------------------------------------------------------
# 1. 초기 설정 & 스타일 (Samsung Browser & Dark Mode Fix)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

# 세션 초기화
if 'input_log' not in st.session_state: st.session_state['input_log'] = []

st.markdown("""
<style>
    /* [1] 사이드바 숨김 & 탭바 고정 */
    [data-testid="stSidebar"] { display: none; }
    div[data-testid="stTabs"] > div:first-child {
        position: sticky; top: 0; z-index: 1000;
        background-color: var(--background-color);
        padding-top: 1rem; border-bottom: 1px solid rgba(128,128,128,0.2);
    }

    /* [2] KPI 컨테이너 (4열 Grid - 누적수익 추가) */
    .kpi-container {
        display: grid;
        grid-template-columns: repeat(4, 1fr); /* 4등분 */
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

    /* [3] 주식 카드 (Rich Info - No Parenthesis Style) */
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
    
    /* [수정] 괄호 없는 손익 표시 스타일 */
    .profit-line { display: flex; align-items: baseline; gap: 8px; font-weight: 700; }
    .profit-amt { font-size: 1.0rem; }
    .profit-rate { font-size: 0.9rem; opacity: 0.9; }
    
    .badge-margin { display: inline-block; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; color: #333; margin-top: 8px; }

    /* [4] 모바일 버튼 텍스트 깨짐 방지 (Samsung Internet Fix) */
    div[data-testid="stPopover"] > button {
        width: 100%;
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.2);
        color: transparent !important;
        -webkit-text-fill-color: transparent !important; /* 삼성 브라우저 강제 투명화 */
        text-shadow: 0 0 0 var(--text-color);
        height: 38px; overflow: hidden;
    }
    div[data-testid="stPopover"] > button p { font-family: sans-serif !important; }

    /* 유틸리티 색상 */
    .c-red { color: #FF5252 !important; }
    .c-blue { color: #448AFF !important; }
    .c-gray { color: #9E9E9E !important; }
    .bg-red-light { background-color: rgba(255, 82, 82, 0.2) !important; color: #FF5252 !important; }
    .bg-green-light { background-color: rgba(105, 240, 174, 0.2) !important; color: #69F0AE !important; }
    .bg-gray-light { background-color: rgba(158, 158, 158, 0.2) !important; color: #9E9E9E !important; }
    
    /* 테이블 스타일 */
    .table-row { border-bottom: 1px solid rgba(128,128,128,0.1); }
</style>
""", unsafe_allow_html=True)

# 상수
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

def get_market_data(tickers):
    fx = 1450.0; fx_status = "Fallback"
    try:
        fx_hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not fx_hist.empty: fx = fx_hist['Close'].iloc[-1]; fx_status = "Live"
    except: pass
    
    data_map = {}
    if tickers:
        valid_tickers = [t for t in tickers if t != '💵 USD CASH']
        for t in valid_tickers:
            try:
                hist = yf.Ticker(t).history(period="1d")
                if not hist.empty: data_map[t] = hist['Close'].iloc[-1]
            except: pass
    return fx, fx_status, data_map

# -------------------------------------------------------------------
# 3. 핵심 로직: 포트폴리오 상태 계산 (매수/매도/배당 반영)
# -------------------------------------------------------------------
def calculate_portfolio_state(trade_df, exchange_df, div_df):
    # 1. 데이터 정제
    if not exchange_df.empty:
        exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
        exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
    if not trade_df.empty:
        trade_df['Qty'] = clean_currency(trade_df['Qty'])
        trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
    if not div_df.empty:
        div_df['Amount_USD'] = clean_currency(div_df['Amount_USD'])
        div_df['Ex_Rate'] = clean_currency(div_df['Ex_Rate'])

    # 2. 타임라인 생성
    timeline = []
    for _, r in exchange_df.iterrows():
        timeline.append({'date': r['Date'], 'type': 'exchange', 'usd': r['USD_Amount'], 'krw': r['KRW_Amount'], 'obj': r})
    for _, r in div_df.iterrows():
        # 배당은 해당 시점 환율로 KRW 가치 산정하여 현금풀에 기여
        timeline.append({'date': r['Date'], 'type': 'dividend', 'usd': r['Amount_USD'], 'krw': r['Amount_USD'] * r['Ex_Rate'], 'obj': r})
    for _, r in trade_df.iterrows():
        # Type: Buy / Sell
        timeline.append({'date': r['Date'], 'type': 'trade', 'action': r['Type'], 'ticker': r['Ticker'], 
                         'qty': r['Qty'], 'price': r['Price_USD'], 'name': r.get('Name', r['Ticker'])})
    
    # 시간순 정렬 (배당 > 환전 > 거래 순)
    prio = {'dividend':1, 'exchange':2, 'trade':3}
    timeline.sort(key=lambda x: (x['date'], prio.get(x['type'], 9)))

    # 3. 상태 변수
    cash_usd = 0.0
    cash_krw_basis = 0.0  # 현금의 원화 평단 계산용
    
    portfolio = {} # Ticker -> {qty, total_cost_usd, total_cost_krw, realized_pl_usd}
    total_realized_pl_usd = 0.0 # 매도 실현 손익 누적 (USD)
    total_dividend_usd = 0.0    # 배당 누적 (USD)

    for item in timeline:
        if item['type'] == 'exchange':
            cash_usd += item['usd']
            cash_krw_basis += item['krw']
            
        elif item['type'] == 'dividend':
            cash_usd += item['usd']
            cash_krw_basis += item['krw'] # 배당금도 현금 평단에 기여 (희석)
            total_dividend_usd += item['usd']
            
        elif item['type'] == 'trade':
            ticker = item['ticker']
            qty = item['qty']
            price = item['price']
            action = item.get('action', 'Buy')
            
            # 포트폴리오 초기화
            if ticker not in portfolio:
                portfolio[ticker] = {'qty': 0, 'total_cost_usd': 0.0, 'total_cost_krw': 0.0, 'realized_pl_usd': 0.0, 'name': item['name']}
            
            # 현재 현금 평단가
            curr_cash_rate = (cash_krw_basis / cash_usd) if cash_usd > 0 else 1450.0

            if action == 'Buy':
                cost_usd = qty * price
                cost_krw = cost_usd * curr_cash_rate
                
                # 현금 차감
                cash_usd -= cost_usd
                cash_krw_basis -= cost_krw
                
                # 주식 잔고 증가
                portfolio[ticker]['qty'] += qty
                portfolio[ticker]['total_cost_usd'] += cost_usd
                portfolio[ticker]['total_cost_krw'] += cost_krw
                
            elif action == 'Sell':
                # 매도 대금 (USD)
                revenue_usd = qty * price
                
                # 매도된 주식의 평단(Cost Basis) 제거
                curr_qty = portfolio[ticker]['qty']
                if curr_qty > 0:
                    avg_cost_usd = portfolio[ticker]['total_cost_usd'] / curr_qty
                    avg_cost_krw = portfolio[ticker]['total_cost_krw'] / curr_qty
                else:
                    avg_cost_usd = 0; avg_cost_krw = 0
                
                removed_cost_usd = qty * avg_cost_usd
                removed_cost_krw = qty * avg_cost_krw
                
                # 실현 손익 (USD 기준) -> "주머니에 챙긴 돈"
                # (판 돈 - 산 돈)
                deal_pl_usd = revenue_usd - removed_cost_usd
                
                # 포트폴리오 갱신
                portfolio[ticker]['qty'] -= qty
                portfolio[ticker]['total_cost_usd'] -= removed_cost_usd
                portfolio[ticker]['total_cost_krw'] -= removed_cost_krw
                portfolio[ticker]['realized_pl_usd'] += deal_pl_usd
                
                total_realized_pl_usd += deal_pl_usd
                
                # 현금 풀 갱신 (사용자 로직: 매도 원금의 원화 가치는 그대로 현금 풀로 복귀)
                # 이익분(deal_pl_usd)은 0의 KRW Cost로 들어오므로 평단을 낮춤 (이익 실현 효과)
                cash_usd += revenue_usd
                cash_krw_basis += removed_cost_krw 

    # 최종 현금 평단
    cash_avg_rate = (cash_krw_basis / cash_usd) if cash_usd > 0 else 1450.0
    
    return cash_usd, cash_avg_rate, portfolio, total_realized_pl_usd, total_dividend_usd

# -------------------------------------------------------------------
# 4. 메인 앱 실행
# -------------------------------------------------------------------
main_tab1, main_tab2 = st.tabs(["📊 대시보드", "📝 입력 매니저"])

# [PAGE 1] 대시보드
with main_tab1:
    trade_df, exchange_df, krw_assets_df, etf_df, div_df = load_data()
    
    # 포트폴리오 계산 엔진 가동
    cash_usd, cash_rate, pf_data, total_realized_usd, total_div_usd = calculate_portfolio_state(trade_df, exchange_df, div_df)
    
    # 시장가 가져오기
    tickers = list(pf_data.keys())
    current_rate, fx_status, price_map = get_market_data(tickers)
    
    # 표시용 데이터프레임 생성
    rows = []
    
    # 1. 현금 행
    cash_principal_krw = cash_usd * cash_rate
    cash_eval_krw = cash_usd * current_rate
    cash_fx_profit = cash_usd * (current_rate - cash_rate)
    
    rows.append({
        'Ticker': '💵 USD CASH', 'Name': '달러예수금',
        'Principal': cash_principal_krw, 'Eval': cash_eval_krw,
        'Price_Profit': 0, 'FX_Profit': cash_fx_profit,
        'Div_Profit': 0, 'Realized_Profit': 0,
        'Total_Profit': cash_fx_profit, # 현금은 환차익이 곧 총수익
        'Safety_Margin': 9999
    })
    
    # 2. 주식 행
    for t, data in pf_data.items():
        qty = data['qty']
        # 잔고가 없어도 실현손익이 있으면 리스트에는 포함 (단, 카드 뷰에서는 필터링 가능)
        if qty == 0 and data['realized_pl_usd'] == 0: continue
        
        cur_p = price_map.get(t, 0)
        # 현재가 없으면 평단으로 대체 (잔고 0이면 0)
        if cur_p == 0 and qty > 0: cur_p = data['total_cost_usd'] / qty
        
        principal_krw = data['total_cost_krw']
        eval_usd = qty * cur_p
        eval_krw = eval_usd * current_rate
        
        # 배당금 (종목별 누적)
        d_usd = div_df[div_df['Ticker'] == t]['Amount_USD'].sum() if not div_df.empty else 0
        d_krw = d_usd * current_rate # 현재 가치로 환산
        
        # 실현 손익 (KRW 환산: 현재 환율 기준 가치)
        realized_krw = data['realized_pl_usd'] * current_rate
        
        # 평가 손익 (미실현)
        unrealized_total = eval_krw - principal_krw
        
        # 주가/환율 손익 분해 (보유분에 한함)
        if qty > 0:
            avg_buy_rate = principal_krw / (data['total_cost_usd']) if data['total_cost_usd'] else 0
            fx_profit = data['total_cost_usd'] * (current_rate - avg_buy_rate)
            price_profit = unrealized_total - fx_profit
            be_rate = (principal_krw - d_krw - realized_krw) / eval_usd if eval_usd > 0 else 0
        else:
            fx_profit = 0; price_profit = 0; be_rate = 0
            
        # 총 누적 손익 = 평가손익 + 실현손익 + 배당
        grand_total = unrealized_total + realized_krw + d_krw
        
        rows.append({
            'Ticker': t, 'Name': data['name'],
            'Principal': principal_krw, 'Eval': eval_krw,
            'Price_Profit': price_profit, 'FX_Profit': fx_profit,
            'Div_Profit': d_krw, 'Realized_Profit': realized_krw,
            'Total_Profit': grand_total, # 표기상 Total은 누적 총합
            'Unrealized_Total': unrealized_total, # 카드 표기용 (평가손익)
            'Safety_Margin': current_rate - be_rate if qty > 0 else 0,
            'Qty': qty
        })
        
    df_combined = pd.DataFrame(rows)
    
    # 정렬
    df_combined['SortKey'] = df_combined['Ticker'].apply(lambda x: SORT_ORDER.index(x) if x in SORT_ORDER else 999)
    df_combined = df_combined.sort_values(['SortKey', 'Ticker']).drop(columns=['SortKey'])
    
    # ---------------- UI ----------------
    sub_kpi, sub_card, sub_html, sub_detail = st.tabs(["📊 KPI", "🗂️ 카드", "📑 통합", "📋 세부"])
    
    with sub_kpi:
        # KPI 계산
        # 총 투입 원금 = 현재 보유 원금 + (실현손익 제외? 아니면 포함? 수익률 계산시 분모는?)
        # 단순화: 현재 잔고 기준 ROI + 누적 실현 수익 별도 표기
        curr_principal = df_combined['Principal'].sum()
        curr_eval = df_combined['Eval'].sum()
        
        # 누적 실현 수익 (매도차익 + 배당) - 현재 환율 가치
        acc_realized_usd = total_realized_usd + total_div_usd
        acc_realized_krw = acc_realized_usd * current_rate
        
        # 총 평가 수익 (미실현)
        curr_unrealized = curr_eval - curr_principal
        
        # 전체 ROI (평가 + 실현) / (현재원금 - 실현분? 복잡함. 단순 ROI: 평가/원금)
        roi = (curr_unrealized / curr_principal * 100) if curr_principal else 0
        
        # 순수 환차익
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
        # 섹터별 요약 (보유중인 것만)
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
        
        # 개별 카드 (보유중인 것만)
        cols = st.columns(4)
        for idx, row in enumerate(active_df.itertuples()):
            with cols[idx % 4]:
                # 카드 표시: 평가 손익 기준 (Unrealized)
                profit = row.Unrealized_Total
                roi_val = profit / row.Principal * 100 if row.Principal else 0
                
                c = "c-red" if profit > 0 else "c-blue" if profit < 0 else "c-gray"
                sym = "▲" if profit > 0 else "▼" if profit < 0 else "-"
                
                if row.Ticker=='💵 USD CASH': margin_html = f'<span class="badge-margin bg-gray-light">∞</span>'
                elif row.Safety_Margin > 0: margin_html = f'<span class="badge-margin bg-green-light">안전 +{row.Safety_Margin:,.0f}</span>'
                else: margin_html = f'<span class="badge-margin bg-red-light">위험 {row.Safety_Margin:,.0f}</span>'
                
                # [수정] 괄호 없는 디자인 반영
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
                
                # 상세 팝업 (배당 & 실현손익 포함)
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
                # 보유중이 아니면 흐리게 표시하거나 스킵? 일단 다 표시하되 스타일 조정
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

# [PAGE 2] 입력 매니저 (옴니 파서 적용)
with main_tab2:
    st.subheader("데이터 입력")
    if st.session_state['input_log']:
        st.info("📋 세션 입력 내역")
        for l in st.session_state['input_log']: st.caption(f"✅ {l}")
        st.divider()

    c1, c2 = st.columns([1, 2])
    with c1:
        date_val = st.date_input("기준 날짜", datetime.now()) # 텍스트 내 날짜가 너무 많아 기준일 하나 잡는게 안전
        st.caption("※ 자동 모드는 텍스트 내의 모든 거래를 위 날짜로 저장합니다.")
        
        mode = st.radio("입력 모드", ["자동(카톡 뭉치)", "수동 매수", "수동 매도"])
        
        # 수동 입력 폼
        if "수동" in mode:
            m_ticker = st.text_input("종목코드 (예: O)")
            m_qty = st.number_input("수량", min_value=1, step=1)
            m_price = st.number_input("단가 ($)", min_value=0.01, step=0.01)
            
    with c2:
        raw_text = st.text_area("카톡 내용 붙여넣기 (광고, 잡담 섞여도 OK)", height=400)
        
    if st.button("저장 실행", type="primary"):
        try:
            sh = get_client()
            ts_base = datetime.now().strftime('%Y%m%d%H%M%S')
            log_list = []
            
            # --- 1. 수동 입력 처리 ---
            if "수동" in mode and m_ticker and m_qty > 0:
                type_str = "Sell" if "매도" in mode else "Buy"
                # 매수 시 평단 0 저장 (추후 자동계산), 매도 시에도 평단 불필요
                sh.worksheet("Trade_Log").append_row([str(date_val), ts_base, m_ticker.upper(), m_ticker.upper(), type_str, m_qty, m_price, 0, "수동"])
                log_list.append(f"{type_str}: {m_ticker} {m_qty}주 (@${m_price})")

            # --- 2. 자동(카톡 뭉치) 파싱 ---
            elif mode == "자동(카톡 뭉치)" and raw_text:
                
                # (A) 환전 파싱 (정규식: 외화매수환전...￦...USD)
                # 여러 줄에 걸쳐 있을 수 있으므로 re.DOTALL 사용
                ex_pattern = r'외화매수환전.*?￦([\d,]+).*?USD ([\d,.]+)'
                ex_matches = re.findall(ex_pattern, raw_text, re.DOTALL)
                
                for idx, (krw_str, usd_str) in enumerate(ex_matches):
                    k_val = int(krw_str.replace(',',''))
                    u_val = float(usd_str.replace(',',''))
                    rate = k_val / u_val
                    uid = f"{ts_base}_EX_{idx}"
                    sh.worksheet("Exchange_Log").append_row([str(date_val), uid, "KRW_to_USD", k_val, u_val, rate, "", "", "카톡일괄"])
                    log_list.append(f"💱 환전: ${u_val:,.2f} (@{rate:.1f}원)")

                # (B) 배당 파싱 (정규식: 티커...USD...세전배당입금)
                # 예: O/리얼티 인컴 \n USD 3.24 \n 세전배당입금
                div_pattern = r'([A-Z]+)/.*?\s+USD ([\d,.]+).*?세전배당입금'
                div_matches = re.findall(div_pattern, raw_text, re.DOTALL)
                
                for idx, (tk, amt_str) in enumerate(div_matches):
                    val_amt = float(amt_str.replace(',',''))
                    uid = f"{ts_base}_DIV_{idx}"
                    # 배당 환율은 1450 고정 혹은 추후 수정 필요
                    sh.worksheet("Dividend_Log").append_row([str(date_val), uid, tk, val_amt, 1450, "카톡일괄"])
                    log_list.append(f"🏦 배당: {tk} ${val_amt}")

                # (C) 주식 체결 파싱 (split 방식 유지 - 가장 정확함)
                if "체결안내" in raw_text:
                    blocks = raw_text.split("한국투자증권 체결안내")
                    trade_count = 0
                    for block in blocks:
                        if "종목명" not in block: continue
                        
                        # 키워드 파싱
                        type_match = re.search(r'\*매매구분:(매수|매도)', block)
                        tk_match = re.search(r'\*종목명:([A-Z]+)', block)
                        qt_match = re.search(r'\*체결수량:([\d]+)', block)
                        pr_match = re.search(r'\*체결단가:USD ([\d.]+)', block)
                        
                        if type_match and tk_match and qt_match and pr_match:
                            t_type = "Buy" if type_match.group(1) == "매수" else "Sell"
                            ticker = tk_match.group(1)
                            qty = int(qt_match.group(1))
                            price = float(pr_match.group(1))
                            
                            uid = f"{ts_base}_TR_{trade_count}"
                            sh.worksheet("Trade_Log").append_row([str(date_val), uid, ticker, ticker, t_type, qty, price, 0, "카톡일괄"])
                            log_list.append(f"🛒 {t_type}: {ticker} {qty}주")
                            trade_count += 1

            # 결과 처리
            if log_list:
                st.session_state['input_log'].extend(log_list)
                st.success(f"✅ 총 {len(log_list)}건의 데이터를 성공적으로 저장했습니다!")
                st.balloons()
                st.cache_data.clear() # 데이터 갱신
            else:
                st.error("분석된 내용이 없습니다. 텍스트 형식을 확인해주세요.")
                
        except Exception as e: st.error(f"처리 중 오류 발생: {str(e)}")
