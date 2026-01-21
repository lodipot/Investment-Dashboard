import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.graph_objects as go
from datetime import datetime
import pytz

# -------------------------------------------------------------------
# 1. 초기 설정 (Config)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈")

# [상수 설정]
BENCHMARK_RATE = 0.035  # 예금 금리 3.5%
TICKER_PRIORITY = ['💵 USD CASH', 'O', 'PLD', 'SCHD', 'JEPI', 'JEPQ', 'KO', 'MSFT', 'GOOGL', 'NVDA', 'TSLA', 'AMD']

# -------------------------------------------------------------------
# 2. 데이터 로드 및 API (Robust Logic)
# -------------------------------------------------------------------
def clean_currency(series):
    """ 콤마 제거 및 숫자 변환 """
    return pd.to_numeric(series.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

@st.cache_data(ttl=300)
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
        st.error(f"구글 시트 로드 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_market_data(tickers):
    """ 
    [개선된 로직] 환율 및 주가 조회 (이중 백업) 
    """
    fx = 1450.0 
    fx_source = "Fallback"

    # 1. 환율 조회 (USDKRW=X 시도 -> 실패시 KRW=X 시도)
    try:
        fx_hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not fx_hist.empty:
            fx = fx_hist['Close'].iloc[-1]
            fx_source = "Live"
        else:
            # 백업 티커 시도
            fx_hist_bk = yf.Ticker("KRW=X").history(period="1d")
            if not fx_hist_bk.empty:
                fx = fx_hist_bk['Close'].iloc[-1]
                fx_source = "Live(Backup)"
    except:
        pass # 최종 실패 시 1450 유지

    data_map = {}
    if tickers:
        valid_tickers = [t for t in tickers if t != '💵 USD CASH']
        # 안전을 위해 개별 호출 (일괄 호출은 하나만 터져도 다 멈출 수 있음)
        for t in valid_tickers:
            try:
                hist = yf.Ticker(t).history(period="1d")
                if not hist.empty:
                    data_map[t] = hist['Close'].iloc[-1]
            except:
                pass 
                
    return fx, fx_source, data_map

# -------------------------------------------------------------------
# 3. 사이드바
# -------------------------------------------------------------------
with st.sidebar:
    st.header("🎮 Control Tower")
    if st.button("🔄 데이터 최신화", type="primary"):
        st.cache_data.clear()
        st.rerun()
    
    korea_tz = pytz.timezone('Asia/Seoul')
    st.caption(f"Update: {datetime.now(korea_tz).strftime('%Y-%m-%d %H:%M:%S')}")
    st.markdown("---")
    show_tax = st.toggle("세후 실질 가치 보기", value=False)
    if show_tax:
        st.info("미국 22%, ISA 9.9% 세금 반영됨")

# -------------------------------------------------------------------
# 4. 메인 로직
# -------------------------------------------------------------------
try:
    trade_df, exchange_df, krw_assets_df, etf_df, div_df = load_data()
    
    # 숫자 변환
    if not exchange_df.empty:
        exchange_df['USD_Amount'] = clean_currency(exchange_df['USD_Amount'])
        exchange_df['KRW_Amount'] = clean_currency(exchange_df['KRW_Amount'])
    if not trade_df.empty:
        trade_df['Qty'] = clean_currency(trade_df['Qty'])
        trade_df['Price_USD'] = clean_currency(trade_df['Price_USD'])
        trade_df['Exchange_Rate'] = clean_currency(trade_df['Exchange_Rate'])
    if not div_df.empty: 
        div_df['Amount_USD'] = clean_currency(div_df['Amount_USD'])

    # API 호출
    unique_tickers = trade_df['Ticker'].unique().tolist()
    current_rate, fx_status, price_map = get_market_data(unique_tickers)

    # ---------------- [계산 로직] ----------------
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
            principal_krw = (group['Qty'] * group['Price_USD'] * group['Exchange_Rate']).sum()
            avg_buy_price = principal_usd / qty
            avg_buy_rate = principal_krw / principal_usd if principal_usd else 0

            # 현재가 (없으면 매수가로 대체하여 전손 방지)
            cur_price = price_map.get(ticker, avg_buy_price)
            if cur_price == 0: cur_price = avg_buy_price

            eval_usd = qty * cur_price
            eval_krw = eval_usd * current_rate
            
            div_usd = div_df[div_df['Ticker'] == ticker]['Amount_USD'].sum() if not div_df.empty else 0
            div_krw = div_usd * current_rate

            total_profit = eval_krw - principal_krw
            fx_profit = principal_usd * (current_rate - avg_buy_rate)
            price_profit = total_profit - fx_profit

            if show_tax:
                taxable = total_profit + div_krw - 2500000
                if taxable > 0:
                    tax = taxable * 0.22
                    eval_krw -= tax
                    total_profit -= tax
            
            be_rate = (principal_krw - div_krw) / eval_usd if eval_usd > 0 else 0
            
            stock_rows.append({
                'Ticker': ticker, 'Name': group['Name'].iloc[0],
                'Principal': principal_krw, 'Eval': eval_krw,
                'Price_Profit': price_profit, 'FX_Profit': fx_profit,
                'Div_Profit': div_krw, 'Total_Profit': total_profit + div_krw,
                'Buy_Rate': avg_buy_rate, 'BE_Rate': be_rate, 'Safety_Margin': current_rate - be_rate
            })

    # 데이터프레임 통합
    df_combined = pd.concat([pd.DataFrame([cash_row]), pd.DataFrame(stock_rows)], ignore_index=True)
    
    # ---------------- [UI 출력] ----------------
    
    # 1. KPI
    total_principal = df_combined['Principal'].sum()
    total_return = df_combined['Total_Profit'].sum()
    roi = (total_return / total_principal * 100) if total_principal else 0
    
    st.title("🚀 Investment Strategy Command")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("총 투자 수익률", f"{roi:+.2f}%", f"{roi - (BENCHMARK_RATE*100):+.2f}%p (vs 예금)")
    c2.metric("순수 환차익", f"{df_combined['FX_Profit'].sum()/total_principal*100:+.2f}%")
    
    # 환율 상태 표시 (Live / Fallback)
    fx_display = f"{current_rate:,.2f}원"
    if fx_status == "Fallback":
        c3.metric("환율 (⚠️연결실패)", "1,450.00원", "API 응답없음")
    else:
        c3.metric("현재 시장 환율", fx_display, "실시간 연동중")

    # 2. 섹터 그래프
    st.subheader("⚖️ 포트폴리오 밸런스")
    div_gr = ['O', 'PLD', 'SCHD', 'JEPI', 'JEPQ', 'KO']
    tech_gr = ['MSFT', 'GOOGL', 'NVDA', 'TSLA', 'AMD']
    
    p_div = df_combined[df_combined['Ticker'].isin(div_gr)]['Total_Profit'].sum()
    p_tech = df_combined[df_combined['Ticker'].isin(tech_gr)]['Total_Profit'].sum()
    p_cash = cash_row['Total_Profit']
    
    fig = go.Figure(go.Bar(
        y=['배당/리츠', '테크/성장', '달러현금'],
        x=[p_div, p_tech, p_cash],
        orientation='h',
        marker_color=['#FF3B30' if x>0 else '#007AFF' for x in [p_div, p_tech, p_cash]]
    ))
    fig.update_layout(height=150, margin=dict(l=0,r=0,t=0,b=0))
    fig.add_vline(x=0, line_color="gray")
    st.plotly_chart(fig, use_container_width=True)

    # 3. 메인 테이블 (Pandas Styler 도입 - 안정성 확보)
    st.subheader("📑 해외자산 통합 현황")
    
    # 표시용 데이터 준비
    df_view = df_combined.copy()
    df_view['SortKey'] = df_view['Ticker'].apply(lambda x: TICKER_PRIORITY.index(x) if x in TICKER_PRIORITY else 999)
    df_view = df_view.sort_values(['SortKey', 'Ticker']).drop(columns=['SortKey', 'Name']) # Name은 Ticker 옆에 병기 불가하므로 일단 제외하거나 별도 표시
    
    # ROI 계산 (표시용)
    df_view['주가수익률'] = df_view.apply(lambda x: x['Price_Profit']/x['Principal'] if x['Principal'] else 0, axis=1)
    df_view['환수익률'] = df_view.apply(lambda x: x['FX_Profit']/x['Principal'] if x['Principal'] else 0, axis=1)
    df_view['통합수익률'] = df_view.apply(lambda x: x['Total_Profit']/x['Principal'] if x['Principal'] else 0, axis=1)

    # 컬럼 재배치 및 이름 변경 (한글화)
    cols_order = ['Ticker', 'Principal', 'Eval', 'Price_Profit', '주가수익률', 'FX_Profit', '환수익률', 'Div_Profit', 'Total_Profit', '통합수익률', 'Safety_Margin']
    df_view = df_view[cols_order]
    
    df_view.columns = ['종목', '투자원금', '평가금액', '주가손익', '주가(%)', '환손익', '환(%)', '배당수익', '합계손익', '총수익(%)', '안전마진']

    # 합계행 추가
    sum_row = df_view.sum(numeric_only=True)
    # 수익률 재계산 (단순합산 X)
    sum_row['주가(%)'] = sum_row['주가손익'] / sum_row['투자원금']
    sum_row['환(%)'] = sum_row['환손익'] / sum_row['투자원금']
    sum_row['총수익(%)'] = sum_row['합계손익'] / sum_row['투자원금']
    sum_row['종목'] = '🔴 TOTAL'
    
    df_view = pd.concat([df_view, pd.DataFrame([sum_row])], ignore_index=True)

    # 스타일링 함수 (빨강/파랑 색상 적용)
    def color_red_blue(val):
        if isinstance(val, (int, float)):
            if val > 0: return 'color: #D32F2F; font-weight: bold;' # Red
            if val < 0: return 'color: #1976D2; font-weight: bold;' # Blue
        return ''

    # Pandas Styler 적용
    st.dataframe(
        df_view.style
        .format({
            '투자원금': '{:,.0f}', '평가금액': '{:,.0f}',
            '주가손익': '{:,.0f}', '주가(%)': '{:+.2%}',
            '환손익': '{:,.0f}', '환(%)': '{:+.2%}',
            '배당수익': '{:,.0f}',
            '합계손익': '{:,.0f}', '총수익(%)': '{:+.2%}',
            '안전마진': '{:,.1f}'
        })
        .applymap(color_red_blue, subset=['주가손익', '주가(%)', '환손익', '환(%)', '합계손익', '총수익(%)', '안전마진']),
        use_container_width=True,
        height=(len(df_view) + 1) * 35 + 3 # 높이 자동 조절
    )

    # 4. 하단 탭
    st.markdown("###")
    t1, t2, t3 = st.tabs(["🇺🇸 세부 내역", "🇰🇷 국내 ETF", "🏦 예금/공제"])
    
    with t1:
        st.dataframe(df_view.style.format(precision=2), use_container_width=True) # 위와 동일한 포맷
    with t2:
        if not etf_df.empty:
            # ETF도 데이터 처리 필요
            etf_disp = etf_df.copy()
            etf_disp['Qty'] = pd.to_numeric(etf_disp['Qty'])
            etf_disp['Price_KRW'] = pd.to_numeric(etf_disp['Price_KRW'])
            etf_disp['평가액'] = etf_disp['Qty'] * etf_disp['Price_KRW']
            etf_disp['손익'] = 0 # 매수단가 데이터 없으므로 임시 0
            st.dataframe(etf_disp, use_container_width=True)
    with t3:
        if not krw_assets_df.empty:
            st.dataframe(krw_assets_df, use_container_width=True)

except Exception as e:
    st.error(f"⚠️ 시스템 오류 발생: {e}")
