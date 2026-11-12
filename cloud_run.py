# -*- coding: utf-8 -*-
"""GitHub Actions scheduled, static read-only Whale50 publisher.

This DOES NOT run anywhere until the user publishes it to GitHub and enables
Actions + Pages. Reads public SEC filings and Binance equity perpetual 24/7 market bars.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import shutil
import time
import whale50
import whale50_signals as sig
import whale50_binance as market
import whale50_validation as valid

ROOT=Path(__file__).resolve().parent
SITE=ROOT/'site'


def has_fresh_sec(con, hours=22):
    last=con.execute('SELECT MAX(checked) FROM checks').fetchone()[0]
    if not last:return False
    try:
        age=datetime.now(timezone.utc)-datetime.fromisoformat(last).astimezone(timezone.utc)
        return age.total_seconds()<hours*3600
    except ValueError:return False


def update_market(con):
    # Reuse the exact desktop fetching + source-selection logic.
    # Binance HTTP 451 switches to visibly labelled US stock session candles.
    return whale50.update_equity_market(con, force=False)


def export_site():
    SITE.mkdir(exist_ok=True)
    payload=whale50.get_payload()
    payload['config']={'configured':True}
    signals=whale50.signal_view()
    performance=whale50.performance_view()
    for name,value in [('data.json',payload),('signals.json',signals),('performance.json',performance)]:
        (SITE/name).write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    page=(ROOT/'dashboard.html').read_text(encoding='utf-8')
    page=page.replace('<script>\n\'use strict\';',"<script>window.WHALE50_CLOUD=true;</script>\n<script>\n'use strict';")
    (SITE/'index.html').write_text(page,encoding='utf-8')
    (SITE/'.nojekyll').write_text('',encoding='utf-8')
    # CHECKPOINT: git commits a single database file, not a dangling WAL.
    con=whale50.db_open()
    con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    con.close()
    print('SITE EXPORTED',len(signals['rows']),'stocks; historical',len(performance['rows']),'rows')


def main():
    os.environ['WHALE50_CLOUD']='1'
    con=whale50.db_open()
    due=not has_fresh_sec(con)
    con.close()
    email=whale50.load_config().get('email','')
    if due and email:
        print('SEC: Checking public filings ...')
        whale50.run_update()
    elif due:
        print('SEC: No contact secret configured. Configure WHALE50_SEC_EMAIL in GitHub Actions secrets.')
    con=whale50.db_open()
    try:update_market(con)
    finally:con.close()
    export_site()


if __name__=='__main__':main()
