# -*- coding: utf-8 -*-
"""Whale50 - SEC EDGAR 13F holdings watcher. Python standard library only."""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import gzip
import io
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import whale50_signals as sig
import whale50_binance as market
import whale50_stock_fallback as stock
import whale50_alpaca as alpaca
import whale50_validation as validation

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
CONFIG = ROOT / 'config.json'
DB_PATH = DATA / 'whale50.sqlite3'
MANAGER_PATH = ROOT / 'managers.json'
PORT = 8765
SEC_GAP = 0.45  # <= 2.3 requests/sec, comfortably below SEC's 10/sec max.
TICKERS = {
 '037833100':'AAPL','594918104':'MSFT','023135106':'AMZN','67066G104':'NVDA',
 '02079K107':'GOOG','02079K305':'GOOGL','30303M102':'META','874039100':'TSM',
 '92826C839':'V','57636Q104':'MA','084670702':'BRK.B','084670108':'BRK.A',
 '78462F103':'SPY','464287200':'IVV','46090E103':'QQQ',
 '060505104':'BAC','025816109':'AXP','191216100':'KO','166764100':'CVX',
 '88160R101':'TSLA','007903107':'AMD','595112103':'MU','68389X105':'ORCL',
 '742718109':'PG','437076102':'HD','532457108':'LLY','11135F101':'AVGO',
 '458140100':'INTC','64110L106':'NFLX','931142103':'WMT','46625H100':'JPM',
 '79466L302':'CRM','722304102':'PDD','69608A108':'PLTR','90353T100':'UBER',
 '149123101':'CAT','136375102':'CNI','92537N108':'VRT','032654105':'ADI',
 '82509L107':'SHOP','58733R102':'MELI','040413106':'ANET','88339J105':'TTD',
 '21036P108':'STZ','125523100':'CI','88579Y101':'MMM','00724F101':'ADBE',
 '254687106':'DIS','464287655':'IWM','464287226':'AGG', '40412C101':'HCA',
 '278642103':'EBAY','872540109':'TJX','654106103':'NKE',
 '09857L108':'BKNG','12572Q105':'CME','20030N101':'CMCSA',
 '92826C839':'V','40412C101':'HCA'
}

MANAGERS = json.loads(MANAGER_PATH.read_text(encoding='utf-8'))
assert len(MANAGERS) == 50 and len({x['cik'] for x in MANAGERS}) == 50
lock = threading.RLock()
job = {'running': False, 'started': '', 'finished':'', 'done':0,'total':50,'current':'','errors':0,'message':''}
price_job = {'running':False,'updated':'','errors':0,'message':'','done':0,'total':0}
signal_job = {'running':False,'updated':'','errors':0,'message':'','done':0,'total':0,'current':''}
rate_lock = threading.Lock()
_last_request = 0.0


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def load_config():
    try:
        c = json.loads(CONFIG.read_text(encoding='utf-8'))
        return {'email':str(c.get('email','')).strip() or __import__('os').environ.get('WHALE50_SEC_EMAIL',''), 'contact_name':str(c.get('contact_name','개인 투자 연구')).strip() or '개인 투자 연구'}
    except (FileNotFoundError, ValueError):
        return {'email':__import__('os').environ.get('WHALE50_SEC_EMAIL',''),'contact_name':'Whale50 Public Research'}


def save_config(c):
    CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8')


def db_open():
    DATA.mkdir(exist_ok=True)
    con=sqlite3.connect(DB_PATH, timeout=25)
    con.execute('PRAGMA busy_timeout=25000')
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('''CREATE TABLE IF NOT EXISTS filings (
        cik TEXT NOT NULL, period TEXT NOT NULL, accession TEXT NOT NULL,
        filed TEXT NOT NULL, source TEXT NOT NULL, rows TEXT NOT NULL,
        fetched TEXT NOT NULL, PRIMARY KEY (cik,period))''')
    con.execute('''CREATE TABLE IF NOT EXISTS checks (
        cik TEXT PRIMARY KEY, checked TEXT, error TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS prices (
        ticker TEXT PRIMARY KEY, bars TEXT NOT NULL, checked TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS market_selection (
        ticker TEXT PRIMARY KEY, provider TEXT NOT NULL, pair TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '', checked TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS signal_bars (
        ticker TEXT NOT NULL, interval TEXT NOT NULL, bars TEXT NOT NULL,
        checked TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', PRIMARY KEY(ticker,interval))''')
    con.commit()
    return con


def localname(tag):
    return tag.rsplit('}',1)[-1].lower()


def first_text(root, field):
    for x in root.iter():
        if localname(x.tag) == field.lower():
            return (x.text or '').strip()
    return ''


