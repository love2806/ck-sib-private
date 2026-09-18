#!/usr/bin/env python3
"""Build versioned SIB baseline snapshots and forward outcomes from CK SQLite.

Uses the frozen ABCDE_v2.0 daily_signals rows as the SIB baseline. Outcomes are
looked up strictly after signal_date, avoiding look-ahead from the signal bar.
"""
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path('/root/.openclaw/workspace/CK')
DB = ROOT / 'db/ck_signals.sqlite'
MODEL = 'SIB_BASELINE_V1'
HORIZONS = (5, 10, 20, 60)


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript('''
    CREATE TABLE IF NOT EXISTS sib_score_snapshots (
      snapshot_date TEXT NOT NULL, ticker TEXT NOT NULL, model_id TEXT NOT NULL,
      scanner_version TEXT, a_score REAL, b_score REAL, c_score REAL,
      d_score REAL, e_score REAL, sib_score REAL, data_quality_score REAL,
      source_signal_id TEXT, created_at TEXT NOT NULL,
      PRIMARY KEY (snapshot_date, ticker, model_id)
    );
    CREATE TABLE IF NOT EXISTS sib_outcomes (
      snapshot_date TEXT NOT NULL, ticker TEXT NOT NULL, model_id TEXT NOT NULL,
      horizon_days INTEGER NOT NULL, entry_price REAL, exit_date TEXT,
      exit_price REAL, return_pct REAL, benchmark_return_pct REAL,
      excess_return_pct REAL, max_favorable_excursion_pct REAL,
      max_adverse_excursion_pct REAL, closed_below_ema INTEGER,
      created_at TEXT NOT NULL,
      PRIMARY KEY (snapshot_date, ticker, model_id, horizon_days)
    );
    CREATE INDEX IF NOT EXISTS idx_sib_snapshots_date_score
      ON sib_score_snapshots(snapshot_date, sib_score DESC);
    CREATE INDEX IF NOT EXISTS idx_sib_outcomes_horizon
      ON sib_outcomes(model_id, horizon_days, snapshot_date);
    ''')


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0): return None
    return (a / b - 1.0) * 100.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(DB)); ap.add_argument('--from-date')
    ap.add_argument('--to-date'); ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    con = sqlite3.connect(args.db); con.row_factory = sqlite3.Row
    ensure_schema(con)
    where = ['scanner_version=?', 'signal_date IS NOT NULL']
    params = ['ABCDE_v2.0']
    if args.from_date: where.append('signal_date>=?'); params.append(args.from_date)
    if args.to_date: where.append('signal_date<=?'); params.append(args.to_date)
    rows = con.execute('SELECT * FROM daily_signals WHERE '+ ' AND '.join(where), params).fetchall()
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    snap_n = out_n = 0
    for r in rows:
        vals = [r[k] for k in ('a_score','b_score','c_score','d_score','e_score')]
        available = [float(v) for v in vals if v is not None]
        # Preserve the production ABCDE final_score as the frozen baseline.
        # Some historical rows have E=None; do not silently discard them.
        # Mark the snapshot quality instead and retain the published score.
        total = r['final_score'] if r['final_score'] is not None else (sum(available) if len(available) == 5 else None)
        quality = len(available) / 5 * 100
        if total is None: continue
        if not args.dry_run:
            con.execute('''INSERT OR REPLACE INTO sib_score_snapshots
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (r['signal_date'], r['ticker'], MODEL, r['scanner_version'], *vals,
               total, quality, r['signal_id'], now))
        snap_n += 1
        prices = con.execute('''SELECT trade_date,close,high,low FROM daily_prices
          WHERE ticker=? AND trade_date>? ORDER BY trade_date LIMIT 60''',
          (r['ticker'], r['signal_date'])).fetchall()
        idx = con.execute('''SELECT trade_date,close FROM daily_prices
          WHERE ticker='VNINDEX' AND trade_date>? ORDER BY trade_date LIMIT 60''',
          (r['signal_date'],)).fetchall()
        entry = r['entry_price']
        if entry is None:
            base = con.execute('SELECT close FROM daily_prices WHERE ticker=? AND trade_date=?', (r['ticker'],r['signal_date'])).fetchone()
            entry = base['close'] if base else None
        if not entry: continue
        for h in HORIZONS:
            if len(prices) < h: continue
            p = prices[h-1]; bench = idx[h-1] if len(idx) >= h else None
            window = prices[:h]
            ret = pct(p['close'], entry)
            bench_ret = pct(bench['close'], idx[0]['close']) if bench else None
            ema = None
            closes = [float(x['close']) for x in window if x['close'] is not None]
            if closes:
                alpha = 2/(200+1); ema = closes[0]
                for c in closes[1:]: ema = alpha*c+(1-alpha)*ema
            below = int(bool(ema is not None and float(p['close']) < ema))
            mfe = max((pct(x['high'], entry) for x in window if x['high'] is not None), default=None)
            mae = min((pct(x['low'], entry) for x in window if x['low'] is not None), default=None)
            if not args.dry_run:
                con.execute('''INSERT OR REPLACE INTO sib_outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (r['signal_date'],r['ticker'],MODEL,h,entry,p['trade_date'],p['close'],ret,bench_ret,
                   ret-bench_ret if ret is not None and bench_ret is not None else None,mfe,mae,below,now))
            out_n += 1
    if not args.dry_run: con.commit()
    print(json.dumps({'model_id':MODEL,'snapshots':snap_n,'outcomes':out_n,'dry_run':args.dry_run},ensure_ascii=False))
    con.close(); return 0

if __name__ == '__main__': raise SystemExit(main())
