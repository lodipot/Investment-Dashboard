import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import textwrap

# -------------------------------------------------------------------
# 1. 초기 설정 & CSS (UI/UX Ultimate)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    /* [1] 탭바 상단 고정 (Sticky Tab Bar) */
    .stTabs [data-baseweb="tab-list"] {
        position: sticky;
        top: 3rem;
        z-index: 999;
        background-color: white;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        margin-top: -3rem;
    }

    /* [2] KPI 전용 그리드 (무조건 3열 + 반응형 폰트) */
    .kpi-container {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr; /* 항상 3등분 */
        gap: 8px; /* 사이 간격 */
        margin-bottom: 20px;
    }
    .kpi-cube {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 1vw; /* 패딩도 화면 크기에 비례 */
        text-align: center;
        display: flex;
        flex-direction: column;
        justify-content: center;
        aspect-ratio: 1 / 0.8; /* 약간 납작한 직사각형 비율 유지 */
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .kpi-title { 
        font-size: clamp(10px, 1.2vw, 16px); /* 최소 10px, 최대 16px, 화면따라 가변 */
        color: #6c757d; 
        font-weight: 600; 
        white-space: nowrap;
    }
    .kpi-value { 
        font-size: clamp(14px, 2.5vw, 32px); /* 화면 폭의 2.5% 크기 */
        font-weight: 800; 
        color: #212529; 
        margin: 4px 0;
    }
    .kpi-sub { 
        font-size: clamp(9px, 1vw, 14px); 
        font-weight: 500; 
    }

    /* [3] 주식 카드 (롤백된 디자인 - Rich Info) */
    .stock-card {
        background-color: white;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        transition: transform 0.2s;
    }
    .stock-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        transform: translateY(-2px);
    }
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 8px;
    }
    .ticker-name { font-size: 1.1rem; font-weight: 700; color: #333; }
    .full-name { font-size: 0.8rem; color: #888; margin-left: 6px; }
    
    .main-val { font-size: 1.4rem; font-weight: 800; color: #212529; margin-bottom: 4px; }
    
    .profit-row { font-size: 0.95rem; font-weight: 600; margin-bottom: 12px; }
    
    .badge-margin {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 700;
        background-color: #f1f3f5;
    }

    /* [4] 모바일 버튼 텍스트 깨짐 방지 Hack */
    div[data-testid="stPopover"] > button {
        width: 100%;
        border: 1px solid #dee2e6;
        background-color: white;
        color: transparent !important;
        text-shadow: 0 0 0 #495057;
        height: 38px;
    }

    /* 색상 유틸리티 */
    .c-red { color: #D32F2F !important; }
    .c-blue { color: #1976D2 !important; }
    .c-gray { color: #adb5bd !important; }
    .bg-red-light { background-color: #ffebee !important; color: #c62828 !important; }
    .bg-green-light { background-color: #e8f5e9 !important; color: #2e7d32 !important; }
    .bg-gray-light { background-color: #f8f9fa !important; color: #495057 !important; }

</style>
""", unsafe_allow_html=True)

# [상수 설정]
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
def clean_currency(series):
    return pd.to_numeric(series.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

@st.cache_data(ttl=60)
def load_data():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Investment_Dashboard_DB")

        trade_df = pd.DataFrame(sh.worksheet("Trade_Log").get_all_records())
        exchange_df = pd.DataFrame(sh.worksheet("Exchange_Log").get_all_records())
        krw_assets_df = pd.DataFrame(sh.worksheet("KRW_Assets").get_all_records())
        etf_df = pd.DataFrame(sh.worksheet("Domestic_ETF").get_all_records())
        try:
            div_df = pd.DataFrame(sh.worksheet("Dividend_Log").get_all_records())
        except:
            div_df = pd.DataFrame(columns=['Date', 'Ticker', 'Amount_USD', 'Note'])

        return trade_df, exchange_df, krw_assets_df, etf_df, div_df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_market_data(tickers):
    fx = 1450.0 
    fx_status = "Fallback"
    try:
        fx_hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not fx_hist.empty:
            fx = fx_hist['Close'].iloc[-1]
            fx_status = "Live"
        else:
            fx_hist_bk = yf.Ticker("KRW=X").history(period="1d")
            if not fx_hist_bk.empty:
                fx = fx_hist_bk['Close'].iloc[-1]
                fx_status = "Live(Backup)"
    except: pass 

    data_map = {}
    if tickers:
        valid_tickers = [t for t in tickers if t != '💵 USD CASH']
        for t in valid_tickers:
            try:
                hist = yf.Ticker(t).history(period="1d")
                if not hist.empty:
                    data_map[t] = hist['Close'].iloc[-1]
            except: pass 
    return fx, fx_status, data_map

# -------------------------------------------------------------------
# 3. 데이터 계산 로직
# -------------------------------------------------------------------
try:
    trade_df, exchange_df, krw_assets_df, etf_df, div_df = load_data()
    
    if not exchange_df.empty:
        exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
        exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
    if not trade_df.empty:
        trade_df['Qty'] = clean_currency(trade_df['Qty'])
        trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
    if not div_df.empty: 
        div_df['Amount_USD'] = clean_currency(div_df['Amount_USD'])

    unique_tickers = trade_df['Ticker'].unique().tolist()
    current_rate, fx_status, price_map = get_market_data(unique_tickers)

    # A. 현금
    total_usd_exchanged = exchange_df['USD_Amount'].sum() if not exchange_df.empty else 0
    total_krw_exchanged = exchange_df['KRW_Amount'].sum() if not exchange_df.empty else 0
    avg_cash_rate = total_krw_exchanged / total_usd_exchanged if total_usd_exchanged > 0 else 0
    
    total_usd_invested = (trade_df['Qty'] * trade_df['Price_USD']).sum() if not trade_df.empty else 0
    usd_cash_balance = total_usd_exchanged - total_usd_invested
    
    cash_principal = usd_cash_balance * avg_cash_rate
    cash_eval = usd_cash_balance * current_rate
    cash_row = {
        'Ticker': '💵 USD CASH', 'Name': '달러예수금',
        'Principal': cash_principal, 'Eval': cash_eval,
        'Price_Profit': 0, 'FX_Profit': cash_principal * (current_rate/avg_cash_rate - 1) if avg_cash_rate else 0,
        'Div_Profit': 0, 'Total_Profit': cash_eval - cash_principal,
        'Buy_Rate': avg_cash_rate, 'BE_Rate': 0, 'Safety_Margin': 9999
    }

    # B. 주식
    stock_rows = []
    if not trade_df.empty:
        for ticker, group in trade_df.groupby('Ticker'):
            qty = group['Qty'].sum()
            if qty == 0: continue
            
            principal_usd = (group['Qty'] * group['Price_USD']).sum()
            # Trade_Log의 Exchange_Rate는 '매수 시점의 평단'임
            principal_krw = (group['Qty'] * group['Price_USD'] * group['Exchange_Rate']).sum()
            
            # 안전장치
            if principal_krw == 0 and principal_usd > 0: principal_krw = principal_usd * 1450

            avg_buy_rate = principal_krw / principal_usd if principal_usd else 0
            
            cur_price = price_map.get(ticker, 0)
            if cur_price == 0: cur_price = principal_usd / qty # 현재가 없으면 평단으로

            eval_usd = qty * cur_price
            eval_krw = eval_usd * current_rate
            div_usd = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() if not div_df.empty else 0
            div_krw = div_usd * current_rate

            fx_profit = principal_usd * (current_rate - avg_buy_rate)
            total_profit = (eval_krw - principal_krw) + div_krw
            price_profit = (eval_krw - principal_krw) - fx_profit
            
            be_rate = (principal_krw - div_krw) / eval_usd if eval_usd > 0 else 0
            
            stock_rows.append({
                'Ticker': ticker, 'Name': group['Name'].iloc[0],
                'Principal': principal_krw, 'Eval': eval_krw,
                'Price_Profit': price_profit, 'FX_Profit': fx_profit, 'Div_Profit': div_krw,
                'Total_Profit': total_profit, 'Buy_Rate': avg_buy_rate,
                'BE_Rate': be_rate, 'Safety_Margin': current_rate - be_rate
            })

    df_combined = pd.concat([pd.DataFrame([cash_row]), pd.DataFrame(stock_rows)], ignore_index=True)
    
    # 섹터 & 정렬
    def get_sector(ticker):
        for code, info in SECTORS.items():
            if ticker in info['tickers']: return code
        return 'ETC'
    
    df_combined['Sector'] = df_combined['Ticker'].apply(get_sector)
    df_combined['SortKey'] = df_combined['Ticker'].apply(lambda x: SORT_ORDER.index(x) if x in SORT_ORDER else 999)
    df_combined = df_combined.sort_values(['SortKey', 'Ticker']).drop(columns=['SortKey'])

    # -------------------------------------------------------------------
    # 4. UI 출력
    # -------------------------------------------------------------------
    tab_kpi, tab_card, tab_html, tab_detail = st.tabs(["📊 KPI", "🗂️ 카드", "📑 통합", "📋 세부"])

    # [TAB 1] KPI (Responsive Grid 3-Columns)
    with tab_kpi:
        total_principal = df_combined['Principal'].sum()
        total_return = df_combined['Total_Profit'].sum()
        roi = (total_return / total_principal * 100) if total_principal else 0
        total_fx = df_combined['FX_Profit'].sum()
        fx_roi = (total_fx / total_principal * 100) if total_principal else 0
        
        excess = roi - (BENCHMARK_RATE*100)
        kpi_cls = "c-red" if excess > 0 else "c-blue"
        fx_cls = "c-red" if fx_roi > 0 else "c-blue"
        fx_msg = "실시간" if fx_status == "Live" else "백업"

        # HTML 한 덩어리로 렌더링 (CSS Grid 적용)
        st.markdown(f"""
        <div class="kpi-container">
            <div class="kpi-cube">
                <div class="kpi-title">총 수익률</div>
                <div class="kpi-value {kpi_cls}">{roi:+.2f}%</div>
                <div class="kpi-sub">예금 대비 {excess:+.2f}%p</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">순수 환차익</div>
                <div class="kpi-value {fx_cls}">{fx_roi:+.2f}%</div>
                <div class="kpi-sub">환율 변동 효과</div>
            </div>
            <div class="kpi-cube">
                <div class="kpi-title">현재 환율 ({fx_msg})</div>
                <div class="kpi-value">{current_rate:,.0f}원</div>
                <div class="kpi-sub">USD/KRW</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # [TAB 2] 카드 현황 (Design Rollback - Rich Info)
    with tab_card:
        # 섹터 요약
        st.caption("📌 섹터별 요약")
        sec_cols = st.columns(len(SECTORS))
        for i, (code, info) in enumerate(SECTORS.items()):
            sec_df = df_combined[df_combined['Sector'] == code]
            sec_profit = sec_df['Total_Profit'].sum()
            sec_roi = sec_profit / sec_df['Principal'].sum() * 100 if sec_df['Principal'].sum() else 0
            
            with sec_cols[i]:
                if sec_profit > 0: cls="c-red"; sign="+"
                elif sec_profit < 0: cls="c-blue"; sign=""
                else: cls="c-gray"; sign=""
                
                st.markdown(f"""
                <div style="text-align:center; padding:5px; background:#f8f9fa; border-radius:8px;">
                    <div style="font-size:0.8rem; color:#666;">{info['emoji']} {info['name'].split(' ')[0]}</div>
                    <div class="{cls}" style="font-size:0.9rem; font-weight:bold;">{sign}{sec_profit:,.0f}</div>
                    <div class="{cls}" style="font-size:0.75rem;">({sign}{sec_roi:.1f}%)</div>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 개별 종목 (롤백된 디자인)
        for code, info in SECTORS.items():
            sec_df = df_combined[df_combined['Sector'] == code]
            if sec_df.empty: continue
            
            st.markdown(f"**{info['emoji']} {info['name']}**")
            cols = st.columns(4) # PC 4열, 모바일 자동 줄바꿈
            
            for idx, row in enumerate(sec_df.itertuples()):
                with cols[idx % 4]:
                    roi_val = row.Total_Profit / row.Principal * 100 if row.Principal else 0
                    
                    if row.Total_Profit > 0: 
                        cls="c-red"; sym="▲"; s="+"
                    elif row.Total_Profit < 0: 
                        cls="c-blue"; sym="▼"; s=""
                    else: 
                        cls="c-gray"; sym="-"; s=""
                    
                    # 안전마진 뱃지
                    if row.Ticker == '💵 USD CASH':
                        margin_html = f'<span class="badge-margin bg-gray-light">∞</span>'
                    elif row.Safety_Margin > 0:
                        margin_html = f'<span class="badge-margin bg-green-light">안전 +{row.Safety_Margin:,.0f}</span>'
                    else:
                        margin_html = f'<span class="badge-margin bg-red-light">위험 {row.Safety_Margin:,.0f}</span>'

                    # 카드 HTML (상세 정보형)
                    st.markdown(f"""
                    <div class="stock-card">
                        <div class="card-header">
                            <span class="ticker-name">{row.Ticker}</span>
                            <span class="full-name">{row.Name}</span>
                        </div>
                        <div class="main-val">{row.Eval:,.0f}</div>
                        <div class="profit-row {cls}">
                            {sym} {abs(row.Total_Profit):,.0f} ({s}{roi_val:.1f}%)
                        </div>
                        <div style="text-align:right;">
                            {margin_html}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 팝업 (돋보기 아이콘)
                    with st.popover("🔍", use_container_width=True):
                        st.markdown(f"**{row.Ticker} 상세 분석**")
                        st.divider()
                        st.write(f"💰 원금: {row.Principal:,.0f}원")
                        st.write(f"💵 평가: {row.Eval:,.0f}원")
                        st.write(f"📈 합계손익: {row.Total_Profit:,.0f}원")
                        st.divider()
                        st.write(f"📉 주가손익: {row.Price_Profit:,.0f}원")
                        st.write(f"💱 환율손익: {row.FX_Profit:,.0f}원")
                        st.write(f"🏦 배당수익: {row.Div_Profit:,.0f}원")

    # [TAB 3] 통합 테이블
    with tab_html:
        def make_clean_html(df):
            rows = ""
            for _, row in df.iterrows():
                if row['Total_Profit'] > 0: t_cls="red"
                elif row['Total_Profit'] < 0: t_cls="blue"
                else: t_cls="zero"
                
                def v_fmt(v, pct=False):
                    if v==0: return '<span class="zero">-</span>'
                    c = "red" if v>0 else "blue"
                    t = f"{v:+.2f}%" if pct else f"{v:,.0f}"
                    return f'<span class="{c}">{t}</span>'

                margin_txt = f"{row['Safety_Margin']:+.1f}" if row['Ticker'] != '💵 USD CASH' else "∞"
                
                rows += f"""
                <tr>
                    <td style="text-align:left"><b>{row['Ticker']}</b><br><span style="font-size:0.8em;color:gray">{row['Name']}</span></td>
                    <td>{v_fmt(row['Price_Profit'])}</td>
                    <td>{v_fmt(row['FX_Profit'])}</td>
                    <td>{v_fmt(row['Total_Profit'])}</td>
                    <td><b>{margin_txt}</b></td>
                </tr>"""
            
            # 합계행
            sum_p = df['Price_Profit'].sum()
            sum_f = df['FX_Profit'].sum()
            sum_t = df['Total_Profit'].sum()
            
            def sum_fmt(v):
                c = "red" if v>0 else "blue"
                return f'<span class="{c}"><b>{v:,.0f}</b></span>'

            rows += f"""
            <tr style="background-color: #fafafa; border-top: 2px solid #aaa;">
                <td style="text-align:left">🔴 <b>TOTAL</b></td>
                <td>{sum_fmt(sum_p)}</td>
                <td>{sum_fmt(sum_f)}</td>
                <td>{sum_fmt(sum_t)}</td>
                <td>-</td>
            </tr>
            """

            return textwrap.dedent(f"""
            <style>
                .red {{color: #D32F2F; font-weight: bold;}}
                .blue {{color: #1976D2; font-weight: bold;}}
                .zero {{color: #ccc;}}
                table {{width: 100%; border-collapse: collapse; font-size: 0.9em;}}
                th {{background: #f0f2f6; padding: 10px; text-align: right; color: #333; border-bottom: 2px solid #ccc; position: sticky; top: 0;}}
                td {{padding: 10px; border-bottom: 1px solid #eee; text-align: right; vertical-align: middle;}}
            </style>
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left">종목</th>
                        <th>주가손익</th>
                        <th>환손익</th>
                        <th>합계손익</th>
                        <th>안전마진</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
            """)
        st.markdown(make_clean_html(df_combined), unsafe_allow_html=True)

    # [TAB 4] 세부 내역
    with tab_detail:
        sub_t1, sub_t2, sub_t3 = st.tabs(["🇺🇸 미국주식", "🇰🇷 국내ETF", "🏦 예금/공제"])
        with sub_t1:
            df_view = df_combined.copy()
            df_view['ROI'] = df_view['Total_Profit'] / df_view['Principal']
            
            sum_row = df_view.sum(numeric_only=True)
            sum_row['ROI'] = sum_row['Total_Profit'] / sum_row['Principal']
            sum_row['Ticker'] = '🔴 TOTAL'
            df_view = pd.concat([df_view, pd.DataFrame([sum_row])], ignore_index=True)
            
            cols = ['Ticker', 'Principal', 'Eval', 'Price_Profit', 'FX_Profit', 'Total_Profit', 'ROI', 'Safety_Margin']
            df_view = df_view[cols]
            
            def color_map(v):
                if isinstance(v, (int, float)) and v!=0:
                    return 'color: #D32F2F; font-weight: bold;' if v>0 else 'color: #1976D2; font-weight: bold;'
                return ''
            
            st.dataframe(
                df_view.style.format("{:,.0f}", subset=['Principal','Eval','Price_Profit','FX_Profit','Total_Profit'])
                .format("{:+.2%}", subset=['ROI'])
                .format("{:+.1f}", subset=['Safety_Margin'])
                .applymap(color_map, subset=['Price_Profit','FX_Profit','Total_Profit','ROI','Safety_Margin']),
                use_container_width=True
            )
        with sub_t2:
            if not etf_df.empty: st.dataframe(etf_df, use_container_width=True)
        with sub_t3:
            if not krw_assets_df.empty: st.dataframe(krw_assets_df, use_container_width=True)

except Exception as e:
    st.error(f"시스템 오류: {e}")
