#!/usr/bin/env python3
"""Evaluation Lab v2: deduplicate ABCDE signals and evaluate next-session entries."""
import argparse, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
DB=Path('/root/.openclaw/workspace/CK/db/ck_signals.sqlite'); MODEL='SIB_EVAL_V2'; H=(5,10,20,60)
def pct(a,b): return None if a is None or not b else (a/b-1)*100
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--db',default=str(DB)); ap.add_argument('--from-date'); ap.add_argument('--to-date'); ap.add_argument('--dry-run',action='store_true'); a=ap.parse_args()
 c=sqlite3.connect(a.db); c.row_factory=sqlite3.Row
 c.executescript('''CREATE TABLE IF NOT EXISTS sib_eval_v2_trades(snapshot_date TEXT,ticker TEXT,score_bucket TEXT,sib_score REAL,data_quality REAL,regime TEXT,signal_id TEXT,entry_date TEXT,entry_price REAL,horizon INTEGER,exit_date TEXT,exit_price REAL,return_pct REAL,benchmark_return_pct REAL,excess_return_pct REAL,mfe_pct REAL,mae_pct INTEGER,PRIMARY KEY(snapshot_date,ticker,horizon)); CREATE TABLE IF NOT EXISTS sib_eval_v2_report(score_bucket TEXT,regime TEXT,horizon INTEGER,samples INTEGER,win_rate REAL,avg_return_pct REAL,median_return_pct REAL,avg_excess_pct REAL,avg_mfe_pct REAL,avg_mae_pct REAL,updated_at TEXT,PRIMARY KEY(score_bucket,regime,horizon));''')
 w=['d.scanner_version=?','d.signal_date IS NOT NULL']; p=['ABCDE_v2.0']
 if a.from_date:w+=['d.signal_date>=?'];p+=[a.from_date]
 if a.to_date:w+=['d.signal_date<=?'];p+=[a.to_date]
 rows=c.execute('''SELECT d.* FROM daily_signals d JOIN (SELECT signal_date,ticker,MAX(COALESCE(final_score,-1)) score FROM daily_signals WHERE scanner_version='ABCDE_v2.0' GROUP BY signal_date,ticker) x ON x.signal_date=d.signal_date AND x.ticker=d.ticker AND x.score=COALESCE(d.final_score,-1) WHERE '''+' AND '.join(w)+' ORDER BY d.signal_date,d.ticker',p).fetchall()
 now=datetime.now(timezone.utc).isoformat(timespec='seconds'); n=0
 for r in rows:
  nxt=c.execute("SELECT trade_date,close FROM daily_prices WHERE ticker=? AND trade_date>? ORDER BY trade_date LIMIT 1",(r['ticker'],r['signal_date'])).fetchone()
  if not nxt or not nxt['close']:continue
  entry=nxt['close']; regime=(c.execute('SELECT regime_label FROM market_regime WHERE trade_date=?',(r['signal_date'],)).fetchone() or [None])[0] or 'UNKNOWN'; score=float(r['final_score']) if r['final_score'] is not None else None
  bucket='90-100' if score>=90 else '80-89' if score>=80 else '70-79' if score>=70 else '<70'
  ps=c.execute('SELECT trade_date,close,high,low FROM daily_prices WHERE ticker=? AND trade_date>? ORDER BY trade_date LIMIT 60',(r['ticker'],nxt['trade_date'])).fetchall()
  bi=c.execute('SELECT trade_date,close FROM daily_prices WHERE ticker="VNINDEX" AND trade_date>? ORDER BY trade_date LIMIT 60',(nxt['trade_date'],)).fetchall()
  for h in H:
   if len(ps)<h:continue
   ex=ps[h-1]; br=bi[h-1] if len(bi)>=h else None; ret=pct(ex['close'],entry); bref=pct(br['close'],bi[0]['close']) if br else None
   mfe=max(pct(x['high'],entry) for x in ps[:h] if x['high'] is not None); mae=min(pct(x['low'],entry) for x in ps[:h] if x['low'] is not None)
   if not a.dry_run:c.execute('INSERT OR REPLACE INTO sib_eval_v2_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(r['signal_date'],r['ticker'],bucket,score,sum(r[k] is not None for k in ('a_score','b_score','c_score','d_score','e_score'))*20,regime,r['signal_id'],nxt['trade_date'],entry,h,ex['trade_date'],ex['close'],ret,bref,ret-bref if bref is not None else None,mfe,mae))
   n+=1
 if not a.dry_run:
  c.execute('DELETE FROM sib_eval_v2_report');
  q=c.execute('SELECT score_bucket,regime,horizon,COUNT(*),AVG(return_pct),AVG(excess_return_pct),AVG(mfe_pct),AVG(mae_pct) FROM sib_eval_v2_trades GROUP BY 1,2,3').fetchall()
  for x in q:
   vals=[x[0],x[1],x[2],x[3],None,x[4],None,x[5],x[6],x[7],now]; c.execute('INSERT INTO sib_eval_v2_report VALUES (?,?,?,?,?,?,?,?,?,?,?)',vals)
  # fill win/median separately
  for x in c.execute('SELECT score_bucket,regime,horizon FROM sib_eval_v2_report').fetchall():
   z=c.execute('SELECT return_pct FROM sib_eval_v2_trades WHERE score_bucket=? AND regime=? AND horizon=?',(x[0],x[1],x[2])).fetchall(); rs=[v[0] for v in z]; win=sum(v>0 for v in rs)/len(rs)*100; med=sorted(rs)[len(rs)//2] if len(rs)%2 else (sorted(rs)[len(rs)//2-1]+sorted(rs)[len(rs)//2])/2
   c.execute('UPDATE sib_eval_v2_report SET win_rate=?,median_return_pct=? WHERE score_bucket=? AND regime=? AND horizon=?',(win,med,x[0],x[1],x[2]))
  c.commit()
 print(json.dumps({'model':MODEL,'dedup_signals':len(rows),'outcomes':n,'dry_run':a.dry_run},ensure_ascii=False)); c.close()
if __name__=='__main__':main()
