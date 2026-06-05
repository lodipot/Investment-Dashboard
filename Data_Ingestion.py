import re
import hashlib
from datetime import datetime

def generate_event_id(timestamp, ticker, qty, price, event_type):
    raw_str = f"{timestamp}_{ticker}_{qty}_{price}_{event_type}"
    return "EVT_" + hashlib.sha256(raw_str.encode('utf-8')).hexdigest()[:12]

def parse_kakao_alert(raw_text):
    parsed_events = []
    
    # 1. 체결 알림 파싱 (한국투자증권 기본 양식 기준 예시)
    trade_pattern = re.compile(r'\[한국투자\]\s*(매수|매도)체결\s*종목명:\s*(.*?)\((.*?)\)\s*체결수량:\s*([\d,]+)주\s*체결단가:\s*([\d.,]+)\s*(USD|JPY|KRW|HKD)\s*체결일시:\s*(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})')
    
    for match in trade_pattern.finditer(raw_text):
        event_type, asset_name, ticker, qty, price, currency, timestamp = match.groups()
        qty, price = float(qty.replace(',', '')), float(price.replace(',', ''))
        market = 'US' if currency == 'USD' else 'JP' if currency == 'JPY' else 'KR'
        
        parsed_events.append({
            'Event_ID': generate_event_id(timestamp, ticker, qty, price, event_type),
            'Status': 'Pending', 'Timestamp': timestamp, 'Event_Type': event_type,
            'Market': market, 'Ticker': ticker, 'Asset_Name': asset_name.strip(),
            'Quantity': qty, 'Price': price, 'Currency': currency,
            'Total_Amount': qty * price, 'KRW_Amount': 0, 'Order_No': '', 'Note': '카톡파싱'
        })
    
    # 2. 환전 알림 파싱 (필요 시 정규식 패턴 수정)
    # 3. 배당 알림 파싱 (필요 시 정규식 패턴 수정)
    
    return parsed_events

def insert_events_to_sheet(client, events):
    if not events: return
    ws = client.open("Investment_Dashboard_DB").worksheet("Unified_Ledger")
    rows = [[e['Event_ID'], e['Status'], e['Timestamp'], e['Event_Type'], e['Market'], 
             e['Ticker'], e['Asset_Name'], e['Quantity'], e['Price'], e['Currency'], 
             e['Total_Amount'], e['KRW_Amount'], e['Order_No'], e['Note']] for e in events]
    ws.append_rows(rows, value_input_option='USER_ENTERED')

def manual_krw_entry(client, date_time, event_type, amount, note):
    final_amt = amount if event_type == "입금" else -amount
    event_id = "MANUAL_" + hashlib.sha256(f"{date_time}_{event_type}_{amount}".encode()).hexdigest()[:8]
    insert_events_to_sheet(client, [{
        'Event_ID': event_id, 'Status': 'Confirmed', 'Timestamp': date_time.strftime("%Y-%m-%d %H:%M:%S"),
        'Event_Type': event_type, 'Market': '-', 'Ticker': '-', 'Asset_Name': '-',
        'Quantity': 0, 'Price': 0, 'Currency': 'KRW', 'Total_Amount': 0, 'KRW_Amount': final_amt,
        'Order_No': '-', 'Note': note
    }])