def parse_infotable(payload):
    """Parse both namespaced and un-namespaced EDGAR information tables."""
    root=ET.fromstring(payload)
    if localname(root.tag) != 'informationtable':
        raise ValueError('13F INFORMATION TABLE XML이 아닙니다')
    holdings={}
    for entry in root.iter():
        if localname(entry.tag) != 'infotable':
            continue
        issuer=first_text(entry,'nameOfIssuer')
        cusip=first_text(entry,'cusip').upper().replace(' ','')
        stocktype=first_text(entry,'sshPrnamtType').upper()
        putcall=first_text(entry,'putCall').upper()
        try:
            shares=int(float(first_text(entry,'sshPrnamt').replace(',','')))
            value=float(first_text(entry,'value').replace(',',''))
        except ValueError:
            continue
        if not cusip or not issuer or stocktype != 'SH' or shares < 0 or value < 0:
            continue
        key=(cusip,putcall)
        if key in holdings:
            holdings[key]['shares']+=shares
            holdings[key]['value']+=value
        else:
            holdings[key]={'cusip':cusip,'issuer':issuer,'security_class':first_text(entry,'titleOfClass'),
                           'shares':shares,'value':value,'option':putcall}
    if not holdings:
        raise ValueError('주식 보유 항목이 없습니다 (공시 형식 확인 필요)')
    return list(holdings.values())


def listed_reports(submissions):
    """Use original 13F-HR statements only; amended filings can be partial additions."""
    recent=submissions.get('filings',{}).get('recent',{})
    n=len(recent.get('form',[]))
    candidates=[]
    for i in range(n):
        if recent['form'][i] != '13F-HR':
            continue
        acc=recent['accessionNumber'][i]
        rep=recent.get('reportDate',[])
        rd=rep[i] if i<len(rep) else ''
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',rd):
            continue
        candidates.append({'period':rd,'accession':acc,'filed':recent['filingDate'][i]})
    by_period={}
    for filing in sorted(candidates,key=lambda z:(z['period'],z['filed']),reverse=True):
        if filing['period'] not in by_period:
            by_period[filing['period']]=filing
    return sorted(by_period.values(),key=lambda z:z['period'],reverse=True)[:3]


def sec_get(url, user_agent):
    global _last_request
    for attempt in range(3):
        with rate_lock:
            delay=SEC_GAP-(time.monotonic()-_last_request)
            if delay > 0: time.sleep(delay)
            _last_request=time.monotonic()
        req=urllib.request.Request(url,headers={'User-Agent':user_agent,'Accept':'application/json, application/xml, text/xml, */*'})
        try:
            with urllib.request.urlopen(req,timeout=28) as resp:
                blob=resp.read(32_000_000)
                if resp.headers.get('Content-Encoding','').lower()=='gzip':
                    blob=gzip.decompress(blob)
                return blob
        except urllib.error.HTTPError as ex:
            if ex.code in (403,401):
                raise RuntimeError('SEC 요청이 차단되었습니다(HTTP %s). 정확한 이메일을 입력하고 잠시 후 재시도하세요.'%ex.code)
            if ex.code not in (429,500,502,503,504) or attempt==2: raise
        except (OSError,TimeoutError):
            if attempt==2: raise
        time.sleep(1.5*(attempt+1))
    raise RuntimeError('SEC 요청 재시도 실패')


def get_filings(cik, contact):
    url='https://data.sec.gov/submissions/CIK%s.json'%cik.zfill(10)
    return listed_reports(json.loads(sec_get(url,contact)))


def get_infotable(cik, filing, contact):
    acc=filing['accession'].replace('-','')
    base='https://www.sec.gov/Archives/edgar/data/%d/%s/'%(int(cik),acc)
    index=json.loads(sec_get(base+'index.json',contact))
    items=index.get('directory',{}).get('item',[])
    # Prefer explicit INFORMATION TABLE type, but many index.json entries have no type.
    xmlitems=[i for i in items if str(i.get('name','')).lower().endswith('.xml')]
    typed=[i for i in xmlitems if 'INFORMATION TABLE' in str(i.get('type','')).upper()]
    named=[i for i in xmlitems if re.search('info.?table|13f.?table|form13finf',i['name'],re.I)]
    others=[i for i in xmlitems if 'primary_doc' not in i['name'].lower() and 'primary' not in i['name'].lower()]
    others.sort(key=lambda x:int(x.get('size','0') or 0),reverse=True)
    seen=set()
    for candidate in typed+named+others:
        fname=candidate['name']
        if fname in seen: continue
        seen.add(fname)
        try:
            rows=parse_infotable(sec_get(base+fname,contact))
            return rows,base+'index.json'
        except (ValueError, ET.ParseError):
            continue
    raise ValueError('INFORMATION TABLE XML이 보이지 않습니다. SEC 공시 원문을 확인하세요.')


