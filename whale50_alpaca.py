# -*- coding: utf-8 -*-
"""Read-only Alpaca US stock market-data client (no trading endpoint).

Alpaca IEX: one exchange, not consolidated SIP, not guaranteed overnight data.
Each timeframe is fetched DIRECTLY and completed bars only. Do not use this
as a 24/7 equity-futures price; missing session intervals are left missing.
Credentials come from GitHub Actions environment variables or ignored local
`data/alpaca_private.json`. They are never sent to the website.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json, os, time

BASE='https://data.alpaca.markets'
FRAMES={'15m':('15Min',26), '30m':('30Min',45), '1h':('1Hour',120),
        '4h':('4Hour',260), '1d':('1Day',1100), '1wk':('1Week',1900), '1mo':('1Month',4000)}
INTRADAY_SECONDS={'15m':900,'30m':1800,'1h':3600,'4h':14400}
ALLOWED_FEEDS={'iex','sip'}
class AlpacaDataError(RuntimeError):pass


def credentials():
    key=os.getenv('WHALE50_ALPACA_KEY_ID') or os.getenv('APCA_API_KEY_ID') or ''
    secret=os.getenv('WHALE50_ALPACA_SECRET_KEY') or os.getenv('APCA_API_SECRET_KEY') or ''
    if key and secret:return key.strip(),secret.strip()
    auth=Path(__file__).resolve().parent/'data'/'alpaca_private.json'
    try:
        data=json.loads(auth.read_text(encoding='utf-8'))
        return str(data.get('key_id','')).strip(),str(data.get('secret_key','')).strip()
    except (OSError,ValueError,TypeError):return '', ''


def configured():
    key,secret=credentials()
    return bool(key and secret)


def feed():
    value=os.getenv('WHALE50_ALPACA_FEED','iex').lower().strip()
    if value not in ALLOWED_FEEDS:
        raise AlpacaDataError('Alpaca feed는 iex 또는 sip만 지원합니다')
    return value


def request_json(path, params, timeout=20):
    key,secret=credentials()
    if not key or not secret:
        raise AlpacaDataError('Alpaca API 키 미설정: GitHub Secrets 또는 로컬 키 파일 필요')
    url=BASE+path+'?'+urlencode(params)
    headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret,
             'Accept':'application/json','User-Agent':'Whale50/4.4 research-only'}
    req=Request(url,headers=headers)
    try:
        with urlopen(req,timeout=timeout) as res:
            return json.loads(res.read(4_000_000))
    except HTTPError as exc:
        if exc.code in (401,403):
            raise AlpacaDataError(f'Alpaca HTTP {exc.code}: API 키 또는 {feed()} 시세 권한 확인 필요') from exc
        if exc.code==429:
            raise AlpacaDataError('Alpaca HTTP 429: 조회 속도 제한, 다음 실행에서 재시도') from exc
        raise AlpacaDataError(f'Alpaca HTTP {exc.code}') from exc
    except (URLError, TimeoutError) as exc:
        raise AlpacaDataError('Alpaca 시세 서버 연결 오류') from exc


def _iso(ts):
    return datetime.fromtimestamp(ts,timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def _complete(ts,frame,now):
    current=datetime.fromtimestamp(now,timezone.utc)
    t=datetime.fromtimestamp(ts,timezone.utc)
    if frame in INTRADAY_SECONDS:
        return ts+INTRADAY_SECONDS[frame] <= now-90
    if frame=='1d':
        # Daily bars may be changing throughout the current US trading day.
        try:
            from zoneinfo import ZoneInfo
            zone=ZoneInfo('America/New_York')
        except Exception:
            # Conservative fallback on Windows without tzdata: use UTC date.
            zone=timezone.utc
        return t.astimezone(zone).date()<current.astimezone(zone).date()
    if frame=='1wk':
        return t.isocalendar()[:2] < current.isocalendar()[:2]
    if frame=='1mo':
        return (t.year,t.month)<(current.year,current.month)
    return False


def get_candles(ticker,frame,now=None):
    if frame not in FRAMES:raise AlpacaDataError('지원하지 않는 시간봉')
    if not ticker or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in ticker.upper()):
        raise AlpacaDataError('잘못된 주식 티커')
    now=float(time.time() if now is None else now)
    tf,days=FRAMES[frame]
    start=_iso(now-days*86400)
    end=_iso(now)
    params={'timeframe':tf,'start':start,'end':end,'feed':feed(),
            'adjustment':'raw','limit':1000,'sort':'asc'}
    bars=[];pages=0
    while True:
        result=request_json('/v2/stocks/'+quote(ticker.upper(),safe='')+'/bars',params)
        entries=result.get('bars') or []
        for b in entries:
            try:
                t=int(datetime.fromisoformat(b['t'].replace('Z','+00:00')).timestamp())
                o,h,l,c,v=(float(b[k]) for k in ('o','h','l','c','v'))
                if min(o,h,l,c)<=0 or v<0 or not _complete(t,frame,now):continue
                bars.append({'t':t,'o':o,'h':h,'l':l,'c':c,'v':v})
            except (TypeError,ValueError,KeyError,OverflowError):continue
        token=result.get('next_page_token')
        pages+=1
        if not token or pages>=8:break
        params['page_token']=token
    if not bars:raise AlpacaDataError('Alpaca에서 완료된 '+frame+' IEX/SIP 봉을 받지 못함 (휴장 또는 데이터 부족 가능)')
    return sorted({b['t']:b for b in bars}.values(),key=lambda b:b['t'])[-4500:]
