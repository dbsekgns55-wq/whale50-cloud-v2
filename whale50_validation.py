# -*- coding: utf-8 -*-
"""Walk-forward direction score validation.

Signal is computed using bars <= i ONLY. Decision at close of i; next
complete bar's open -> close is the outcome. No intrabar fills or trading.
Historical replay and observations registered BEFORE the outcome are separate.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import json
import sqlite3
import time
import whale50_signals as sig

MIN_BARS = 78
# 15m, 30m, 1h, 4h, 24h day, week, month
FRAMES = ('15m','30m','1h','4h','1d','1wk','1mo')
LABEL = {'15m':'15분','30m':'30분','1h':'1시간','4h':'4시간','1d':'일봉','1wk':'주봉','1mo':'월봉'}


def frame_bars(sources):
    data = {k:list(v) for k,v in sources.items()}
    return {k:data.get(k,[]) for k in FRAMES}


def outcome(b):
    """Prediction for direction of NEXT bar open to close, no execution assumed."""
    pct = (float(b['c']) / float(b['o']) - 1) * 100 if float(b['o']) else 0
    return pct, ('롱' if pct>1e-10 else '숏' if pct < -1e-10 else '보합')


def empty_counts():
    return {'correct':0,'wrong':0,'flat':0,'neutral':0,'evaluated':0,'hit_rate':None,'sample_bars':0,'start_utc':'','end_utc':''}


def finish(d):
    d['evaluated']=d['correct']+d['wrong']
    d['hit_rate']=round(100*d['correct']/d['evaluated'],1) if d['evaluated'] else None
    return d


def backtest_one(bars, frame, max_trials=180):
    """Strict chronology: at bar i close calculate score, check next bar open->close.

    Only SIGNALS with side in {long,short} count as trials; neutral separately.
    Historical replay ≠ forward observation, and doesn't include trading costs.
    """
    out=empty_counts()
    n=len(bars)
    if n < MIN_BARS+1:
        out['sample_bars']=n
        return out
    first=max(MIN_BARS-1,n-1-max_trials)
    for i in range(first,n-1):
        signal=sig.indicator(bars[:i+1],frame)
        if signal['status']!='ok': continue
        if signal['side']=='관망':
            out['neutral']+=1
            continue
        pct, actual=outcome(bars[i+1])
        if actual=='보합':out['flat']+=1
        elif (signal['side']=='롱 우세' and actual=='롱') or (signal['side']=='숏 우세' and actual=='숏'):
            out['correct']+=1
        else:out['wrong']+=1
    out['sample_bars']=n
    out['start_utc']=datetime.fromtimestamp(bars[first]['t'],timezone.utc).strftime('%Y-%m-%d %H:%M')
    out['end_utc']=datetime.fromtimestamp(bars[-1]['t'],timezone.utc).strftime('%Y-%m-%d %H:%M')
    return finish(out)


def init_db(con):
    con.execute('''CREATE TABLE IF NOT EXISTS forward_predictions (
        ticker TEXT NOT NULL, frame TEXT NOT NULL, signal_bar INTEGER NOT NULL,
        recorded_at TEXT NOT NULL, side TEXT NOT NULL, long_score INTEGER NOT NULL,
        result TEXT NOT NULL DEFAULT 'pending', outcome_pct REAL,
        next_bar INTEGER, resolved_at TEXT,
        PRIMARY KEY (ticker, frame, signal_bar))''')
    con.commit()


def record_forward(con,ticker,frame,bars,record=True):
    """Settle previously timestamped predictions, then register latest bar.

    Never reconstruct 'live' predictions from past bars. Also refuses new
    entries if newest bar is evidently stale; existing pending can settle.
    """
    init_db(con)
    lookup={int(b['t']):i for i,b in enumerate(bars)}
    for t,side in con.execute('''SELECT signal_bar,side FROM forward_predictions
                    WHERE ticker=? AND frame=? AND result='pending' ''',(ticker,frame)):
        idx=lookup.get(int(t))
        if idx is None or idx+1>=len(bars):continue
        next_bar=bars[idx+1]
        pct,actual=outcome(next_bar)
        result='flat' if actual=='보합' else 'correct' if ((side=='롱 우세' and actual=='롱') or (side=='숏 우세' and actual=='숏')) else 'wrong'
        con.execute('''UPDATE forward_predictions SET result=?,outcome_pct=?,next_bar=?,resolved_at=?
                    WHERE ticker=? AND frame=? AND signal_bar=?''',
                    (result,round(pct,6),int(next_bar['t']),datetime.now(timezone.utc).isoformat(),ticker,frame,int(t)))
    if record and len(bars)>=MIN_BARS:
        latest=bars[-1]
        age=time.time()-int(latest['t'])
        max_age=86400*4 if frame in ('15m','30m','1h','4h') else 86400*8 if frame=='1d' else 86400*20 if frame=='1wk' else 86400*75
        if -3600<age<max_age:
            signal=sig.indicator(bars,frame)
            if signal.get('status')=='ok' and signal['side']!='관망':
                con.execute('''INSERT OR IGNORE INTO forward_predictions
                  (ticker,frame,signal_bar,recorded_at,side,long_score)
                  VALUES(?,?,?,?,?,?)''',
                  (ticker,frame,int(latest['t']),datetime.now(timezone.utc).isoformat(),signal['side'],signal['long']))
    con.commit()


def forward_stats(con,ticker,frame):
    init_db(con)
    records=con.execute('''SELECT result,count(*) FROM forward_predictions
                          WHERE ticker=? AND frame=? GROUP BY result''',(ticker,frame)).fetchall()
    counts={a:int(b) for a,b in records}
    win=counts.get('correct',0);loss=counts.get('wrong',0)
    return {'correct':win,'wrong':loss,'flat':counts.get('flat',0),'pending':counts.get('pending',0),
            'evaluated':win+loss,'hit_rate':round(100*win/(win+loss),1) if win+loss else None}


def report(cache_by_ticker,con):
    """cache_by_ticker: dict(ticker -> {source interval -> bars})"""
    allrows=[];aggregate={f:empty_counts() for f in FRAMES}
    forward_agg={f:{'correct':0,'wrong':0,'flat':0,'pending':0} for f in FRAMES}
    for ticker,sources in cache_by_ticker.items():
        frames=frame_bars(sources)
        for frame,bars in frames.items():
            stats=backtest_one(bars,frame)
            fw=forward_stats(con,ticker,frame)
            allrows.append({'ticker':ticker,'frame':frame,'label':LABEL[frame],'historical':stats,'forward':fw})
            for k in ('correct','wrong','flat','neutral'):
                aggregate[frame][k]+=stats[k]
            for k in ('correct','wrong','flat','pending'):
                forward_agg[frame][k]+=fw[k]
    for fr in FRAMES:
        finish(aggregate[fr]);f=forward_agg[fr];d=f['correct']+f['wrong']
        f['evaluated']=d;f['hit_rate']=round(f['correct']/d*100,1) if d else None
    return {'frame_order':list(FRAMES),'rows':allrows,'historical':aggregate,'forward':forward_agg,
            'method':'Historical on Binance equity perpetuals: past completed bars only; predict next completed bar open→close. Forward: signal was saved before that outcome occurred.',
            'notice':'바이낸스 주식 무기한 선물 가격의 과거 재생 적중률은 실거래 검증이 아닙니다. 관망은 제외하며 수수료·슬리피지·배당·공매도 비용을 반영하지 않습니다.',
            'asof':datetime.now(timezone.utc).isoformat()}
