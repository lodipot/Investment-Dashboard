# [KIS_API_Manager.py 내부의 get_trade_history 함수 전면 교체]

def get_trade_history(start_date, end_date):
    token = get_access_token()
    if not token: return None

    # [핵심 변경]
    # URL: 기간별 체결내역 (inquire-period-ccld) -> 체결 기준! (결제X)
    # TR_ID: TTTS3012R (실전투자용 해외주식 기간별 체결내역)
    # 참고: 모의투자는 VTSS3012R 이지만, 여기선 실전(TTTS3012R) 적용
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "TTTS3012R",  # <--- [FIX] JTTT3001R -> TTTS3012R 로 수정
        "custtype": "P"
    }
    
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ORD_DT_S": start_date,
        "ORD_DT_E": end_date,
        "CTX_AREA_FK100": "", # 연속조회 키 (필요시 구현)
        "CTX_AREA_NK100": ""
    }
    
    # URL: /inquire-period-ccld (체결내역)
    res = _request_api('GET', f"{URL_BASE}/uapi/overseas-stock/v1/trading/inquire-period-ccld", headers, params=params)
    
    if res.status_code == 200:
        data = res.json()
        
        # [데이터 정제]
        # TTTS3012R의 응답 구조도 'output1' 리스트에 담겨옵니다.
        # 필드명이 약간 다를 수 있으므로 안전하게 매핑합니다.
        
        output_list = []
        if 'output1' in data:
            for item in data['output1']:
                # 체결 수량이 있는 것만 처리
                qty = int(item.get('ccld_qty', 0))
                if qty > 0:
                    mapped_item = {
                        'dt': item['ord_dt'],        # 주문일(체결일)
                        'pdno': item['pdno'],        # 종목코드
                        'prdt_name': item['prdt_name'], # 종목명
                        'sll_buy_dvsn_cd': item['sll_buy_dvsn_cd'], # 01:매도, 02:매수
                        'ccld_qty': str(qty),
                        # 체결단가 (avg_prvs:체결평균가 우선, 없으면 ft_ccld_unpr3)
                        'ft_ccld_unpr3': item.get('avg_prvs', item.get('ft_ccld_unpr3', '0'))
                    }
                    output_list.append(mapped_item)
        
        return {'output1': output_list}
            
    return None
