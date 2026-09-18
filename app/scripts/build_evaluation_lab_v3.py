#!/usr/bin/env python3
"""Compare ABCDE with Top20, Ichimoku and EMA-RETEST memberships."""
import argparse,sqlite3,json
from datetime import datetime,timezone
DB='/root/.openclaw/workspace/CK/db/ck_signals.sqlite'; H=(5,10,20,60)
VARIANTS={'BASELINE_ABCDE':lambda r:True,'ABCDE_TOP20':lambda r:r['is_top20']==1,'ABCDE_ICHIMOKU':lambda r:r['is_ichimoku_candidate']==1,'ABCDE_EMA_RETEST':lambda r:r['retest_valid']==1,'ABCDE_TOP20_ICHIMOKU':lambda r:r['is_top20']==1 and r['is_ichimoku_candidate']==1,'ABCDE_ALL_MODULES':lambda r:r['is_top20']==1 and r['is_ichimoku_candidate']==1 and r['retest_valid']==1}
def pct(a,b):return None if a is None or not b else (a/b-1)*100
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--db',default=DB);ap.add_argument('--from-date');ap.add_argument('--to-date');ap.add_argument('--dry-run',action='store_true');a=ap.parse_args();c=sqlite3.connect(a.db);c.row_factory=sqlite3.Row
 c.executescript('''CREATE TABLE IF NOT EXISTS sib_eval_v3_trades (snapshot_date TEXT,ticker TEXT,variant TEXT,sib_score REAL,regime TEXT,entry_date TEXT,entry_price REAL,horizon INTEGER,exit_date TEXT,exit_price REAL,return_pct REAL,benchmark_return_pct REAL,excess_return_pct REAL,mfe_pct REAL,mae_pct REAL,PRIMARY KEY(snapshot_date,ticker,variant,horizon));CREATE TABLE IF NOT EXISTS sib_eval_v3_report (variant TEXT,regime TEXT,horizon INTEGER,samples INTEGER,win_rate REAL,avg_return_pct REAL,median_return_pct REAL,avg_excess_pct REAL,avg_mfe_pct REAL,avg_mae_pct REAL,updated_at TEXT,PRIMARY KEY(variant,regime,horizon));''')
 w=[];p=[]
 if a.from_date:w.append('trade_date>=?');p.append(a.from_date)
 if a.to_date:w.append('trade_date<=?');p.append(a.to_date)
 rows=c.execute('SELECT * FROM stock_daily_feature_snapshot'+((' WHERE '+' AND '.join(w)) if w else '')+' ORDER BY trade_date,ticker',p).fetchall(); n=0
 for r in rows:
  for v,rule in VARIANTS.items():
   if not rule(r):continue
   nxt=c.execute('SELECT trade_date,close FROM daily_prices WHERE ticker=? AND trade_date>? ORDER BY trade_date LIMIT 1',(r['ticker'],r['trade_date'])).fetchone()
   if not nxt or not nxt['close']:continue
   ps=c.execute('SELECT trade_date,close,high,low FROM daily_prices WHERE ticker=? AND trade_date>? ORDER BY trade_date LIMIT 60',(r['ticker'],nxt['trade_date'])).fetchall(); bi=c.execute("SELECT trade_date,close FROM daily_prices WHERE ticker='VNINDEX' AND trade_date>? ORDER BY trade_date LIMIT 60",(nxt['trade_date'],)).fetchall()
   for h in H:
    if len(ps)<h:continue
    ex=ps[h-1]; br=bi[h-1] if len(bi)>=h else None; ret=pct(ex['close'],nxt['close']); bref=pct(br['close'],bi[0]['close']) if br else None;mfe=max(pct(x['high'],nxt['close']) for x in ps[:h] if x['high'] is not None);mae=min(pct(x['low'],nxt['close']) for x in ps[:h] if x['low'] is not None)
    if not a.dry_run:c.execute('INSERT OR REPLACE INTO sib_eval_v3_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(r['trade_date'],r['ticker'],v,r['sib_score'],r['regime'],nxt['trade_date'],nxt['close'],h,ex['trade_date'],ex['close'],ret,bref,ret-bref if bref is not None else None,mfe,mae))
    n+=1
 if not a.dry_run:
  c.execute('DELETE FROM sib_eval_v3_report'); now=datetime.now(timezone.utc).isoformat(timespec='seconds')
  for x in c.execute('SELECT variant,regime,horizon,COUNT(*),AVG(return_pct),AVG(excess_return_pct),AVG(mfe_pct),AVG(mae_pct) FROM sib_eval_v3_trades GROUP BY 1,2,3').fetchall():
   z=[q[0] for q in c.execute('SELECT return_pct FROM sib_eval_v3_trades WHERE variant=? AND regime=? AND horizon=?',(x[0],x[1],x[2])).fetchall()]; s=sorted(z);med=s[len(s)//2] if len(s)%2 else (s[len(s)//2-1]+s[len(s)//2])/2;c.execute('INSERT INTO sib_eval_v3_report VALUES (?,?,?,?,?,?,?,?,?,?,?)',(x[0],x[1],x[2],x[3],sum(q>0 for q in z)/len(z)*100,x[4],med,x[5],x[6],x[7],now))
  c.commit()
 print(json.dumps({'model':'SIB_EVAL_V3','snapshot_rows':len(rows),'outcomes':n,'dry_run':a.dry_run,'variants':list(VARIANTS)},ensure_ascii=False));c.close()
if __name__=='__main__':main()