def _update_one(con, fund, contact):
    cik=fund['cik']
    filings=get_filings(cik,contact)
    if not filings:
        raise ValueError('13F-HR 원본 보유 공시가 없습니다 (13F-NT 여부 확인)')
    for filing in filings:
        row=con.execute('SELECT accession FROM filings WHERE cik=? AND period=?',(cik,filing['period'])).fetchone()
        if row and row[0]==filing['accession']:
            continue
        holdings,source=get_infotable(cik,filing,contact)
        con.execute('''INSERT OR REPLACE INTO filings (cik,period,accession,filed,source,rows,fetched)
                       VALUES (?,?,?,?,?,?,?)''',
                    (cik,filing['period'],filing['accession'],filing['filed'],source,
                     json.dumps(holdings,ensure_ascii=False),now_iso()))
        con.commit()
    con.execute('INSERT OR REPLACE INTO checks(cik,checked,error) VALUES(?,?,?)',(cik,now_iso(),''))
    con.commit()


def run_update(force=False):
    with lock:
        if job['running']: return False
        job.update(running=True,started=now_iso(),finished='',done=0,total=len(MANAGERS),current='',errors=0,message='SEC 공시 확인 중')
    conf=load_config()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',conf['email']):
        with lock: job.update(running=False,finished=now_iso(),message='설정에서 SEC 접속용 이메일을 먼저 입력해주세요')
        return False
    contact='%s %s'%(re.sub(r'[^a-zA-Z0-9 _.-]','',conf['contact_name']) or 'Independent Research',conf['email'])
    con=db_open()
    try:
        for idx,fund in enumerate(MANAGERS,1):
            with lock: job['current']=fund['name']
            try:
                _update_one(con,fund,contact)
            except Exception as ex:
                msg=str(ex)
                con.execute('INSERT OR REPLACE INTO checks(cik,checked,error) VALUES(?,?,?)',(fund['cik'],now_iso(),msg[:400]))
                con.commit()
                with lock: job['errors']+=1
            with lock: job['done']=idx
    finally:
        con.close()
        with lock: job.update(running=False,finished=now_iso(),current='',message='확인 완료')
    # Prices are secondary and optional; an outage must never invalidate filings.
    if __import__('os').environ.get('WHALE50_CLOUD')!='1':
        try: update_prices()
        except Exception as ex: print('시세 갱신 선택 기능 오류:',ex)
        try: run_signals_update('latest')
        except Exception as ex: print('7개 봉 분석 조회 오류:',ex)
    return True


def try_update_background():
    with lock:
        if job['running']: return False
    t=threading.Thread(target=run_update,daemon=True)
    t.start()
    return True


def maybe_automatic():
    # When the program is left open, poll once per day. A Windows scheduled task
    # is available to check while the dashboard is closed.
    while True:
        try:
            cfg=load_config()
            if cfg['email']:
                con=db_open()
                count=con.execute('SELECT COUNT(*) FROM checks WHERE checked >= ?',((dt.datetime.now().astimezone()-dt.timedelta(hours=22)).isoformat(),)).fetchone()[0]
                con.close()
                if count < len(MANAGERS) and not job['running']:
                    try_update_background()
        except Exception as ex:
            print('Auto check:',ex)
        time.sleep(3600)


def _snapshots(con):
    records=con.execute('SELECT cik,period,filed,source,rows FROM filings ORDER BY period DESC').fetchall()
    byfund=defaultdict(dict)
    for cik,period,filed,source,rows in records:
        byfund[cik][period]={'period':period,'filed':filed,'url':source,'holdings':json.loads(rows)}
    return byfund


