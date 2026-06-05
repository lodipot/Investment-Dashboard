import pandas as pd

def sync_api_to_ledger(client, df_ledger):
    """
    기존 원장 데이터를 보존하며 API 데이터로 Pending 상태를 Confirmed로 덮어씁니다(Upsert).
    """
    # 1. API 호출 로직 (해외주식 체결 예시: TTTS3035R 등)
    # api_records = fetch_recent_trades_from_api(...) # (기존 구현하신 KIS API 호출 함수)
    
    # 테스트용 가상의 API 응답 데이터 (실제 파싱 로직에 연결)
    api_records = [
        # {'Ticker': 'AAPL', 'Timestamp': '2025-05-23 23:30:15', 'Quantity': 10, 'Price': 150.0, 'Event_Type': '매수', 'Order_No': '1234567890'}
    ]
    
    ws = client.open("Investment_Dashboard_DB").worksheet("Unified_Ledger")
    
    # 2. Upsert 매칭 로직
    updates_made = False
    for api_rec in api_records:
        # API 데이터로 Hash PK 생성 (초 단위 시간이 다를 수 있으므로 날짜 단위까지만 매칭하거나 별도 매핑 로직 필요)
        api_event_id_prefix = "EVT_" + hashlib.sha256(f"{api_rec['Timestamp'][:10]}_{api_rec['Ticker']}_{api_rec['Quantity']}_{api_rec['Price']}_{api_rec['Event_Type']}".encode()).hexdigest()[:8]
        
        # DataFrame에서 매칭되는 Pending 레코드 찾기
        mask = (df_ledger['Status'] == 'Pending') & (df_ledger['Event_ID'].str.contains(api_event_id_prefix))
        matching_rows = df_ledger[mask]
        
        if not matching_rows.empty:
            row_idx = matching_rows.index[0]
            # 구글 시트의 행 번호는 index + 2 (헤더가 1행이므로)
            sheet_row = int(row_idx) + 2 
            
            # 3. 빈칸 채우기 (Order_No) 및 상태(Confirmed) 업데이트
            ws.update_cell(sheet_row, 2, 'Confirmed') # Status 열(2번)
            ws.update_cell(sheet_row, 13, api_rec['Order_No']) # Order_No 열(13번)
            
            # 정확한 초단위 Timestamp 덮어쓰기
            ws.update_cell(sheet_row, 3, api_rec['Timestamp']) 
            
            updates_made = True
            
    return updates_made
