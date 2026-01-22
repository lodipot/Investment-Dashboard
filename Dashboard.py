import streamlit as st
import pandas as pd
import yfinance as yf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz
import textwrap

# -------------------------------------------------------------------
# 1. 초기 설정 (Config)
# -------------------------------------------------------------------
st.set_page_config(page_title="Investment Strategy Command", layout="wide", page_icon="📈")

# [상수 설정]
BENCHMARK_RATE = 0.035
# 섹터 분류 정의
SECTORS = {
    'REITS': {'emoji': '🏢', 'name': '리츠 & 부동산', 'tickers': ['O', 'PLD']},
    'DVD_DEF': {'emoji': '💰', 'name': '배당 & 방어주', 'tickers': ['SCHD', 'JEPI', 'JEPQ', 'KO']},
    'BIG_TECH': {'emoji': '💻', 'name': '빅테크 (Stable)', 'tickers': ['MSFT', 'GOOGL']},
    'VOL_TECH': {'emoji': '🚀', 'name': '혁신테크 (Volatile)', 'tickers': ['NVDA', 'TSLA', 'AMD']},
    'CASH': {'emoji': '💵', 'name': '달러 현금', 'tickers': ['💵 USD CASH']}
}

# -------------------------------------------------------------------
# 2. 데이터 로드 및 API
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
# 3. 사이드바
# -------------------------------------------------------------------
with st.sidebar:
    st.header("🎮 Control Tower")
    korea_tz = pytz.timezone('Asia/Seoul')
    st.caption(f"Update: {datetime.now(korea_tz).strftime('%H:%M:%S')}")
    st.info("💡 F5를 누르면 데이터가 갱신됩니다.")
    st.markdown("---")
    show_tax = st.toggle("세후 실질 가치 보기", value=False)

