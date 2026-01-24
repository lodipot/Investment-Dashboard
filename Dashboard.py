import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz
import textwrap

# -------------------------------------------------------------------
# 1. 초기 설정 & 스타일링
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

# [CSS] 탭바 고정 & 카드 스타일 & 버튼 수정
st.markdown("""
<style>
    /* 1. 탭바 상단 고정 (Sticky Tab Bar) */
    .stTabs [data-baseweb="tab-list"] {
        position: sticky;
        top: 0; /* 상단에서 0px 위치에 고정 */
        z-index: 999; /* 다른 요소보다 위에 표시 */
        background-color: white; /* 배경색 지정 (투명 방지) */
        padding-top: 1rem;
        padding-bottom: 1rem;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); /* 그림자 효과 */
    }
    
    /* 2. 정사각형 큐브 카드 (Cube Card) */
    .cube-card {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        height: 100%; /* 높이 꽉 채우기 */
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }
    .cube-title { font-size: 0.9rem; color: #6c757d; margin-bottom: 5px; font-weight: 600; }
    .cube-value { font-size: 1.2rem; font-weight: 800; color: #212529; margin-bottom: 2px; }
    .cube-sub { font-size: 0.8rem; font-weight: 500; }
    
    /* 3. 모바일 버튼 깨짐 방지 */
    div[data-testid="stPopover"] > button {
        width: 100%;
        height: 40px;
        border: 1px solid #dee2e6;
        background-color: white;
    }
    
    /* 색상 유틸리티 */
    .text-red { color: #D32F2F !important; }
    .text-blue { color: #1976D2 !important; }
    .text-gray { color: #adb5bd !important; }
    .text-green { color: #2E7D32 !important; }
</style>
""", unsafe_allow_html=True)

# [상수 설정]
BENCHMARK_RATE = 0.035
SECTORS = {
    'REITS': {'emoji': '🏢', 'name': '리츠 & 부동산', 'tickers': ['O', 'PLD']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당 & 방어주', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'KO']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크 (Stable)', 'tickers': ['MSFT', 'GOOGL']},
    'VOL_TECH': {'emoji': '🚀', 'name': '혁신테크 (Volatile)', 'tickers': ['NVDA', 'TSLA', 'AMD']},
    'CASH': {'emoji': '💵', 'name': '달러 현금', 'tickers': ['💵 USD CASH']}
}
SORT_ORDER = ['O', 'PLD', 'JEPI', 'JEPQ', 'KO', 'SCHD', 'GOOGL', 'MSFT', 'AMD', 'NVDA', 'TSLA', '💵 USD CASH']

