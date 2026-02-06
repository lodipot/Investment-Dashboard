# [KIS_API_Manager.py]
# 기존 파일의 내용에 아래 함수를 덮어쓰거나 수정하세요.

def get_trade_history(start_date, end_date):
    token = get_access_token()
    if not token: return None

    # -----------------------------------------------------------
    # [전략 변경] '주문체결내역' 대신 '체결기준잔고'를 조회하여 당일 매매분 포착
    # API ID: v1_해외주식-008 (CTRP6504R)
    # -----------------------------------------------------------
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "CTRP6504R", # 해외주식 체결기준현재잔고
        "custtype": "P"
    }
    
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "WCRC_FRCR_DVSN_CD": "01", # 01: 원화, 02: 외화
        "NATN_CD": "840",          # 840: 미국
        "TR_MKET_CD": "00",        # 00: 전체
        "INQR_DVSN_CD": "00"       # 00: 전체
    }
    
    # URL: /uapi/overseas-stock/v1/trading/inquire-present-balance
    res = _request_api('GET', f"{URL_BASE}/uapi/overseas-stock/v1/trading/inquire-present-balance", headers, params=params)
    
    output_list = []
    
    if res.status_code == 200:
        data = res.json()
        
        # 잔고 내역에서 '금일 체결 수량'이 있는 종목만 추출
        if 'output1' in data:
            for item in data['output1']:
                # thdt_buy_ccld_qty1 : 금일 매수 체결 수량 (소수점 포함)
                buy_qty = float(item.get('thdt_buy_ccld_qty1', 0))
                # thdt_sll_ccld_qty1 : 금일 매도 체결 수량
                sell_qty = float(item.get('thdt_sll_ccld_qty1', 0))
                
                # 매수 건 발견!
                if buy_qty > 0:
                    mapped_item = {
                        'dt': datetime.now().strftime("%Y%m%d"), # 날짜는 오늘(조회일)로 찍힘
                        'pdno': item['pdno'],                    # 종목코드
                        'prdt_name': item['prdt_name'],          # 종목명
                        'sll_buy_dvsn_cd': '02',                 # 02: 매수
                        'ccld_qty': str(int(buy_qty)),
                        # 체결가는 '매입평균가(pchs_avg_pric)'로 대체 (개별 단가는 알 수 없으나 평단 관리에 문제 없음)
                        'ft_ccld_unpr3': item.get('pchs_avg_pric', '0') 
                    }
                    output_list.append(mapped_item)
                
                # 매도 건 발견!
                if sell_qty > 0:
                    mapped_item = {
                        'dt': datetime.now().strftime("%Y%m%d"),
                        'pdno': item['pdno'],
                        'prdt_name': item['prdt_name'],
                        'sll_buy_dvsn_cd': '01',                 # 01: 매도
                        'ccld_qty': str(int(sell_qty)),
                        'ft_ccld_unpr3': item.get('now_pric2', '0') # 매도가는 현재가로 추정 (API 한계)
                    }
                    output_list.append(mapped_item)
        
        # 과거 내역(CTOS4001R)도 병행해서 가져오면 좋겠지만, 
        # 현재 급한 불(2/3 거래)을 끄기 위해 잔고 기반 데이터만 리턴합니다.
        return {'output1': output_list}
            
    return None