def _rankings(byfund, selected_period):
    # Different managers may have different newest quarters; UI labels the mixed view explicitly.
    summary=defaultdict(lambda:{'buy_usd':0.,'sell_usd':0.,'hold_usd':0.,'buyers':set(),'holders':set(),
                                  'new_buyers':set(),'detail':[], 'positions':[], 'periods':set(), 'name':'','cusip':'','ticker':''})
    detail=[]; managers=[]
    for fund in MANAGERS:
        cik=fund['cik']; snapshots=byfund.get(cik,{})
        periods=sorted(snapshots,reverse=True)
        currperiod=(periods[0] if periods else None) if selected_period=='latest' else selected_period
        current=snapshots.get(currperiod)
        older=next((snapshots[p] for p in periods if p < currperiod),None) if current else None
        status={'name':fund['name'],'short':fund['short'],'cik':cik,'period':currperiod if current else None,
                'filed':current['filed'] if current else None,'source':current['url'] if current else '',
                'positions':len(current['holdings']) if current else 0,
                'comparison_period':older['period'] if older else None,'hold_usd':0.,'buy_usd':0.,'buys':0}
        if current:
            old_by_key={(r['cusip'],r['option']):r for r in older['holdings']} if older else {}
            current_keys={(r['cusip'],r['option']) for r in current['holdings']}
            for r in current['holdings']:
                if r['option'] or r['shares']<=0: # exclude PUT/CALL derivatives
                    continue
                cusip=r['cusip']; shares=int(r['shares']); value=float(r['value'])
                ticker=TICKERS.get(cusip,'')
                block=summary[cusip]
                block['cusip']=cusip; block['name']=r['issuer']; block['ticker']=ticker
                block['hold_usd']+=value; block['holders'].add(cik); block['periods'].add(currperiod)
                block['positions'].append({'cik':cik,'short':fund['short'],'value_usd':value,'period':currperiod,'filed':current['filed']})
                status['hold_usd']+=value
                prev=int(old_by_key.get((cusip,''),{}).get('shares',0)) if older else None
                if prev is not None:
                    delta=shares-prev
                    # NOT cash purchases: delta_shares * period-end unit value.
                    est=(abs(delta)*value/shares) if delta else 0.
                    item={'fund':fund['name'],'short':fund['short'],'cik':cik,'period':currperiod,
                          'previous_period':older['period'],'filed':current['filed'],'source':current['url'],
                          'name':r['issuer'],'ticker':ticker,'cusip':cusip,'shares':shares,'previous_shares':prev,
                          'delta_shares':delta,'value_usd':value,'estimated_change_usd':est,
                          'action':'신규' if prev==0 and delta>0 else '추가' if delta>0 else '축소' if delta<0 else '유지',
                          'change_pct':round(delta/prev*100,2) if prev>0 else None}
                    detail.append(item)
                    if delta>0:
                        block['buy_usd']+=est;block['buyers'].add(cik)
                        if prev==0:block['new_buyers'].add(cik)
                        block['detail'].append(item)
                        status['buy_usd']+=est; status['buys']+=1
                    elif delta<0:block['sell_usd']+=est
            # Full exits have no current filing row; value uses PRIOR quarter's valuation.
            if older:
                for key,previous in old_by_key.items():
                    if key in current_keys or previous['option'] or previous['shares']<=0:
                        continue
                    oldvalue=float(previous['value'])
                    ticker=TICKERS.get(previous['cusip'],'')
                    exitrow={'fund':fund['name'],'short':fund['short'],'cik':cik,'period':currperiod,
                             'previous_period':older['period'],'filed':current['filed'],'source':current['url'],
                             'name':previous['issuer'],'ticker':ticker,'cusip':previous['cusip'],
                             'shares':0,'previous_shares':int(previous['shares']),
                             'delta_shares':-int(previous['shares']),'value_usd':0.,
                             'estimated_change_usd':oldvalue,'action':'전량매도','change_pct':-100.}
                    detail.append(exitrow)
                    block=summary[previous['cusip']]
                    if not block['name']:
                        block['name']=previous['issuer'];block['ticker']=ticker;block['cusip']=previous['cusip']
                    block['sell_usd']+=oldvalue
        managers.append(status)
    rankings=[]
    for r in summary.values():
        rankings.append({'cusip':r['cusip'],'ticker':r['ticker'],'name':r['name'],
                         'buy_usd':round(r['buy_usd']),'sell_usd':round(r['sell_usd']),
                         'hold_usd':round(r['hold_usd']),
                         'buyers':len(r['buyers']),'holders':len(r['holders']),
                         'new_buyers':len(r['new_buyers']),
                         'periods':sorted(r['periods'],reverse=True),
                         'buying_funds':sorted(r['detail'],key=lambda x:-x['estimated_change_usd']),
                         'positions':r['positions']})
    return rankings,detail,managers



def parse_yahoo_chart(content):
    """Optional unofficial Yahoo adjusted closing prices, no prices invented."""
    j=json.loads(content)
    arr=j.get('chart',{}).get('result')
    if not arr: raise ValueError('시세 제공업체에서 자료가 없습니다')
    r=arr[0]
    stamps=r.get('timestamp',[])
    quote=r.get('indicators',{}).get('quote',[{}])[0].get('close',[])
    adj=r.get('indicators',{}).get('adjclose',[])
    closes=adj[0].get('adjclose',[]) if adj else quote
    if len(closes)!=len(stamps):closes=quote
    bars=[]
    for d,v in zip(stamps,closes):
        if v is None or float(v)<=0:continue
        stamp=dt.datetime.fromtimestamp(int(d),dt.timezone.utc).date().isoformat()
        bars.append([stamp,round(float(v),4)])
    if not bars:raise ValueError('유효한 종가가 없습니다')
    return bars


def price_fetch(ticker):
    from urllib.parse import quote
    url='https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1y&interval=1d'%quote(ticker,safe='')
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=15) as resp:
        return parse_yahoo_chart(resp.read(350_000))