# -------------------------------------------------------------------
# 4. 데이터 가공 (Calculation)
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

    df_combined = pd.concat([pd.DataFrame([cash_row]), pd.DataFrame(stock_rows)], ignore_index=True)
    
    # 섹터 정보 매핑
    def get_sector(ticker):
        for code, info in SECTORS.items():
            if ticker in info['tickers']: return code
        return 'ETC'
    
    df_combined['Sector'] = df_combined['Ticker'].apply(get_sector)

    # -------------------------------------------------------------------
    # 5. UI 출력 (탭 구조)
    # -------------------------------------------------------------------
    st.title("🚀 Investment Strategy Command")
    
    # 탭 구성 (요청하신 순서대로)
    tab_kpi, tab_card, tab_html, tab_detail = st.tabs(["📊 KPI 요약", "🗂️ 카드형 현황", "📑 통합 테이블", "📋 세부 내역"])

    # -------------------------------------------------------------------
    # [TAB 1] KPI 요약
    # -------------------------------------------------------------------
    with tab_kpi:
        total_principal = df_combined['Principal'].sum()
        roi = (df_combined['Total_Profit'].sum() / total_principal * 100) if total_principal else 0
        fx_roi = (df_combined['FX_Profit'].sum() / total_principal * 100) if total_principal else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("총 투자 수익률", f"{roi:+.2f}%", f"{roi - (BENCHMARK_RATE*100):+.2f}%p (vs 예금)")
        c2.metric("순수 환차익", f"{fx_roi:+.2f}%", "환율 변동 기여분")
        fx_msg = "실시간" if fx_status == "Live" else "백업"
        c3.metric(f"현재 환율 ({fx_msg})", f"{current_rate:,.2f}원")

    # -------------------------------------------------------------------
    # [TAB 2] 해외자산 통합 현황 (카드형)
    # -------------------------------------------------------------------
    with tab_card:
        # 섹터별 중간 점검 (요약 카드)
        st.subheader("📌 섹터별 요약")
        sec_cols = st.columns(len(SECTORS))
        for i, (code, info) in enumerate(SECTORS.items()):
            sec_df = df_combined[df_combined['Sector'] == code]
            sec_profit = sec_df['Total_Profit'].sum()
            
            with sec_cols[i]:
                # 섹터 요약 카드 HTML
                bg_color = "#f9f9f9"
                if sec_profit > 0: txt_color = "#D32F2F" # Red
                elif sec_profit < 0: txt_color = "#1976D2" # Blue
                else: txt_color = "#333"
                
                st.markdown(f"""
                <div style="background:{bg_color}; padding:10px; border-radius:8px; border:1px solid #eee; text-align:center;">
                    <div style="font-size:0.9em; color:#666;">{info['emoji']} {info['name']}</div>
                    <div style="font-size:1.1em; font-weight:bold; color:{txt_color};">{sec_profit:,.0f}원</div>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 섹터별 개별 카드 (가로 배치)
        for code, info in SECTORS.items():
            sec_df = df_combined[df_combined['Sector'] == code]
            if sec_df.empty: continue
            
            st.markdown(f"#### {info['emoji']} {info['name']}")
            
            # 카드를 그리드로 배치 (한 줄에 3~4개 정도 들어가게)
            # 스트림릿 columns를 사용하여 배치
            cols = st.columns(len(sec_df) if len(sec_df) < 4 else 4) 
            
            for idx, row in enumerate(sec_df.itertuples()):
                # 열 순환 (Wrap around)
                with cols[idx % 4]:
                    # [디자인 로직]
                    # 1. 금액: 일반 텍스트 (검정)
                    # 2. 손익: ▲/▼ + 금액 (색상)
                    # 3. 수익률: ±% (색상, 괄호 없음)
                    
                    roi_val = row.Total_Profit / row.Principal * 100 if row.Principal else 0
                    
                    if row.Total_Profit > 0:
                        cls = "red"; symbol = "▲"; sign = "+"
                        color_code = "#D32F2F"
                    elif row.Total_Profit < 0:
                        cls = "blue"; symbol = "▼"; sign = "" # 음수는 숫자에 -가 포함됨
                        color_code = "#1976D2"
                    else:
                        cls = "gray"; symbol = "-"; sign = ""
                        color_code = "#666"

                    # 안전마진 뱃지 색상 (양수=안전=초록)
                    margin_color = "#2E7D32" if row.Safety_Margin > 0 else "#D32F2F"
                    margin_txt = "∞" if row.Ticker == '💵 USD CASH' else f"{row.Safety_Margin:+.0f}"

                    # 카드 HTML
                    card_html = f"""
                    <div style="background:white; padding:15px; border-radius:10px; border:1px solid #eee; box-shadow:0 1px 3px rgba(0,0,0,0.1); margin-bottom:10px;">
                        <div style="font-weight:bold; font-size:1.05em; margin-bottom:8px;">
                            {row.Ticker} <span style="font-size:0.8em; color:#888; font-weight:normal;">{row.Name}</span>
                        </div>
                        <div style="font-size:1.2em; font-weight:bold; color:#333; margin-bottom:2px;">
                            {row.Eval:,.0f}원
                        </div>
                        <div style="font-size:1em; color:{color_code}; margin-bottom:8px;">
                            {symbol} {abs(row.Total_Profit):,.0f} <span style="font-size:0.9em; margin-left:4px;">{sign}{roi_val:.2f}%</span>
                        </div>
                        <div style="font-size:0.8em; color:#555;">
                            안전마진 <span style="background:{margin_color}15; color:{margin_color}; padding:2px 6px; border-radius:4px; font-weight:bold;">{margin_txt}</span>
                        </div>
                    </div>
                    """
                    st.markdown(card_html, unsafe_allow_html=True)
                    
                    # 팝업 버튼 (카드 바로 아래 배치)
                    with st.popover("🔍 상세 보기", use_container_width=True):
                        st.markdown(f"### {row.Ticker} 상세 분석")
                        
                        st.markdown("##### 💰 자산 현황")
                        col_a, col_b = st.columns(2)
                        col_a.metric("투자원금", f"{row.Principal:,.0f}원")
                        col_b.metric("평가금액", f"{row.Eval:,.0f}원", f"{row.Total_Profit:,.0f}원")
                        
                        st.markdown("##### 📊 수익 분해")
                        # 0값은 '-' 처리
                        def fmt(v): return f"{v:,.0f}원" if v!=0 else "-"
                        st.write(f"- **주가 손익:** {fmt(row.Price_Profit)}")
                        st.write(f"- **환율 손익:** {fmt(row.FX_Profit)}")
                        st.write(f"- **배당 수익:** {fmt(row.Div_Profit)}")
                        
                        st.markdown("##### 🛡️ 리스크")
                        st.write(f"- **매수 환율:** {row.Buy_Rate:,.1f}원")
                        if row.Ticker != '💵 USD CASH':
                            st.write(f"- **손익분기:** {row.BE_Rate:,.1f}원")
                            margin_msg = "안전" if row.Safety_Margin > 0 else "주의"
                            st.write(f"- **안전마진:** {row.Safety_Margin:+.1f}원 ({margin_msg})")

    # -------------------------------------------------------------------
    # [TAB 3] HTML 복행 테이블 (재도전)
    # -------------------------------------------------------------------
    with tab_html:
        def make_clean_html(df):
            rows = ""
            for _, row in df.iterrows():
                # 색상/기호 로직 (카드와 동일)
                if row['Total_Profit'] > 0: 
                    t_cls = "red"; t_sym = "▲"
                elif row['Total_Profit'] < 0: 
                    t_cls = "blue"; t_sym = "▼"
                else: 
                    t_cls = "zero"; t_sym = "-"
                
                # 값 포맷팅 helper
                def val_fmt(v, is_pct=False):
                    if v == 0: return '<span class="zero">-</span>'
                    color = "red" if v > 0 else "blue"
                    # 부호 제거하고 색상으로 표현 (요청사항 반영)
                    # 하지만 테이블에서는 ±가 명확해야 하므로 유지하되 스타일 적용
                    if is_pct: txt = f"{v:+.2f}%"
                    else: txt = f"{v:,.0f}"
                    return f'<span class="{color}">{txt}</span>'

                p_roi = row['Price_Profit']/row['Principal']*100 if row['Principal'] else 0
                f_roi = row['FX_Profit']/row['Principal']*100 if row['Principal'] else 0
                t_roi = row['Total_Profit']/row['Principal']*100 if row['Principal'] else 0
                
                margin_txt = f"{row['Safety_Margin']:+.1f}" if row['Ticker'] != '💵 USD CASH' else "∞"
                
                rows += f"""
                <tr>
                    <td style="text-align:left"><b>{row['Ticker']}</b><br><span style="font-size:0.8em;color:gray">{row['Name']}</span></td>
                    <td>{val_fmt(row['Price_Profit'])}<br><span style="font-size:0.85em">{val_fmt(p_roi, True)}</span></td>
                    <td>{val_fmt(row['FX_Profit'])}<br><span style="font-size:0.85em">{val_fmt(f_roi, True)}</span></td>
                    <td>{val_fmt(row['Total_Profit'])}<br><span style="font-size:0.85em">{val_fmt(t_roi, True)}</span></td>
                    <td><b>{margin_txt}</b></td>
                </tr>"""
            
            # dedent로 들여쓰기 제거 -> 코드 노출 방지
            return textwrap.dedent(f"""
            <style>
                .red {{color: #D32F2F; font-weight: bold;}}
                .blue {{color: #1976D2; font-weight: bold;}}
                .zero {{color: #ccc;}}
                table {{width: 100%; border-collapse: collapse; font-size: 0.9em;}}
                th {{background: #f0f2f6; padding: 10px; text-align: right; color: #333; border-bottom: 2px solid #ccc;}}
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

    # -------------------------------------------------------------------
    # [TAB 4] 세부 내역 (기존 Styler 유지)
    # -------------------------------------------------------------------
    with tab_detail:
        st.caption("※ 해외자산의 상세 데이터와 국내 ETF/예금 현황입니다.")
        sub_t1, sub_t2, sub_t3 = st.tabs(["🇺🇸 전체 리스트", "🇰🇷 국내 ETF", "🏦 예금/공제"])
        
        with sub_t1:
            # 표시용 DF
            df_view = df_combined.copy()
            df_view['주가(%)'] = df_view.apply(lambda x: x['Price_Profit']/x['Principal'] if x['Principal'] else 0, axis=1)
            df_view['환(%)'] = df_view.apply(lambda x: x['FX_Profit']/x['Principal'] if x['Principal'] else 0, axis=1)
            df_view['총수익(%)'] = df_view.apply(lambda x: x['Total_Profit']/x['Principal'] if x['Principal'] else 0, axis=1)
            
            cols = ['Ticker', 'Principal', 'Eval', 'Price_Profit', '주가(%)', 'FX_Profit', '환(%)', 'Total_Profit', '총수익(%)', 'Safety_Margin']
            df_view = df_view[cols]
            df_view.columns = ['종목', '투자원금', '평가금액', '주가손익', '주가(%)', '환손익', '환(%)', '합계손익', '총수익(%)', '안전마진']
            
            # 합계행
            sum_row = df_view.sum(numeric_only=True)
            sum_row['주가(%)'] = sum_row['주가손익'] / sum_row['투자원금']
            sum_row['환(%)'] = sum_row['환손익'] / sum_row['투자원금']
            sum_row['총수익(%)'] = sum_row['합계손익'] / sum_row['투자원금']
            sum_row['종목'] = '🔴 TOTAL'
            df_view = pd.concat([df_view, pd.DataFrame([sum_row])], ignore_index=True)

            def fmt_money(v): return "-" if v==0 else f"{v:,.0f}"
            def fmt_pct(v): return "-" if v==0 else f"{v:+.2%}"
            def color_rb(v):
                if isinstance(v, (int, float)) and v!=0:
                    return 'color: #D32F2F; font-weight: bold;' if v>0 else 'color: #1976D2; font-weight: bold;'
                return ''

            st.dataframe(
                df_view.style
                .format({'투자원금':fmt_money, '평가금액':fmt_money, '주가손익':fmt_money, '환손익':fmt_money, '합계손익':fmt_money, '주가(%)':fmt_pct, '환(%)':fmt_pct, '총수익(%)':fmt_pct, '안전마진':"{:,.1f}"})
                .applymap(color_rb, subset=['주가손익','환손익','합계손익','주가(%)','환(%)','총수익(%)','안전마진']),
                use_container_width=True
            )

        with sub_t2:
            if not etf_df.empty: st.dataframe(etf_df, use_container_width=True)
        with sub_t3:
            if not krw_assets_df.empty: st.dataframe(krw_assets_df, use_container_width=True)

except Exception as e:
    st.error(f"⚠️ 시스템 오류 발생: {e}")
