#!/usr/bin/env python3
"""Build the unified daily feature snapshot for ABCDE/SIB evaluation."""
import argparse,sqlite3,json
from datetime import datetime,timezone
from pathlib import Path
DB='/root/.openclaw/workspace/CK/db/ck_signals.sqlite'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--db',default=DB);ap.add_argument('--from-date');ap.add_argument('--to-date');ap.add_argument('--dry-run',action='store_true');a=ap.parse_args();c=sqlite3.connect(a.db);c.row_factory=sqlite3.Row
 c.executescript('''CREATE TABLE IF NOT EXISTS stock_daily_feature_snapshot (trade_date TEXT NOT NULL,ticker TEXT NOT NULL,feature_version TEXT NOT NULL,signal_id TEXT,exchange TEXT,a_score REAL,b_score REAL,c_score REAL,d_score REAL,e_score REAL,sib_score REAL,data_quality_score REAL,top20_rank REAL,top20_score REAL,is_top20 INTEGER DEFAULT 0,ichimoku_rank_score REAL,ichimoku_d1_setup_score REAL,ichimoku_timing_score REAL,ichimoku_status TEXT,is_ichimoku_candidate INTEGER DEFAULT 0,close REAL,ma20 REAL,ema99 REAL,ema200 REAL,max_ema REAL,ema_distance_pct REAL,ema_gap_pct REAL,vol_ma20 REAL,relative_volume REAL,has_ema_breakout INTEGER DEFAULT 0,has_ema_touch INTEGER DEFAULT 0,retest_valid INTEGER DEFAULT 0,breakout_age INTEGER,touch_age INTEGER,regime TEXT,created_at TEXT NOT NULL,PRIMARY KEY(trade_date,ticker,feature_version));''')
 dates=c.execute("SELECT DISTINCT signal_date FROM daily_signals WHERE scanner_version='ABCDE_v2.0' AND signal_date IS NOT NULL ORDER BY signal_date").fetchall(); dates=[x[0] for x in dates if (not a.from_date or x[0]>=a.from_date) and (not a.to_date or x[0]<=a.to_date)]; n=0;now=datetime.now(timezone.utc).isoformat(timespec='seconds')
 for d in dates:
  sigs=c.execute("SELECT * FROM daily_signals WHERE signal_date=? AND scanner_version='ABCDE_v2.0' ORDER BY COALESCE(final_score,-1) DESC",(d,)).fetchall(); seen=set()
  # Top20 ranks from the daily ABCDE output, not a new ranking formula.
  for rank,r in enumerate(sigs,1):
   if r['ticker'] in seen:continue
   seen.add(r['ticker']); ema=c.execute('SELECT * FROM ma20_ema_signals WHERE scan_date=? AND ticker=?',(d,r['ticker'])).fetchone(); ich=c.execute('SELECT * FROM ichimoku_mtf_signals WHERE scan_date=? AND ticker=? ORDER BY rank_score DESC LIMIT 1',(d,r['ticker'])).fetchone(); price=c.execute('SELECT * FROM daily_prices WHERE ticker=? AND trade_date=?',(r['ticker'],d)).fetchone(); reg=c.execute('SELECT regime_label FROM market_regime WHERE trade_date=?',(d,)).fetchone(); score=r['final_score']; vals=[r[k] for k in ('a_score','b_score','c_score','d_score','e_score')]; quality=sum(v is not None for v in vals)*20
   row=(d,r['ticker'],'FEATURE_SNAPSHOT_V1',r['signal_id'],r['exchange'],*vals,score,quality,rank if rank<=20 else None,score if rank<=20 else None,int(rank<=20),ich['rank_score'] if ich else None,ich['d1_setup_score'] if ich else None,ich['timing_score'] if ich else None,ich['action_status'] if ich else None,int(ich is not None),price['close'] if price else None,ema['ma20'] if ema else None,ema['ema99'] if ema else None,ema['ema200'] if ema else None,max(ema['ema99'],ema['ema200']) if ema else None,((price['close']/max(ema['ema99'],ema['ema200'])-1)*100) if price and ema else None,ema['ema_gap_pct'] if ema else None,ema['vol_ma20'] if ema else None,r['relative_volume'],None,None,None,None,None,reg[0] if reg else 'UNKNOWN',now,None,None)
   if not a.dry_run:c.execute('INSERT OR REPLACE INTO stock_daily_feature_snapshot VALUES ('+','.join('?'*len(row))+')',row)
   n+=1
 if not a.dry_run:c.commit()
 print(json.dumps({'dates':len(dates),'rows':n,'dry_run':a.dry_run,'feature_version':'FEATURE_SNAPSHOT_V1'},ensure_ascii=False));c.close()
if __name__=='__main__':main()