def update_prices():
    """Only request 20 actively followed stock tickers; cache results for one day."""
    with lock:
        if price_job['running']:return
        price_job.update(running=True,errors=0,message='공시 후 주가 변동 조회',done=0,total=0)
    con=db_open()
    try:
        ranking,_,_=_rankings(_snapshots(con),'latest')
        buys=sorted((r for r in ranking if r['ticker'] and r['buy_usd']>0),key=lambda r:-r['buy_usd'])[:16]
        holdings=sorted((r for r in ranking if r['ticker']),key=lambda r:-r['hold_usd'])[:12]
        tickers=list(dict.fromkeys(r['ticker'] for r in buys+holdings))[:20]
        with lock:price_job['total']=len(tickers)
        cutoff=(dt.datetime.now().astimezone()-dt.timedelta(hours=22)).isoformat()
        for ticker in tickers:
            prev=con.execute('SELECT checked FROM prices WHERE ticker=?',(ticker,)).fetchone()
            if not prev or prev[0]<cutoff:
                try:
                    bars=price_fetch(ticker)
                    con.execute('INSERT OR REPLACE INTO prices(ticker,bars,checked) VALUES(?,?,?)',(ticker,json.dumps(bars),now_iso()))
                    con.commit()
                except Exception as ex:
                    with lock:price_job['errors']+=1
                time.sleep(0.7)
            with lock:price_job['done']+=1
        with lock:price_job['updated']=now_iso();price_job['message']='시세 확인 완료'
    finally:
        con.close()
        with lock:price_job['running']=False


def add_price_indicators(rankings,con):
    data={ticker:json.loads(bars) for ticker,bars in con.execute('SELECT ticker,bars FROM prices')}
    for r in rankings:
        bars=data.get(r['ticker'],[])
        if not bars:continue
        sources=r['buying_funds'] if r['buying_funds'] else r['positions']
        filed_dates=[p.get('filed','') for p in sources if p.get('filed')]
        if not filed_dates:continue
        anchor=max(filed_dates)
        after=next((item for item in bars if item[0]>anchor),None)
        if not after:continue
        latest=bars[-1]
        if latest[0]<anchor:continue
        r['price']={'anchor':anchor,'ref_date':after[0],'latest_date':latest[0],
                    'start':after[1],'last':latest[1],
                    'return_pct':round((latest[1]/after[1]-1)*100,2),
                    'is_adjusted':True}




# Technical analysis is independent from SEC quarterly reporting; this is NOT
# a win-probability estimate and NEVER sends trading orders.
def signal_targets(period='latest',fund='all',limit=20):
    con=db_open()
    try:
        byfund=_snapshots(con)
        rows,_,_=_rankings(byfund,period)
        rows=sig.group_company_rankings(rows)
    finally:con.close()
    if fund!='all':
        if fund not in {f['cik'] for f in MANAGERS}:fund='all'
        else:
            for r in rows:
                buys=[x for x in r['buying_funds'] if x['cik']==fund]
                r['buy_usd']=sum(x['estimated_change_usd'] for x in buys)
                r['buyers']=len({x['cik'] for x in buys})
    eligible=sorted((r for r in rows if r.get('buy_usd',0)>0 and not sig.is_etf(r)),key=lambda r:-r['buy_usd'])
    tradable=[r for r in eligible if r.get('ticker')]
    return tradable[:limit],sum(not r.get('ticker') for r in eligible)


def market_cache_key(ticker):
    return "BINEQ:"+ticker

def _read_signal_cache(con,ticker):
    rows=con.execute('SELECT interval,bars,checked,error FROM signal_bars WHERE ticker=?',(ticker,)).fetchall()
    return {k:{'bars':json.loads(bars),'checked':checked,'error':err} for k,bars,checked,err in rows}


def provider_cache_key(ticker,provider):
    if provider=='binance':return market_cache_key(ticker)
    if provider=='alpaca_iex':return 'ALPACA_IEX:'+ticker
    if provider=='alpaca_sip':return 'ALPACA_SIP:'+ticker
    return 'STOCK:'+ticker


