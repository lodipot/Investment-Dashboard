import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz
import textwrap

# -------------------------------------------------------------------
# 1. 초기 설정 & CSS (UI/UX Polishing)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    /* [1] 탭바 상단 고정 (Sticky Tab Bar) */
    .stTabs [data-baseweb="tab-list"] {
        position: sticky;
        top: 3rem; /* 헤더 높이만큼 띄움 */
        z-index: 999;
        background-color: white;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        margin-top: -3rem; /* 시각적 보정 */
    }

    /* [2] 완벽한 정사각형 큐브 카드 (Square Fixed) */
    .cube-card {
        aspect-ratio: 1 / 1; /* 가로세로 1:1 강제 고정 */
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 16px; /* 둥근 모서리 강조 */
        padding: 10px; /* 내부 여백 */
        text-align: center;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        
        /* 내용물 중앙 정렬 */
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        overflow: hidden; /* 넘치는 내용 숨김 (안전장치) */
    }
    
    /* 카드 내부 텍스트 스타일 */
    .cube-title { font-size: 0.85rem; color: #6c757d; margin-bottom: 4px; font-weight: 600; white-space: nowrap; }
    .cube-value { font-size: 1.1rem; font-weight: 800; color: #212529; margin-bottom: 2px; line-height: 1.2; word-break: keep-all; }
    .cube-sub { font-size: 0.75rem; font-weight: 500; margin-top: 2px; }

    /* [3] 모바일 버튼 텍스트 깨짐 방지 (강력한 Hack) */
    /* Popover 버튼 내부 텍스트 숨기고 이모지만 표시 */
    div[data-testid="stPopover"] > button {
        width: 100%;
        border: 1px solid #dee2e6;
        background-color: white;
        color: transparent !important; /* 텍스트(expand_more 등) 투명화 */
        text-shadow: 0 0 0 #495057; /* 이모지 색상 복원 */
        display: flex;
        justify-content: center;
        align-items: center;
    }
    /* 버튼 내 아이콘 강제 정렬 */
    div[data-testid="stPopover"] > button > div {
        display: flex;
        justify-content: center;
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
    'REITS': {'emoji': '🏢', 'name': '리츠', 'tickers': ['O', 'PLD']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'KO']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크', 'tickers': ['MSFT', 'GOOGL']},
    'VOL_TECH': {'emoji': '🚀', 'name': '성장주', 'tickers': ['NVDA', 'TSLA', 'AMD']},
    'CASH': {'emoji': '💵', 'name': '현금', 'tickers': ['💵 USD CASH']}
}
# 사용자 지정 정렬 순서
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
            principal_krw = (group['Qty'] * group['Price_USD'] * group['Exchange_Rate']).sum() # Trade_Log에 저장된 Exchange_Rate 사용
            avg_buy_price = principal_usd / qty
            
            # Trade Log의 Ex_Rate가 비어있으면(0이면) 단순 계산 (안전장치)
            if principal_krw == 0 and principal_usd > 0:
                 principal_krw = principal_usd * 1450

            cur_price = price_map.get(ticker, avg_buy_price)
            if cur_price == 0: cur_price = avg_buy_price

            eval_usd = qty * cur_price
            eval_krw = eval_usd * current_rate
            div_usd = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() if not div_df.empty else 0
            div_krw = div_usd * current_rate

            total_profit = eval_krw - principal_krw
            
            # 환손익: 달러원금 * (현재환율 - 매수환율)
            avg_buy_rate = principal_krw / principal_usd if principal_usd else 0
            fx_profit = principal_usd * (current_rate - avg_buy_rate)
            
            price_profit = total_profit - fx_profit - div_krw # 나머지는 주가+배당인데 배당 분리시 주가만 남음? 
            # 아니, Total = Eval - Principal
            # Total = (Price_P + FX_P) -> 여기서 Div는 별도 수령액이므로 Total에 포함 X? 
            # 사용자 정의: Total Profit = (Eval - Principal) + Div
            total_profit_with_div = total_profit + div_krw
            
            # 역산: Total(포함) = Price(순수) + FX + Div
            # Price = Total(포함) - FX - Div = (Eval - Principal + Div) - FX - Div = Eval - Principal - FX
            price_profit = (eval_krw - principal_krw) - fx_profit

            be_rate = (principal_krw - div_krw) / eval_usd if eval_usd > 0 else 0
            
            stock_rows.append({
                'Ticker': ticker, 'Name': group['Name'].iloc[0],
                'Principal': principal_krw, 'Eval': eval_krw,
                'Price_Profit': price_profit, 'FX_Profit': fx_profit,
                'Div_Profit': div_krw, 'Total_Profit': total_profit_with_div,
                'Buy_Rate': avg_buy_rate, 'BE_Rate': be_rate, 'Safety_Margin': current_rate - be_rate
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
    # 탭 구성
    tab_kpi, tab_card, tab_html, tab_detail = st.tabs(["📊 KPI", "🗂️ 카드", "📑 통합", "📋 세부"])

    # [TAB 1] KPI (Square Cube)
    with tab_kpi:
        total_principal = df_combined['Principal'].sum()
        total_return = df_combined['Total_Profit'].sum()
        roi = (total_return / total_principal * 100) if total_principal else 0
        
        total_fx = df_combined['FX_Profit'].sum()
        fx_roi = (total_fx / total_principal * 100) if total_principal else 0
        
        c1, c2, c3 = st.columns(3)
        with c1:
            excess = roi - (BENCHMARK_RATE*100)
            cls = "text-red" if excess > 0 else "text-blue"
            st.markdown(f"""<div class="cube-card"><div class="cube-title">총 수익률</div><div class="cube-value {cls}">{roi:+.2f}%</div><div class="cube-sub">vs 예금 {excess:+.2f}%p</div></div>""", unsafe_allow_html=True)
        with c2:
            cls = "text-red" if fx_roi > 0 else "text-blue"
            st.markdown(f"""<div class="cube-card"><div class="cube-title">환차익</div><div class="cube-value {cls}">{fx_roi:+.2f}%</div><div class="cube-sub">순수 환효과</div></div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""<div class="cube-card"><div class="cube-title">현재 환율</div><div class="cube-value">{current_rate:,.0f}원</div><div class="cube-sub">실시간</div></div>""", unsafe_allow_html=True)

    # [TAB 2] 카드 현황 (Square Cube, Full Number)
    with tab_card:
        # 섹터 요약
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
                
                # [수정] 만 단위 절사 제거 -> Full Number
                val_str = f"{sec_profit:,.0f}" 
                
                st.markdown(f"""
                <div class="cube-card" style="padding:5px;">
                    <div class="cube-title">{info['emoji']} {info['name'].split(' ')[0]}</div>
                    <div class="cube-value {cls}" style="font-size:0.95rem;">{sign}{val_str}</div>
                    <div class="cube-sub {cls}">({sign}{sec_roi:.1f}%)</div>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 개별 종목 (Full Number)
        for code, info in SECTORS.items():
            sec_df = df_combined[df_combined['Sector'] == code]
            if sec_df.empty: continue
            
            st.markdown(f"**{info['emoji']} {info['name']}**")
            cols = st.columns(4) 
            for idx, row in enumerate(sec_df.itertuples()):
                with cols[idx % 4]:
                    roi_val = row.Total_Profit / row.Principal * 100 if row.Principal else 0
                    
                    if row.Total_Profit > 0: cls="text-red"; sym="▲"; s="+"
                    elif row.Total_Profit < 0: cls="text-blue"; sym="▼"; s=""
                    else: cls="text-gray"; sym="-"; s=""
                    
                    # [수정] Full Number 적용
                    st.markdown(f"""
                    <div class="cube-card">
                        <div class="cube-title">{row.Ticker}</div>
                        <div class="cube-value">{row.Eval:,.0f}</div>
                        <div class="cube-sub {cls}">{sym}{abs(row.Total_Profit):,.0f} ({s}{roi_val:.1f}%)</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 팝업 (CSS Hack 적용됨)
                    with st.popover("🔍", use_container_width=True):
                        st.markdown(f"**{row.Ticker} ({row.Name})**")
                        st.divider()
                        st.write(f"💰 원금: {row.Principal:,.0f}원")
                        st.write(f"💵 평가: {row.Eval:,.0f}원")
                        st.write(f"📈 손익: {row.Total_Profit:,.0f}원")
                        if row.Ticker != '💵 USD CASH':
                            st.divider()
                            st.write(f"🛡️ 안전마진: {row.Safety_Margin:+.1f}원")

    # [TAB 3] 통합 테이블 (+ 합계행 추가)
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
            
            # [수정] 합계 행 계산 및 추가
            sum_p = df['Price_Profit'].sum()
            sum_f = df['FX_Profit'].sum()
            sum_t = df['Total_Profit'].sum()
            sum_princ = df['Principal'].sum()
            
            sum_p_roi = sum_p / sum_princ * 100 if sum_princ else 0
            sum_f_roi = sum_f / sum_princ * 100 if sum_princ else 0
            sum_t_roi = sum_t / sum_princ * 100 if sum_princ else 0
            
            def sum_fmt(v, roi):
                c = "red" if v>0 else "blue"
                return f'<span class="{c}"><b>{v:,.0f}</b><br><span style="font-size:0.85em">({roi:+.2f}%)</span></span>'

            rows += f"""
            <tr style="background-color: #fafafa; border-top: 2px solid #aaa;">
                <td style="text-align:left">🔴 <b>TOTAL</b></td>
                <td>{sum_fmt(sum_p, sum_p_roi)}</td>
                <td>{sum_fmt(sum_f, sum_f_roi)}</td>
                <td>{sum_fmt(sum_t, sum_t_roi)}</td>
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
            # 현금 맨 뒤로 (이미 SortKey로 처리됨)
            df_view = df_combined.copy()
            df_view['ROI'] = df_view['Total_Profit'] / df_view['Principal']
            
            # 합계행
            sum_row = df_view.sum(numeric_only=True)
            sum_row['ROI'] = sum_row['Total_Profit'] / sum_row['Principal']
            sum_row['Ticker'] = '🔴 TOTAL'
            df_view = pd.concat([df_view, pd.DataFrame([sum_row])], ignore_index=True)
            
            # 필요한 컬럼만
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
