# -*- coding: utf-8 -*-
"""Whale50 equity time-frame signals. Indicator scores, NOT calibrated odds.

Signal source: Binance USD-M stock equity perpetual 24/7 public OHLCV; no live orders.
No external Python packages required.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import json
import math
import statistics
import time
import urllib.request

# ETF trusts are intentionally not company-merged.
ETF_TICKERS={'SPY','IVV','QQQ','IWM','AGG','TLT','VOO','VTI','DIA','SCHD','JEPI','XLF','XLK'}
ETF_NAMES=('ISHARES','SPDR','ETF','EXCHANGE TRADED','INVESCO QQQ','VANGUARD INDEX',
           'INDEX FDS','INDEX FUND','TRUST SERIES','SPDR S&P','PROSHARES','SELECT SECTOR SPDR')
CLASS_GROUPS={
    '02079K107':('ALPHABET','GOOGL','ALPHABET INC (GOOG+GOOGL)'),
    '02079K305':('ALPHABET','GOOGL','ALPHABET INC (GOOG+GOOGL)'),
    '084670702':('BERKSHIRE','BRK.B','BERKSHIRE HATHAWAY (A+B)'),
    '084670108':('BERKSHIRE','BRK.B','BERKSHIRE HATHAWAY (A+B)'),
}
FRAMES=['15m','30m','1h','4h','1d','1wk','1mo']
SOURCE={'15m':('15m','500'),'30m':('30m','500'),'1h':('1h','500'),
        '4h':('4h','500'),'1d':('1d','500'),'1wk':('1wk','500'),'1mo':('1mo','500')}
SIGNAL_INTERVAL_SECONDS=600   # cached source refresh >=10 minutes


def is_etf(r):
    name=str(r.get('name','')).upper()
    return r.get('ticker','') in ETF_TICKERS or any(k in name for k in ETF_NAMES)


def group_company_rankings(rows):
    """Merge known voting classes, dedup managers by CIK across share classes.

    Others remain CUSIP-specific to avoid erroneous issuer-name merging.
    """
    merged={}
    for r in rows:
        cusip=r.get('cusip','')
        grouping=CLASS_GROUPS.get(cusip)
        key=grouping[0] if grouping else cusip
        if not key: continue
        out=merged.get(key)
        if out is None:
            out={'company_key':key,'ticker':grouping[1] if grouping else r.get('ticker',''),
                 'name':grouping[2] if grouping else r.get('name',''),
                 'cusip':cusip,'cusips':[],'tickers':[],
                 'buy_usd':0,'sell_usd':0,'hold_usd':0,'buyers':0,'holders':0,'new_buyers':0,
                 'periods':[],'buying_funds':[],'positions':[],'price':r.get('price')}
            merged[key]=out
        out['cusips'].append(cusip)
        if r.get('ticker') and r['ticker'] not in out['tickers']:out['tickers'].append(r['ticker'])
        for k in ('buy_usd','sell_usd','hold_usd'):out[k]+=r.get(k,0)
        out['buying_funds']+=r.get('buying_funds',[])
        out['positions']+=r.get('positions',[])
        out['periods']=sorted(set(out['periods']+r.get('periods',[])),reverse=True)
        if r.get('price') and (not out.get('price') or r.get('ticker')==out['ticker']): out['price']=r['price']
    result=[]
    for r in merged.values():
        r['buyers']=len({x['cik'] for x in r['buying_funds']})
        r['holders']=len({x['cik'] for x in r['positions']})
        r['new_buyers']=len({x['cik'] for x in r['buying_funds'] if x.get('action')=='신규'})
        r['buying_funds'].sort(key=lambda x:-x['estimated_change_usd'])
        r['cusip']=' + '.join(dict.fromkeys(r['cusips']))
        result.append(r)
    return result


def fetch_ohlcv(ticker, src_interval, period):
    """Read only Binance equity perpetual klines (NOT Yahoo stock bars)."""
    import whale50_binance as market
    pair=market.EQUITY_PERPS.get(ticker)
    if not pair:raise market.MarketDataError('해당 미국 주식의 바이낸스 주식 선물 미확인')
    return market.get_candles(pair,src_interval)


def merge_bars(old, new, keep=4500):
    """Preserve market candles accumulated from earlier collections."""
    return sorted({int(b['t']):b for b in list(old)+list(new)}.values(), key=lambda b:b['t'])[-keep:]


def resample(bars, size, reset_daily=False):
    """Aggregate *complete* consecutive source bars. 4h=4 completed hourly sessions.

    US equities do not have a literal 24-hour candle; 1d is one trading day.
    """
    groups=[]; chunk=[]; old_day=None
    for b in bars:
        day=datetime.fromtimestamp(b['t'],timezone.utc).strftime('%Y-%m-%d')
        if reset_daily and day!=old_day:chunk=[]
        old_day=day
        chunk.append(b)
        if len(chunk)==size:
            groups.append({'t':chunk[0]['t'],'o':chunk[0]['o'],'h':max(x['h'] for x in chunk),
                           'l':min(x['l'] for x in chunk),'c':chunk[-1]['c'],
                           'v':sum(x['v'] for x in chunk)})
            chunk=[]
    return groups


def ema(values,span):
    a=2/(span+1)
    e=values[0]
    for v in values[1:]:e=a*v+(1-a)*e
    return e


def rsi(values,period=14):
    moves=[values[i]-values[i-1] for i in range(1,len(values))]
    tail=moves[-period:]
    up=sum(max(x,0) for x in tail)/period
    dn=sum(max(-x,0) for x in tail)/period
    if up==0 and dn==0:return 50.
    if dn==0:return 100.
    return 100-100/(1+up/dn)


def ichimoku(bars, *, allow_partial=False):
    """Ichimoku 9/26/52 and 26-bar shift, strictly completed bars only.

    78 bars are needed for the full *currently visible* displaced cloud.
    With 52--77 monthly bars, only the current Tenkan/Kijun, projected
    cloud and Chikou comparisons are computable. The current cloud is
    unavailable, and its score is explicitly omitted (never fabricated).
    """
    n=len(bars)
    partial=52 <= n < 78 and allow_partial
    if n<78 and not partial:
        return {'status':'insufficient','reason':'현재 구름대 포함 일목균형표는 완료봉 78개 필요'}

    def midpoint(seq):
        return (max(x['h'] for x in seq)+min(x['l'] for x in seq))/2

    tenkan=midpoint(bars[-9:])
    kijun=midpoint(bars[-26:])
    # Spans computed now are displayed 26 bars in the FUTURE (projection,
    # not a forecast). They are not the cloud used for today's price position.
    projected_a=(tenkan+kijun)/2
    projected_b=midpoint(bars[-52:])
    # Index -27 corresponds to the last bar 26 periods before the latest.
    past=bars[:-26]
    close=float(bars[-1]['c'])
    if partial:
        # 52--77 bars cannot support Senkou B at t-26 (needs 52 earlier bars).
        visible_a=visible_b=None
        cloud_position='현재 구름 계산 불가';cloud_score=0
    else:
        visible_a=(midpoint(past[-9:])+midpoint(past[-26:]))/2
        visible_b=midpoint(past[-52:])
        if close>max(visible_a,visible_b):
            cloud_position='구름 위';cloud_score=10
        elif close<min(visible_a,visible_b):
            cloud_position='구름 아래';cloud_score=-10
        else:
            cloud_position='구름 안';cloud_score=0
    if tenkan>kijun:tk='전환선 우세';tk_score=5
    elif tenkan<kijun:tk='기준선 우세';tk_score=-5
    else:tk='전환·기준 동률';tk_score=0
    historical=bars[-27]
    if close>historical['h']:chikou='과거 가격 위';chikou_score=3
    elif close<historical['l']:chikou='과거 가격 아래';chikou_score=-3
    else:chikou='과거 가격 범위 안';chikou_score=0
    if projected_a>projected_b:
        projected='양운';projection_score=2
    elif projected_a<projected_b:
        projected='음운';projection_score=-2
    else:
        projected='중립';projection_score=0
    def price(v):return round(v,4) if v is not None else None
    return {'status':'partial' if partial else 'ok','cloud_position':cloud_position,
            'cloud_top':price(max(visible_a,visible_b)) if not partial else None,
            'cloud_bottom':price(min(visible_a,visible_b)) if not partial else None,
            'tenkan':price(tenkan),'kijun':price(kijun),'tk_status':tk,
            'chikou_status':chikou,'future_cloud':projected,
            'span_a_now':price(visible_a),'span_b_now':price(visible_b),
            'projected_span_a':price(projected_a),'projected_span_b':price(projected_b),
            'score':cloud_score+tk_score+chikou_score+projection_score,
            'shift_bars':26,
            'note':f'완료봉 {n}개: 전환선/기준선/후행스팬/선행구름 계산; 현재 구름대는 78개부터' if partial else ''}


def indicator(bars,frame):
    """Indicator directional balance (not forecast odds or proven win rate)."""
    minimum=52 if frame=='1mo' else 78
    if len(bars)<minimum:
        return {'status':'insufficient','reason':f'완료봉 {len(bars)}개 / 분석에 최소 {minimum}개 필요'}
    c=[float(x['c']) for x in bars]
    e12=ema(c[-160:],12)
    e26=ema(c[-160:],26)
    e20=ema(c[-160:],20)
    val_rsi=rsi(c)
    # RSI 12, EMA12/26 10, EMA20 10, 5-bar momentum 8, Ichimoku 20.
    # Ichimoku's 20 points = visible cloud(10) + Tenkan/Kijun(5)
    # + Chikou confirmation(3) + projected cloud color(2).
    recent_changes=[abs(c[i]/c[i-1]-1) for i in range(max(1,len(c)-21),len(c)) if c[i-1]]
    movement=max(0.00001,statistics.mean(recent_changes or [0.00001]))
    momentum=(c[-1]/c[-6]-1) if c[-6] else 0
    trend=10 if e12>e26 else -10 if e12<e26 else 0.
    level=10 if c[-1]>e20 else -10 if c[-1]<e20 else 0.
    strength=12*max(-1.,min(1.,(val_rsi-50.)/30.))
    impulse=8*max(-1.,min(1.,momentum/(movement*4)))
    ichi=ichimoku(bars,allow_partial=(frame=='1mo'))
    # No imputation or boost for the 10-point current-cloud component missing
    # from partial monthly history; comparison with full 78+ bar signals is limited.
    long=round(max(15.,min(85.,50+trend+level+strength+impulse+ichi['score'])))
    short=100-long
    if long>=60:side='롱 우세'
    elif long<=40:side='숏 우세'
    else:side='관망'
    last=datetime.fromtimestamp(bars[-1]['t'],timezone.utc).isoformat(timespec='minutes')
    return {'status':'ok','frame':frame,'long':long,'short':short,'side':side,
            'rsi':round(val_rsi,1),'last_close':round(c[-1],4),
            'last_bar_utc':last,'bar_count':len(bars),'ichimoku':ichi,
            'partial':ichi['status']=='partial',
            'quality_note':ichi.get('note','')}


def build_signals(sources):
    """Receive interval->list OHLCV bars and score all 7 timeframes."""
    input_bars={key:list(value) for key,value in sources.items()}
    return {k:indicator(input_bars.get(k,[]),k) for k in FRAMES}