def update_equity_market(con, period='latest', fund='all', force=False):
    """Update TOP20 without ever mixing feeds in signals or backtest records.

    With Alpaca API keys available, use Alpaca IEX (or explicitly permitted SIP).
    Without them, default to the existing Yahoo regular-session fallback.
    Binance is used ONLY if WHALE50_MARKET_PROVIDER=binance is selected.
    """
    import os
    targets,_=signal_targets(period,fund)
    selected=os.environ.get('WHALE50_MARKET_PROVIDER','auto').lower().strip()
    if selected not in ('auto','alpaca','yahoo','binance'):
        selected='auto'
    active={};access_error=''
    if selected=='binance':
        try:active=market.active_equity_pairs()
        except Exception as ex:
            access_error=str(ex)[:180]
            print('BINANCE ACCESS ERROR:',access_error,flush=True)
    with lock:signal_job['total']=len(targets)*len(sig.FRAMES)
    cutoff=(dt.datetime.now().astimezone()-dt.timedelta(seconds=sig.SIGNAL_INTERVAL_SECONDS)).isoformat()
    counts={'binance':0,'alpaca_iex':0,'alpaca_sip':0,'stock':0,'errors':0}
    for r in targets:
        ticker=r['ticker']
        if selected=='binance' and active.get(ticker):
            provider='binance';pair=active[ticker];reason=''
        elif selected=='binance':
            provider='stock';pair=ticker;reason=('바이낸스 접근 오류: '+access_error if access_error else '바이낸스 주식 선물 미확인')+'; Yahoo 정규장 대체'
        elif selected in ('auto','alpaca') and alpaca.configured():
            af=alpaca.feed();provider='alpaca_'+af;pair=ticker
            reason=('IEX 단일 거래소 시세, 전체 시장/24시간 시세 아님' if af=='iex' else 'SIP 전 거래소 시세 (구독 권한 필요), 24/7 아님')
        elif selected=='alpaca':
            af=alpaca.feed();provider='alpaca_'+af;pair=ticker
            reason='Alpaca 키 미설정; GitHub Secrets 또는 로컬 설정 필요'
        else:
            provider='stock';pair=ticker
            reason='Alpaca 키 미설정 → Yahoo 정규장 대체 (24/7 아님)' if selected=='auto' else 'Yahoo 정규장 (24/7 아님)'
        key=provider_cache_key(ticker,provider)
        con.execute("""INSERT OR REPLACE INTO market_selection(ticker,provider,pair,note,checked)
                       VALUES(?,?,?,?,?)""",(ticker,provider,pair,reason,now_iso()))
        con.commit()
        counts[provider]+=1
        for frame in sig.FRAMES:
            with lock:signal_job['current']=f'{ticker} {provider} {frame}'
            existing=con.execute('SELECT bars,checked FROM signal_bars WHERE ticker=? AND interval=?',(key,frame)).fetchone()
            if not force and existing and existing[1]>=cutoff and existing[0]!='[]':
                with lock:signal_job['done']+=1
                continue
            try:
                if provider=='binance':bars=market.get_candles(pair,frame)
                elif provider.startswith('alpaca_'):bars=alpaca.get_candles(ticker,frame)
                else:bars=stock.get_candles(ticker.replace('.','-'),frame)
                merged=sig.merge_bars(json.loads(existing[0]) if existing else [],bars)
                con.execute("""INSERT OR REPLACE INTO signal_bars(ticker,interval,bars,checked,error)
                               VALUES(?,?,?,?,?)""",(key,frame,json.dumps(merged),now_iso(),''))
                print('PRICE OK',ticker,provider,frame,len(merged),flush=True)
            except Exception as ex:
                counts['errors']+=1
                with lock:signal_job['errors']+=1
                con.execute("""INSERT OR REPLACE INTO signal_bars(ticker,interval,bars,checked,error)
                               VALUES(?,?,?,?,?)""",(key,frame,existing[0] if existing else '[]',now_iso(),str(ex)[:250]))
                print('PRICE ERROR',ticker,provider,frame,str(ex)[:100],flush=True)
            con.commit()
            with lock:signal_job['done']+=1
            time.sleep(.05)
        try:
            cache=_read_signal_cache(con,key)
            frames=validation.frame_bars({k:v['bars'] for k,v in cache.items() if v['bars']})
            for frame,bars in frames.items():validation.record_forward(con,key,frame,bars)
        except Exception as ex:print('Validation error',ticker,ex,flush=True)
    with lock:signal_job.update(updated=now_iso(),message=f'Alpaca IEX {counts["alpaca_iex"]} / SIP {counts["alpaca_sip"]} / Yahoo {counts["stock"]} / Binance {counts["binance"]}; 오류 {counts["errors"]}')
    return counts


def run_signals_update(period='latest',fund='all',force=False):
    with lock:
        if signal_job['running']:return False
        signal_job.update(running=True,updated=now_iso(),done=0,total=0,errors=0,current='',message='시세 갱신 시작')
    con=db_open()
    try:
        update_equity_market(con,period,fund,force)
    finally:
        con.close()
        with lock:signal_job.update(running=False,current='')
    return True


def try_signals_background(period='latest',fund='all',force=False):
    with lock:
        if signal_job['running']:return False
    thread=threading.Thread(target=run_signals_update,args=(period,fund,force),daemon=True)
    thread.start()
    return True


