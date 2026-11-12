# -*- coding: utf-8 -*-
"""Read-only Binance USD-M EQUITY PERPETUAL market candles.
This is NOT direct stock ownership and not the same as Binance Stocks (24/5).
Only confirmed stock underlying tickers may be mapped, never an arbitrary
crypto token with a colliding ticker. API calls are GET only, no credentials.
"""
from __future__ import annotations
import json
import time
import urllib.request
import urllib.error
import urllib.parse

BASE = 'https://fapi.binance.com'
# Officially announced equity-linked perpetual pairs. Still require current
# exchangeInfo status=TRADING confirmation; delistings produce unavailable.
EQUITY_PERPS = {
    'GOOGL':'GOOGLUSDT','AMZN':'AMZNUSDT','META':'METAUSDT',
    'NVDA':'NVDAUSDT','MSFT':'MSFTUSDT','V':'VUSDT','MU':'MUUSDT',
    'AMD':'AMDUSDT','UBER':'UBERUSDT','TSLA':'TSLAUSDT',
    'MSTR':'MSTRUSDT','CRCL':'CRCLUSDT','COIN':'COINUSDT',
    'PLTR':'PLTRUSDT','SNDK':'SNDKUSDT','AVGO':'AVGOUSDT',
    'INTC':'INTCUSDT','ORCL':'ORCLUSDT','HD':'HDUSDT',
    'CSCO':'CSCOUSDT','DIS':'DISUSDT','WMT':'WMTUSDT',
    'JPM':'JPMUSDT','BRK.B':'BRKBUSDT','QCOM':'QCOMUSDT',
    'MRVL':'MRVLUSDT','HPE':'HPEUSDT',
}
SOURCE = {'15m':'15m','30m':'30m','1h':'1h','4h':'4h','1d':'1d','1wk':'1w','1mo':'1M'}
TICK_MS = {'15m':900_000,'30m':1_800_000,'1h':3_600_000,'4h':14_400_000,
           '1d':86_400_000,'1wk':604_800_000,'1mo':31*86_400_000}

class MarketDataError(RuntimeError): pass
class RestrictedMarketError(MarketDataError): pass

def request_json(path, query=None, timeout=15):
    url=BASE+path+(('?'+urllib.parse.urlencode(query)) if query else '')
    req=urllib.request.Request(url, headers={'User-Agent':'Whale50/4.0 read-only research','Accept':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read(2_500_000))
    except urllib.error.HTTPError as ex:
        if ex.code==451:
            raise RestrictedMarketError('HTTP 451: Binance 주식 선물 API 지역/법률 접근 제한') from ex
        raise MarketDataError(f'바이낸스 응답 HTTP {ex.code}') from ex

def active_equity_pairs():
    data=request_json('/fapi/v1/exchangeInfo',timeout=18)
    active={row.get('symbol') for row in data.get('symbols',[])
            if row.get('status')=='TRADING' and row.get('contractType')=='PERPETUAL'}
    return {ticker:pair for ticker,pair in EQUITY_PERPS.items() if pair in active}

def get_candles(pair, frame, limit=500, now_ms=None):
    if pair not in set(EQUITY_PERPS.values()):
        raise MarketDataError('확인된 주식 연계 선물 거래쌍이 아닙니다')
    if frame not in SOURCE:raise MarketDataError('지원하지 않는 봉')
    received=request_json('/fapi/v1/klines',{'symbol':pair,'interval':SOURCE[frame],'limit':limit})
    now_ms=now_ms or int(time.time()*1000)
    bars=[]
    for item in received:
        if len(item)<7:continue
        t,o,h,l,c,v,close_ms=item[:7]
        if int(close_ms)>now_ms-10_000:continue # only completely closed candle
        o,h,l,c,v=map(float,(o,h,l,c,v))
        if min(o,h,l,c)<=0:continue
        bars.append({'t':int(t)//1000,'o':o,'h':h,'l':l,'c':c,'v':v})
    if not bars:raise MarketDataError('완료된 24시간 주식 선물봉이 없습니다')
    return sorted({b['t']:b for b in bars}.values(),key=lambda b:b['t'])
