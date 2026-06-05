import re
import hashlib
from datetime import datetime
import gspread

# 1. 고유 Event_ID (Hash PK) 생성 로직
def generate_event_id(timestamp, ticker, qty, price, event_type):
    """
    거래일자, 종목, 수량, 단가, 거래유형을 조합하여 고유한 식별자를 만듭니다.
    기존 원장을 날리지 않고 API 데이터와 매핑하기 위한 핵심 Key입니다.
    """
    raw_str = f"{timestamp}_{ticker}_{qty}_{price}_{event_type}"
    return "EVT_" + hashlib.sha256(raw_str.encode('utf-8')).hexdigest()[:12]

# 2. 카카오톡 정규식 파서 (확장 가능하도록 모듈화)
def parse_kakao_alert(raw_text):
    """
    카카오톡 알림 텍스트를 파싱하여 신통합원장 14개 열 규격의 딕셔너리로 반환합니다.
    (정규식 패턴은 실제 알림 포맷에 맞춰 추가/수정이 필요할 수 있습니다.)
    """
    parsed_events = []
    
    # [예시] 체결 알림 정규식 (매수/매도)
    trade_pattern = re.compile(r'\[한국투자\]\s*(매수|매도)체결\s*종목명:\s*(.*?)\((.*?)\)\s*체결수량:\s*([\d,]+)주\s*체결단가:\s*([\d.,]+)\s*(USD|JPY|KRW|HKD)\s*체결일시:\s*(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})')
    
    # [예시] 배당 알림 정규식
    div_pattern = re.compile(r'\[한국투자\]\s*해외주식\s*배당금\s*입금\s*종목명:\s*(.*?)\((.*?)\)\s*입금금액:\s*([\d.,]+)\s*(USD|JPY)')

    # 매매 체결 파싱
    for match in trade_pattern.finditer(raw_text):
        event_type, asset_name, ticker, qty, price, currency, timestamp = match.groups()
        qty = float(qty.replace(',', ''))
        price = float(price.replace(',', ''))
        total_amount = qty * price
        
        # JPY/USD/KRW 시장 구분
        market = 'US' if currency == 'USD' else 'JP' if currency == 'JPY' else 'KR' if currency == 'KRW' else 'HK'

        event_id = generate_event_id(timestamp, ticker, qty, price, event_type)
        
        parsed_events.append({
            'Event_ID': event_id,
            'Status': 'Pending',  # API 동기화 전 임시 상태
            'Timestamp': timestamp,
            'Event_Type': event_type,
            'Market': market,
            'Ticker': ticker,
            'Asset_Name': asset_name.strip(),
            'Quantity': qty,
            'Price': price,
            'Currency': currency,
            'Total_Amount': total_amount,
            'KRW_Amount': 0, # 환전이 아니므로 0
            'Order_No': '',  # API 동기화 시 채워짐
            'Note': '카톡파싱_매매'
        })
    
    # 배당 및 환전 파싱 로직 추가 (생략, 위 패턴 참조하여 append)
    
    return parsed_events

# 3. 구글 시트 Insert 로직
def insert_events_to_sheet(client, events):
    if not events:
        return 0
    
    sh = client.open("Investment_Dashboard_DB")
    ws = sh.worksheet("Unified_Ledger")
    
    # 14개 열 순서에 맞춰 리스트화
    rows_to_insert = []
    for e in events:
        row = [
            e['Event_ID'], e['Status'], e['Timestamp'], e['Event_Type'], e['Market'], 
            e['Ticker'], e['Asset_Name'], e['Quantity'], e['Price'], e['Currency'], 
            e['Total_Amount'], e['KRW_Amount'], e['Order_No'], e['Note']
        ]
        rows_to_insert.append(row)
    
    ws.append_rows(rows_to_insert, value_input_option='USER_ENTERED')
    return len(rows_to_insert)

# 4. 수동 원화(KRW) 입출금 전용 함수
def manual_krw_entry(client, date_time, event_type, amount, note):
    event_id = "MANUAL_" + hashlib.sha256(f"{date_time}_{event_type}_{amount}".encode()).hexdigest()[:8]
    event = {
        'Event_ID': event_id, 'Status': 'Confirmed', 'Timestamp': date_time.strftime("%Y-%m-%d %H:%M:%S"),
        'Event_Type': event_type, 'Market': '-', 'Ticker': '-', 'Asset_Name': '-',
        'Quantity': 0, 'Price': 0, 'Currency': 'KRW', 'Total_Amount': 0, 'KRW_Amount': amount,
        'Order_No': '-', 'Note': note
    }
    return insert_events_to_sheet(client, [event])