def signal_view(period='latest',fund='all'):
    targets,unknown_count=signal_targets(period,fund)
    con=db_open()
    out=[]
    try:
        selections={ticker:{'provider':provider,'pair':pair,'note':note,'checked':checked}
                    for ticker,provider,pair,note,checked in con.execute(
                        'SELECT ticker,provider,pair,note,checked FROM market_selection')}
        for r in targets:
            item=selections.get(r['ticker'],{})
            provider=item.get('provider','')
            key=provider_cache_key(r['ticker'],provider)
            cache=_read_signal_cache(con,key)
            sources={k:v['bars'] for k,v in cache.items() if v['bars']}
            frames=sig.build_signals(sources) if provider else {
                fr:{'status':'unavailable','reason':'시세 조회 전: 업데이트를 실행하세요'} for fr in sig.FRAMES}
            for fr,signal in frames.items():
                if signal.get('status')=='insufficient' and cache.get(fr,{}).get('error'):
                    signal['reason']=cache[fr]['error']
                if signal.get('status')=='ok':
                    try:
                        age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(signal['last_bar_utc'])).total_seconds()
                        # US stock source can be stale for nights/weekends: do not treat
                        # a stale regular session quote as a LIVE price.
                        max_age=5*86400 if fr=='1d' else 22*86400 if fr=='1wk' else 75*86400 if fr=='1mo' else (3*86400 if provider!='binance' else {'15m':3600,'30m':7200,'1h':10800,'4h':21600}[fr])
                        if age>max_age:
                            signal['status']='stale';signal['reason']='마지막 거래봉 오래됨 (정규장 휴장 가능)'
                    except (ValueError,TypeError): pass
            valid_dates=[v['checked'] for v in cache.values() if v['bars']]
            problems={k:v['error'] for k,v in cache.items() if v['error']}
            out.append({'company_key':r['company_key'],'ticker':r['ticker'],'name':r['name'],
                        'buy_usd':r['buy_usd'],'buyers':r['buyers'],
                        'market_pair':item.get('pair',''),
                        'provider':provider,'provider_note':item.get('note',''),
                        'market_source':('바이낸스 주식 무기한 선물 24/7' if provider=='binance' else 'Alpaca IEX 미국 주식 (단일 거래소, 24/7 아님)' if provider=='alpaca_iex' else 'Alpaca SIP 미국 주식 (24/7 아님)' if provider=='alpaca_sip' else 'Yahoo 미국 주식 정규장 (24/7 아님)'),
                        'funds':r['buying_funds'],'frames':frames,
                        'updated':max(valid_dates,default=''),'errors':problems})
    finally: con.close()
    return {'rows':out,'unknown_ticker_skipped':unknown_count,'period':period,
            'fund':fund,'market_source':'Alpaca / Yahoo / Binance 별도 보관 (미국 주식 24/7 아님)',
            'job':dict(signal_job),'frame_order':sig.FRAMES,'asof':now_iso(),
            'meaning':'롱/숏은 지표 방향 점수이며 검증된 확률이 아닙니다. Alpaca 무료 IEX는 전체 거래소/24시간 시세가 아닙니다.'}


def maybe_signals_automatic():
    # On desktop, refresh the top 20 verified Binance equity perpetuals.
    # API failures remain visible as errors, not invented scores.
    time.sleep(120)
    while True:
        try:
            if not signal_job['running']:
                con=db_open()
                have=con.execute('SELECT COUNT(*) FROM filings').fetchone()[0]
                fresh=con.execute('SELECT COUNT(*) FROM signal_bars WHERE checked>=?',
                          ((dt.datetime.now().astimezone()-dt.timedelta(minutes=10)).isoformat(),)).fetchone()[0]
                con.close()
                if have and fresh<15: try_signals_background('latest')
        except Exception as ex:print('Auto signal check:',ex)
        time.sleep(300)


def performance_view(period='latest',fund='all'):
    targets,_=signal_targets(period,fund)
    con=db_open()
    try:
        cache={}
        selections={t:(p,pr) for t,p,pr in con.execute('SELECT ticker,provider,pair FROM market_selection')}
        for r in targets:
            provider,pair=selections.get(r['ticker'],('', ''))
            if not provider:continue
            key=provider_cache_key(r['ticker'],provider)
            info=_read_signal_cache(con,key)
            cache[key]={src:row['bars'] for src,row in info.items() if row['bars']}
        report=validation.report(cache,con)
        for item in report['rows']:
            key=item['ticker']
            item['provider']=('바이낸스 24/7 선물' if key.startswith('BINEQ:') else 'Alpaca IEX' if key.startswith('ALPACA_IEX:') else 'Alpaca SIP' if key.startswith('ALPACA_SIP:') else 'Yahoo 정규장')
            item['market_pair']=selections.get(key.split(':',1)[-1],('', ''))[1]
            item['ticker']=key.split(':',1)[-1]
        report['market_source']='Alpaca IEX/SIP · Yahoo 정규장 · Binance 주식선물은 출처별 개별 결과 (혼합 집계 주의)'
        report['notice']='IEX/SIP/정규장 주식과 Binance 24/7 선물은 다른 자료이므로 적중률을 혼합 비교하면 안 됩니다.'
        return report
    finally:con.close()


