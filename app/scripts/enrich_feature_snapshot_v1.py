#!/usr/bin/env python3
"""Derive EMA breakout/retest flags for unified feature snapshots."""
import argparse,sqlite3,json
from datetime import datetime,timezone
DB='/root/.openclaw/workspace/CK/db/ck_signals.sqlite'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--db',default=DB);ap.add_argument('--distance-pct',type=float,default=1.5);ap.add_argument('--window',type=int,default=20);a=ap.parse_args();c=sqlite3.connect(a.db);c.row_factory=sqlite3.Row
 rows=c.execute("select trade_date,ticker from stock_daily_feature_snapshot where feature_version='FEATURE_SNAPSHOT_V1' order by ticker,trade_date").fetchall(); n=0
 for r in rows:
  bars=c.execute("select trade_date,close,high,low from daily_prices where ticker=? and trade_date<=? order by trade_date",(r['ticker'],r['trade_date'])).fetchall()
  if len(bars)<210: continue
  closes=[float(x['close']) for x in bars]; ema99=[];ema200=[]
  for span,out in [(99,ema99),(200,ema200)]:
   alpha=2/(span+1);v=closes[0]
   for z in closes: v=alpha*z+(1-alpha)*v;out.append(v)
  maxe=[max(ema99[i],ema200[i]) for i in range(len(bars))]; i=len(bars)-1
  start=max(1,i-a.window); crosses=[j for j in range(start,i) if closes[j]>maxe[j] and closes[j-1]<=maxe[j-1]]
  has=bool(crosses); touch=False; age=None; touchage=None
  if has:
   j=crosses[-1]; age=i-j
   for k in range(j+1,i+1):
    if bars[k]['low'] is not None and float(bars[k]['low'])<=maxe[k]*(1+a.distance_pct/100): touch=True;touchage=i-k
  curdist=(closes[i]/maxe[i]-1)*100
  valid=int(has and touch and closes[i]>maxe[i] and curdist<=a.distance_pct)
  c.execute("update stock_daily_feature_snapshot set has_ema_breakout=?,has_ema_touch=?,retest_valid=?,breakout_age=?,touch_age=?,ema99_slope_pct=?,ema200_slope_pct=? where trade_date=? and ticker=? and feature_version=?",(int(has),int(touch),valid,age,touchage,(ema99[i]/ema99[max(0,i-10)]-1)*100,(ema200[i]/ema200[max(0,i-10)]-1)*100,r['trade_date'],r['ticker'],'FEATURE_SNAPSHOT_V1'));n+=1
 c.commit();print(json.dumps({'updated':n,'distance_pct':a.distance_pct,'window':a.window},ensure_ascii=False));c.close()
if __name__=='__main__':main()