# -------------------------------------------------------------------
# 2. 데이터 로드
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
# 3. 데이터 가공
# -------------------------------------------------------------------
try:
    trade_df, exchange_df, krw_assets_df, etf_df, div_df = load_data()
    
    # 전처리
    if not exchange_df.empty:
        exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
        exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
    if not trade_df.empty:
        trade_df['Qty'] = clean_currency(trade_df['Qty'])
        trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
        trade_df['Exchange_Rate'] = clean_currency(trade_df['Exchange_Rate'])
    if not div_df.empty: 
        div_df['Amount_USD'] = clean_currency(div_df['Amount_USD'])

    unique_tickers = trade_df['Ticker'].unique().tolist()
    current_rate, fx_status, price_map = get_market_data(unique_tickers)

    # A. 현금 계산
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

    # B. 주식 계산
    stock_rows = []
    if not trade_df.empty:
        for ticker, group in trade_df.groupby('Ticker'):
            qty = group['Qty'].sum()
            if qty == 0: continue
            
            principal_usd = (group['Qty'] * group['Price_USD']).sum()
            principal_krw = (group['Qty'] * group['Price_USD'] * group['Exchange_Rate']).sum()
            avg_buy_price = principal_usd / qty
            avg_buy_rate = principal_krw / principal_usd if principal_usd else 0

            cur_price = price_map.get(ticker, avg_buy_price)
            if cur_price == 0: cur_price = avg_buy_price

            eval_usd = qty * cur_price
            eval_krw = eval_usd * current_rate
            div_usd = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() if not div_df.empty else 0
            div_krw = div_usd * current_rate

            total_profit = eval_krw - principal_krw
            fx_profit = principal_usd * (current_rate - avg_buy_rate)
            price_profit = total_profit - fx_profit
            
            be_rate = (principal_krw - div_krw) / eval_usd if eval_usd > 0 else 0
            stock_rows.append({
                'Ticker': ticker, 'Name': group['Name'].iloc[0],
                'Principal': principal_krw, 'Eval': eval_krw,
                'Price_Profit': price_profit, 'FX_Profit': fx_profit,
                'Div_Profit': div_krw, 'Total_Profit': total_profit + div_krw,
                'Buy_Rate': avg_buy_rate, 'BE_Rate': be_rate, 'Safety_Margin': current_rate - be_rate
            })

    df_combined = pd.concat([pd.DataFrame([cash_row]), pd.DataFrame(stock_rows)], ignore_index=True)
    
    # 섹터 정보 & 정렬
    def get_sector(ticker):
        for code, info in SECTORS.items():
            if ticker in info['tickers']: return code
        return 'ETC'
    
    df_combined['Sector'] = df_combined['Ticker'].apply(get_sector)
    df_combined['SortKey'] = df_combined['Ticker'].apply(lambda x: SORT_ORDER.index(x) if x in SORT_ORDER else 999)
    df_combined = df_combined.sort_values(['SortKey', 'Ticker']).drop(columns=['SortKey'])

    # -------------------------------------------------------------------
    # 4. 화면 출력 (UI)
    # -------------------------------------------------------------------
    st.title("🚀 ISC") # 제목 간소화
    
    # 탭 구성
    tab_kpi, tab_card, tab_html, tab_detail = st.tabs(["📊 KPI", "🗂️ 카드", "📑 통합", "📋 세부"])

    # [TAB 1] KPI 요약 (카드형)
    with tab_kpi:
        total_principal = df_combined['Principal'].sum()
        roi = (df_combined['Total_Profit'].sum() / total_principal * 100) if total_principal else 0
        fx_roi = (df_combined['FX_Profit'].sum() / total_principal * 100) if total_principal else 0
        
        kpi_cols = st.columns(3)
        with kpi_cols[0]:
            excess = roi - (BENCHMARK_RATE*100)
            cls = "text-red" if excess > 0 else "text-blue"
            st.markdown(f"""<div class="cube-card"><div class="cube-title">총 투자 수익률</div><div class="cube-value {cls}">{roi:+.2f}%</div><div class="cube-sub">예금 대비 {excess:+.2f}%p</div></div>""", unsafe_allow_html=True)
        with kpi_cols[1]:
            cls = "text-red" if fx_roi > 0 else "text-blue"
            st.markdown(f"""<div class="cube-card"><div class="cube-title">순수 환차익</div><div class="cube-value {cls}">{fx_roi:+.2f}%</div><div class="cube-sub">환율 변동 효과</div></div>""", unsafe_allow_html=True)
        with kpi_cols[2]:
            fx_msg = "실시간" if fx_status == "Live" else "백업"
            st.markdown(f"""<div class="cube-card"><div class="cube-title">현재 환율 ({fx_msg})</div><div class="cube-value">{current_rate:,.2f}원</div><div class="cube-sub">USD/KRW</div></div>""", unsafe_allow_html=True)

    # [TAB 2] 카드형 현황
    with tab_card:
        # 섹터별 요약
        st.caption("📌 섹터별 현황")
        sec_cols = st.columns(len(SECTORS))
        for i, (code, info) in enumerate(SECTORS.items()):
            sec_df = df_combined[df_combined['Sector'] == code]
            sec_profit = sec_df['Total_Profit'].sum()
            sec_roi = sec_profit / sec_df['Principal'].sum() * 100 if sec_df['Principal'].sum() else 0
            
            with sec_cols[i]:
                if sec_profit > 0: cls="text-red"; sign="+"
                elif sec_profit < 0: cls="text-blue"; sign=""
                else: cls="text-gray"; sign=""
                
                # 금액이 크면 '만' 단위 절사
                val_str = f"{sec_profit/10000:,.0f}만" if abs(sec_profit) >= 10000 else f"{sec_profit:,.0f}"
                
                st.markdown(f"""
                <div class="cube-card" style="padding:10px;">
                    <div class="cube-title" style="font-size:0.8rem;">{info['emoji']} {info['name'].split(' ')[0]}</div>
                    <div class="cube-value {cls}" style="font-size:1rem;">{sign}{val_str}</div>
                    <div class="cube-sub {cls}">({sign}{sec_roi:.1f}%)</div>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 개별 종목 카드
        for code, info in SECTORS.items():
            sec_df = df_combined[df_combined['Sector'] == code]
            if sec_df.empty: continue
            
            st.markdown(f"**{info['emoji']} {info['name']}**")
            
            # 반응형 그리드 흉내 (st.columns 활용)
            cols = st.columns(4) 
            for idx, row in enumerate(sec_df.itertuples()):
                with cols[idx % 4]:
                    roi_val = row.Total_Profit / row.Principal * 100 if row.Principal else 0
                    
                    if row.Total_Profit > 0: cls="text-red"; sym="▲"; s="+"
                    elif row.Total_Profit < 0: cls="text-blue"; sym="▼"; s=""
                    else: cls="text-gray"; sym="-"; s=""
                    
                    # 큐브 카드 HTML
                    st.markdown(f"""
                    <div class="cube-card">
                        <div class="cube-title">{row.Ticker}</div>
                        <div class="cube-value">{row.Eval/10000:,.0f}만</div>
                        <div class="cube-sub {cls}">{sym} {abs(row.Total_Profit)/10000:,.0f}만 ({s}{roi_val:.1f}%)</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 팝업 버튼 (아이콘만 표시)
                    with st.popover("🔍", use_container_width=True):
                        st.markdown(f"### {row.Ticker} 상세")
                        st.divider()
                        c1, c2 = st.columns(2)
                        c1.metric("평가금액", f"{row.Eval:,.0f}원")
                        c2.metric("투자원금", f"{row.Principal:,.0f}원")
                        
                        st.write(f"**💰 손익분해**")
                        st.write(f"- 주가: {row.Price_Profit:,.0f} ({row.Price_Profit/row.Principal*100:+.1f}%)")
                        st.write(f"- 환율: {row.FX_Profit:,.0f} ({row.FX_Profit/row.Principal*100:+.1f}%)")
                        st.write(f"- 배당: {row.Div_Profit:,.0f}")
                        
                        st.divider()
                        if row.Ticker != '💵 USD CASH':
                            margin_col = "green" if row.Safety_Margin > 0 else "red"
                            st.write(f"**🛡️ 안전마진:** :{margin_col}[{row.Safety_Margin:+.1f}원]")
                            st.caption(f"(손익분기 환율: {row.BE_Rate:,.1f}원)")

    # [TAB 3] HTML 통합 테이블
    with tab_html:
        def make_clean_html(df):
            rows = ""
            for _, row in df.iterrows():
                if row['Total_Profit'] > 0: t_cls="red"; t_sym="▲"
                elif row['Total_Profit'] < 0: t_cls="blue"; t_sym="▼"
                else: t_cls="zero"; t_sym="-"
                
                def v_fmt(v, pct=False):
                    if v==0: return '<span class="zero">-</span>'
                    c = "red" if v>0 else "blue"
                    t = f"{v:+.2f}%" if pct else f"{v:,.0f}"
                    return f'<span class="{c}">{t}</span>'

                p_roi = row['Price_Profit']/row['Principal']*100 if row['Principal'] else 0
                f_roi = row['FX_Profit']/row['Principal']*100 if row['Principal'] else 0
                t_roi = row['Total_Profit']/row['Principal']*100 if row['Principal'] else 0
                
                margin_txt = f"{row['Safety_Margin']:+.1f}" if row['Ticker'] != '💵 USD CASH' else "∞"
                
                rows += f"""
                <tr>
                    <td style="text-align:left"><b>{row['Ticker']}</b><br><span style="font-size:0.8em;color:gray">{row['Name']}</span></td>
                    <td>{v_fmt(row['Price_Profit'])}<br><span style="font-size:0.85em">{v_fmt(p_roi, True)}</span></td>
                    <td>{v_fmt(row['FX_Profit'])}<br><span style="font-size:0.85em">{v_fmt(f_roi, True)}</span></td>
                    <td>{v_fmt(row['Total_Profit'])}<br><span style="font-size:0.85em">{v_fmt(t_roi, True)}</span></td>
                    <td><b>{margin_txt}</b></td>
                </tr>"""
            
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
            # 현금 맨 뒤로 보내기
            df_detail = df_combined.copy()
            df_detail['SortKey'] = df_detail['Ticker'].apply(lambda x: 999 if 'CASH' in x else 0)
            df_detail = df_detail.sort_values(['SortKey', 'Ticker']).drop(columns=['SortKey'])
            
            # 표시용 포맷팅
            df_view = df_detail[['Ticker', 'Principal', 'Eval', 'Price_Profit', 'FX_Profit', 'Total_Profit', 'Safety_Margin']].copy()
            df_view['ROI'] = df_detail['Total_Profit'] / df_detail['Principal']
            
            # 합계행
            sum_row = df_view.sum(numeric_only=True)
            sum_row['ROI'] = sum_row['Total_Profit'] / sum_row['Principal']
            sum_row['Ticker'] = '🔴 TOTAL'
            df_view = pd.concat([df_view, pd.DataFrame([sum_row])], ignore_index=True)
            
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