def get_payload(period='latest'):
    con=db_open()
    try:
        byfund=_snapshots(con)
        checks={cik:{'checked':checked,'error':error} for cik,checked,error in con.execute('SELECT cik,checked,error FROM checks')}
        periods=sorted({p for data in byfund.values() for p in data},reverse=True)
        if period!='latest' and period not in periods: period='latest'
        rankings, detail, managers=_rankings(byfund,period)
        add_price_indicators(rankings,con)
        rankings=sig.group_company_rankings(rankings)
        for m in managers:m.update(checks.get(m['cik'],{}))
        return {'selected_period':period,'periods':periods,'rankings':rankings,'details':detail,
                'managers':managers,'manager_count':len(MANAGERS),'available_count':sum(bool(m['period']) for m in managers),
                'compared_count':sum(bool(m['comparison_period']) for m in managers),
                'check':dict(job),'price_check':dict(price_job),'config':{'configured':bool(load_config()['email'])},'now':now_iso()}
    finally: con.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if not self.path.startswith('/api/data'): print('[web]',fmt%args)
    def send(self, payload, status=200, kind='application/json; charset=utf-8'):
        if isinstance(payload,(dict,list)):payload=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        elif isinstance(payload,str):payload=payload.encode('utf-8')
        self.send_response(status); self.send_header('Content-Type',kind)
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/':
            self.send((ROOT/'dashboard.html').read_bytes(),kind='text/html; charset=utf-8')
        elif path=='/api/data':
            self.send(get_payload(parse_qs(urlparse(self.path).query).get('period',['latest'])[0]))
        elif path=='/api/settings':
            self.send(load_config())
        elif path=='/api/signals':
            qs=parse_qs(urlparse(self.path).query)
            period=qs.get('period',['latest'])[0]
            fund=qs.get('fund',['all'])[0]
            if not (period=='latest' or re.fullmatch(r'20\d\d-\d\d-\d\d',period)):period='latest'
            self.send(signal_view(period,fund))
        elif path=='/api/performance':
            qs=parse_qs(urlparse(self.path).query)
            period=qs.get('period',['latest'])[0]
            fund=qs.get('fund',['all'])[0]
            if not (period=='latest' or re.fullmatch(r'20\d\d-\d\d-\d\d',period)):period='latest'
            self.send(performance_view(period,fund))
        elif path=='/api/status':
            with lock:self.send(dict(job))
        else:self.send({'error':'Not found'},404)
    def do_POST(self):
        if self.headers.get('Origin') not in ('',None,'http://127.0.0.1:%s'%PORT,'http://localhost:%s'%PORT):
            return self.send({'error':'Origin denied'},403)
        size=int(self.headers.get('Content-Length','0') or 0)
        if size>2048:return self.send({'error':'Too large'},413)
        try: body=json.loads(self.rfile.read(size) or b'{}')
        except ValueError:return self.send({'error':'잘못된 요청'},400)
        path=urlparse(self.path).path
        if path=='/api/settings':
            email=str(body.get('email','')).strip();name=str(body.get('contact_name','Personal Investor')).strip()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
                return self.send({'error':'SEC 데이터 요청용 실제 이메일 주소가 필요합니다'},400)
            save_config({'email':email,'contact_name':name or 'Personal Investor'})
            self.send({'ok':True})
        elif path=='/api/signals/refresh':
            period=str(body.get('period','latest'))
            fund=str(body.get('fund','all'))
            if not (period=='latest' or re.fullmatch(r'20\d\d-\d\d-\d\d',period)):period='latest'
            if fund!='all' and fund not in {f['cik'] for f in MANAGERS}:return self.send({'error':'잘못된 운용사'},400)
            started=try_signals_background(period,fund,True)
            self.send({'started':started,'running':not started})
        elif path=='/api/refresh':
            conf=load_config()
            if not conf['email']:return self.send({'error':'먼저 SEC 연락용 이메일을 입력해주세요'},400)
            if job['running']:return self.send({'running':True})
            try_update_background(); self.send({'started':True})
        else:self.send({'error':'Not found'},404)


def start_server(open_browser=True):
    db_open().close()
    t=threading.Thread(target=maybe_automatic,daemon=True);t.start()
    threading.Thread(target=maybe_signals_automatic,daemon=True).start()
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    url='http://127.0.0.1:%s/'%PORT
    print('Whale50 대시보드 시작:',url,flush=True)
    if open_browser:
        threading.Timer(0.9,lambda:webbrowser.open(url)).start()
    try:server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:print('\n종료합니다')
    finally:server.server_close()


def main():
    parser=argparse.ArgumentParser(description='Whale50 SEC 13F Tracker')
    parser.add_argument('--update',action='store_true',help='Fetch updated SEC filings and exit')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if args.update:
        ok=run_update();print(json.dumps(job,ensure_ascii=False,indent=2));sys.exit(0 if ok and not job['errors'] else 1)
    start_server(open_browser=not args.no_browser)

if __name__=='__main__':main()
