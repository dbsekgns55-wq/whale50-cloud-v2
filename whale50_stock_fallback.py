# -*- coding: utf-8 -*-
"""Public Yahoo stock candles -- REGULAR US equity sessions, NOT 24/7 futures.
Uses no API credentials. This is an honest fallback when Binance denies access.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo
import json
import time
import urllib.request

# Windows Python frequently lacks the IANA tz database. Compute US Eastern DST
# using the current US rules as a standard-library-only fallback.
try:
    NY=ZoneInfo('America/New_York')
except Exception:
    NY=None

def _new_york_datetime(timestamp):
    utc=datetime.fromtimestamp(timestamp,timezone.utc)
    if NY is not None:return utc.astimezone(NY)
    year=utc.year
    march=datetime(year,3,1,tzinfo=timezone.utc)
    first_sun_march=1+(6-march.weekday())%7
    second_sun_march=first_sun_march+7
    november=datetime(year,11,1,tzinfo=timezone.utc)
    first_sun_nov=1+(6-november.weekday())%7
    start=datetime(year,3,second_sun_march,7,tzinfo=timezone.utc)
    end=datetime(year,11,first_sun_nov,6,tzinfo=timezone.utc)
    offset=-4 if start<=utc<end else -5
    return utc.astimezone(timezone(timedelta(hours=offset)))
# Yahoo history has intraday limits. Historical coverage varies by ticker.
RANGES={'15m':('15m','1mo'),'30m':('30m','1mo'),'1h':('60m','6mo'),
        '4h':('60m','6mo'),'1d':('1d','5y'),'1wk':('1wk','10y'),'1mo':('1mo','10y')}
SECONDS={'15m':900,'30m':1800,'1h':3600,'4h':14400}

class StockDataError(RuntimeError):pass

def _fetch(ticker,interval,period,now=None):
    now=time.time() if now is None else now
    errors=[]
    for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
        url=f'https://{host}/v8/finance/chart/{quote(ticker,safe="")}?'+urlencode({
            'range':period,'interval':interval,'includePrePost':'false'})
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                result=json.loads(response.read(5_000_000))['chart']['result'][0]
            timestamps=result.get('timestamp') or []
            quote_data=result['indicators']['quote'][0]
            bars=[]
            for i,t in enumerate(timestamps):
                try:
                    o,h,l,c,v=[quote_data.get(k,[])[i] for k in ('open','high','low','close','volume')]
                    if any(x is None for x in (o,h,l,c)):continue
                    o,h,l,c=map(float,(o,h,l,c))
                    if min(o,h,l,c)<=0:continue
                    bars.append({'t':int(t),'o':o,'h':h,'l':l,'c':c,'v':float(v or 0)})
                except (IndexError,TypeError,ValueError):continue
            if interval in ('15m','30m','60m'):
                d={'15m':900,'30m':1800,'60m':3600}[interval]
                bars=[x for x in bars if x['t']+d<now-30]
            else:
                dt_now=_new_york_datetime(now)
                def completed(x):
                    date=_new_york_datetime(x['t'])
                    if interval=='1d':
                        return date.date()!=dt_now.date() or (dt_now.hour,dt_now.minute)>=(16,10)
                    if interval=='1wk':
                        return (date.isocalendar().year,date.isocalendar().week)!=(dt_now.isocalendar().year,dt_now.isocalendar().week)
                    return (date.year,date.month)!=(dt_now.year,dt_now.month)
                bars=[x for x in bars if completed(x)]
            if not bars:raise StockDataError('완료된 정규장 시세 없음')
            return bars
        except Exception as e:errors.append(f'{host}: {type(e).__name__} {e}')
    raise StockDataError('정규장 대체 시세 조회 실패: '+'; '.join(errors)[:240])

def _aggregate(items,units):
    # Incomplete groups are excluded. Never merge across local trading days.
    groups=[];chunk=[];current_day=None
    for bar in items:
        day=_new_york_datetime(bar['t']).date()
        if day!=current_day:chunk=[];current_day=day
        chunk.append(bar)
        if len(chunk)==units:
            groups.append({'t':chunk[0]['t'],'o':chunk[0]['o'],
                           'h':max(x['h'] for x in chunk),'l':min(x['l'] for x in chunk),
                           'c':chunk[-1]['c'],'v':sum(x['v'] for x in chunk)})
            chunk=[]
    return groups

def get_candles(ticker,frame,now=None):
    if frame not in RANGES:raise StockDataError('지원하지 않는 시간봉')
    if frame=='4h':return _aggregate(_fetch(ticker,'60m','6mo',now),4)
    if frame=='30m':return _aggregate(_fetch(ticker,'15m','1mo',now),2)
    interval,period=RANGES[frame]
    return _fetch(ticker,interval,period,now)
