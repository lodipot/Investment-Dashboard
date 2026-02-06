# [KIS_API_Manager.py 의 get_trade_history 함수 전체 교체]

def get_trade_history(start_date, end_date):
    token = get_access_token()
    if not token: return None

    # [공식 문서 기반 수정]
    # API 명: 해외주식 주문체결내역
    # TR_ID: TTTS3035R (실전투자) / VTTS3035R (모의투자)
    # URL: /uapi/overseas-stock/v1/trading/inquire-ccnl
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "TTTS3035R", # [중요] 문서에서 확인한 정확한 TR_ID
        "custtype": "P"
    }
    
    # 문서에 명시된 파라미터 구조 준수
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ORD_STRT_DT": start_date,  # 조회시작일 (YYYYMMDD)
        "ORD_END_DT": end_date,    # 조회종료일 (YYYYMMDD)
        "SLL_BUY_DVSN_CD": "00",   # 매도매수구분 (00:전체, 01:매도, 02:매수)
        "CCLD_NCCS_DVSN": "00",    # 체결미체결구분 (00:전체, 01:체결, 02:미체결)
        "OVRS_EXCG_CD": "%",       # 해외거래소코드 (%: 전체)
        "SORT_SQN": "DS",          # 정렬순서 (DS:주문순, AS:주문역순)
        "ORD_DT": "",              # 주문일자 (공란)
        "ORD_GNO_BRNO": "",        # 주문채번지점번호 (공란)
        "ODNO": "",                # 주문번호 (공란)
        "CTX_AREA_FK200": "",      # 연속조회키
        "CTX_AREA_NK200": ""       # 연속조회키
    }
    
    res = _request_api('GET', f"{URL_BASE}/uapi/overseas-stock/v1/trading/inquire-ccnl", headers, params=params)
    
    if res.status_code == 200:
        data = res.json()
        output_list = []
        
        # 문서상 응답 리스트 키는 'output'
        if 'output' in data:
            for item in data['output']:
                # FT_CCLD_QTY (체결수량)이 0보다 큰 것만 추출 (미체결 주문 제외)
                # 문서상 필드명: ft_ccld_qty (체결수량), ft_ccld_unpr3 (체결단가)
                ccld_qty = float(item.get('ft_ccld_qty', 0))
                
                if ccld_qty > 0:
                    # Dashboard.py가 이해하는 포맷으로 변환
                    mapped_item = {
                        'dt': item['ord_dt'],           # 주문일자
                        'pdno': item['pdno'],           # 종목코드
                        'prdt_name': item['prdt_name'], # 종목명
                        'sll_buy_dvsn_cd': item['sll_buy_dvsn_cd'], # 01:매도, 02:매수
                        'ccld_qty': str(int(ccld_qty)),
                        'ft_ccld_unpr3': item.get('ft_ccld_unpr3', '0') # 체결단가
                    }
                    output_list.append(mapped_item)
        
        # Dashboard.py 호환성을 위해 output1 키로 감싸서 반환
        return {'output1': output_list}
            
    return None
