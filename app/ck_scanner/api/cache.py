from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ck_scanner.api.queries import DB, query, rows_sql
from ck_scanner.explanations.score_explain import explain_score
from ck_scanner.scoring.registry import list_rules

CACHE_VERSION = 'dashboard_cache_v4.0'
SCORE_RUN_ID = 'setup_scores_v4.0'

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS setup_scores (
  score_id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  signal_date TEXT NOT NULL,
  setup_type TEXT,
  score_name TEXT NOT NULL,
  score_value REAL,
  grade TEXT,
  components_json TEXT NOT NULL,
  suggestions_json TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(signal_id, score_name, rule_version)
);
CREATE INDEX IF NOT EXISTS idx_setup_scores_signal ON setup_scores(signal_id);
CREATE INDEX IF NOT EXISTS idx_setup_scores_date_ticker ON setup_scores(signal_date, ticker);
CREATE INDEX IF NOT EXISTS idx_setup_scores_name ON setup_scores(score_name);

CREATE TABLE IF NOT EXISTS dashboard_cache (
  cache_id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL,
  signal_date TEXT NOT NULL,
  ticker TEXT NOT NULL,
  row_json TEXT NOT NULL,
  cache_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(signal_id, cache_version)
);
CREATE INDEX IF NOT EXISTS idx_dashboard_cache_version_date ON dashboard_cache(cache_version, signal_date);
CREATE INDEX IF NOT EXISTS idx_dashboard_cache_ticker ON dashboard_cache(ticker);
"""

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')

def migrate(db: Path = DB) -> None:
    con = sqlite3.connect(db)
    try:
        con.executescript(MIGRATION_SQL)
        con.commit()
    finally:
        con.close()

def grade(score_name: str, score_value) -> str | None:
    if score_value is None:
        return None
    try:
        s = float(score_value)
    except Exception:
        return None
    if score_name == 'PULLBACK_QUALITY':
        if s >= 75: return 'Đẹp'
        if s >= 60: return 'Theo dõi'
        return 'Yếu'
    if score_name == 'B_ACCUMULATION':
        if s >= 17: return 'Nền mạnh'
        if s >= 14: return 'Nền ổn'
        return 'Nền yếu'
    if score_name == 'DECISION_SCORE':
        if s >= 110: return 'Ưu tiên cao'
        if s >= 90: return 'Theo dõi'
        return 'Thấp'
    return None

def score_value_for(row: dict, score_name: str):
    return {
        'DECISION_SCORE': row.get('decision_score'),
        'PULLBACK_QUALITY': row.get('pullback_quality_score'),
        'B_ACCUMULATION': row.get('b_accumulation_score'),
    }.get(score_name)

def rebuild_cache(db: Path = DB, cache_version: str = CACHE_VERSION) -> dict:
    migrate(db)
    rows = query(rows_sql('', order='ds.signal_date DESC, final_rank_score DESC, quality_score DESC, decision_score DESC', limit=100000))
    created = now_iso()
    con = sqlite3.connect(db)
    try:
        con.execute('BEGIN')
        for row in rows:
            signal_id = row.get('signal_id')
            if not signal_id:
                # rows_sql now expected to include signal_id; skip defensively if absent
                continue
            row_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
            con.execute(
                '''INSERT OR REPLACE INTO dashboard_cache
                   (cache_id, signal_id, signal_date, ticker, row_json, cache_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (f'{cache_version}:{signal_id}', signal_id, row.get('signal_date'), row.get('ticker'), row_json, cache_version, created),
            )
            for rule in list_rules():
                score_name = rule['rule_id']
                val = score_value_for(row, score_name)
                if val is None:
                    continue
                ex = explain_score(row, score_name)
                rule_version = ex.get('rule_version') or rule.get('rule_version_id')
                con.execute(
                    '''INSERT OR REPLACE INTO setup_scores
                       (score_id, signal_id, ticker, signal_date, setup_type, score_name, score_value, grade,
                        components_json, suggestions_json, rule_version, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        f'{signal_id}:{score_name}:{rule_version}', signal_id, row.get('ticker'), row.get('signal_date'),
                        row.get('setup_type'), score_name, val, grade(score_name, val),
                        json.dumps(ex.get('components') or [], ensure_ascii=False, sort_keys=True),
                        json.dumps(ex.get('suggestions') or {}, ensure_ascii=False, sort_keys=True),
                        rule_version, created,
                    ),
                )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {'cache_version': cache_version, 'rows': len(rows), 'created_at': created}

def cache_stats(db: Path = DB, cache_version: str = CACHE_VERSION) -> dict:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        tables = [r['name'] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if 'dashboard_cache' not in tables:
            return {'cache_version': cache_version, 'ready': False, 'rows': 0, 'setup_scores': 0}
        r = con.execute('SELECT COUNT(*) rows, MAX(created_at) created_at FROM dashboard_cache WHERE cache_version=?', (cache_version,)).fetchone()
        s = con.execute('SELECT COUNT(*) setup_scores, MAX(created_at) setup_created_at FROM setup_scores').fetchone()
        return {'cache_version': cache_version, 'ready': bool(r['rows']), 'rows': r['rows'], 'created_at': r['created_at'], 'setup_scores': s['setup_scores'], 'setup_created_at': s['setup_created_at']}
    finally:
        con.close()

def _load_cache_rows(where_sql: str = '', params=(), order_sql: str = 'decision_score DESC, action_score DESC', limit: int = 200, db: Path = DB, cache_version: str = CACHE_VERSION) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        sql = f'''
SELECT row_json
FROM dashboard_cache
WHERE cache_version = ? {where_sql}
ORDER BY {order_sql}
LIMIT ?
'''
        rows = []
        for r in con.execute(sql, [cache_version, *params, int(limit)]).fetchall():
            rows.append(json.loads(r['row_json']))
        return rows
    finally:
        con.close()

def build_cache_where(qs) -> tuple[str, list]:
    date=(qs.get('date') or [''])[0]
    start=(qs.get('start') or [date])[0]
    end=(qs.get('end') or [date])[0]
    setup=(qs.get('setup') or [''])[0]
    label=(qs.get('label') or [''])[0]
    sector=(qs.get('sector') or [''])[0]
    ticker=(qs.get('ticker') or [''])[0].strip().upper()
    action=(qs.get('action') or [''])[0]
    breakout=(qs.get('breakout') or [''])[0]
    min_score=(qs.get('min_score') or [''])[0]
    min_rr=(qs.get('min_rr') or [''])[0]
    max_risk=(qs.get('max_risk') or [''])[0]
    min_liquidity=(qs.get('min_liquidity') or [''])[0]
    min_sector=(qs.get('min_sector') or [''])[0]
    preset=(qs.get('preset') or [''])[0]
    where=[]; params=[]
    def json_col(name): return f"json_extract(row_json, '$.{name}')"
    if start:
        where.append('signal_date >= ?'); params.append(start)
    if end:
        where.append('signal_date <= ?'); params.append(end)
    if setup:
        where.append(f'{json_col("setup_type")} = ?'); params.append(setup)
    if label:
        where.append(f'{json_col("buy_zone_label")} = ?'); params.append(label)
    if sector:
        where.append(f'{json_col("sector")} = ?'); params.append(sector)
    if ticker:
        where.append('ticker LIKE ?'); params.append(f'%{ticker}%')
    if action:
        where.append(f'{json_col("action_label")} = ?'); params.append(action)
    if breakout:
        if breakout == 'triggered': where.append(f'{json_col("breakout_status")} = ?'); params.append('Đã vượt mốc breakout')
        elif breakout == 'waiting': where.append(f'{json_col("breakout_status")} LIKE ?'); params.append('Chờ giá đóng cửa >%')
        elif breakout == 'missing': where.append(f'{json_col("breakout_status")} = ?'); params.append('Chưa đủ dữ liệu 20 phiên')
    for raw, col in [(min_score,'decision_score'),(min_rr,'reward_risk'),(max_risk,'risk_pct'),(min_liquidity,'avg_volume5_latest'),(min_sector,'sector_score')]:
        if raw:
            try: val=float(raw)
            except ValueError: continue
            op='<=' if col=='risk_pct' else '>='
            where.append(f'CAST({json_col(col)} AS REAL) {op} ?'); params.append(val)
    if preset:
        if preset == 'actionable':
            where.append(f'CAST({json_col("decision_score")} AS REAL) >= ?'); params.append(65)
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
            where.append(f'CAST({json_col("avg_volume5_latest")} AS REAL) >= ?'); params.append(1000000)
        elif preset == 'backtest_edge':
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(6)
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("avg_volume5_latest")} AS REAL) >= ?'); params.append(1000000)
            where.append(f'''(
              ({json_col("setup_type")} LIKE '%Pullback%' AND CAST({json_col("relative_volume")} AS REAL) BETWEEN 1.0 AND 3.0 AND CAST({json_col("rsi14")} AS REAL) BETWEEN 55 AND 75)
              OR ({json_col("setup_type")} LIKE '%Tích%' AND CAST({json_col("relative_volume")} AS REAL) BETWEEN 0.8 AND 2.5 AND CAST({json_col("rsi14")} AS REAL) BETWEEN 45 AND 72)
              OR ({json_col("setup_type")} LIKE '%Dòng tiền%' AND CAST({json_col("relative_volume")} AS REAL) BETWEEN 0.6 AND 2.5 AND CAST({json_col("rsi14")} AS REAL) BETWEEN 50 AND 75)
            )''')
        elif preset == 'volman_breakout':
            where.append(f'CAST({json_col("b_accumulation_score")} AS REAL) >= ?'); params.append(14)
            where.append(f'CAST({json_col("range20_pct")} AS REAL) <= ?'); params.append(12)
            where.append(f'CAST({json_col("distance_to_high20_pct")} AS REAL) <= ?'); params.append(5)
            where.append(f'CAST({json_col("vol_dry_ratio")} AS REAL) <= ?'); params.append(0.9)
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
            where.append(f'CAST({json_col("avg_volume5_latest")} AS REAL) >= ?'); params.append(1000000)
            where.append(f'CAST({json_col("sector_score")} AS REAL) >= ?'); params.append(55)
            where.append(f'({json_col("rs_rank_pct")} IS NULL OR CAST({json_col("rs_rank_pct")} AS REAL) >= ?)'); params.append(55)
            where.append(f'({json_col("setup_buy_trigger_price")} IS NULL OR CAST({json_col("entry_price")} AS REAL) <= CAST({json_col("setup_buy_trigger_price")} AS REAL) * 1.03)')
        elif preset == 'volman_retest':
            where.append(f'CAST({json_col("retest_setup_score")} AS REAL) >= ?'); params.append(60)
            where.append(f'CAST({json_col("retest_distance_pct")} AS REAL) BETWEEN ? AND ?'); params.extend([-2, 3])
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
            where.append(f'CAST({json_col("avg_volume5_latest")} AS REAL) >= ?'); params.append(1000000)
            where.append(f'CAST({json_col("sector_score")} AS REAL) >= ?'); params.append(55)
            where.append(f'({json_col("rs_rank_pct")} IS NULL OR CAST({json_col("rs_rank_pct")} AS REAL) >= ?)'); params.append(55)
        elif preset == 'breakout_retest':
            where.append(f'CAST({json_col("retest_setup_score")} AS REAL) >= ?'); params.append(60)
        elif preset == 'pullback_good':
            where.append(f'CAST({json_col("pullback_quality_score")} AS REAL) >= ?'); params.append(60)
        elif preset == 'accumulation_strong':
            where.append(f'CAST({json_col("b_accumulation_score")} AS REAL) >= ?'); params.append(14)
        elif preset == 'sector_rs':
            where.append(f'CAST({json_col("sector_score")} AS REAL) >= ?'); params.append(55)
            where.append(f'CAST({json_col("decision_score")} AS REAL) >= ?'); params.append(70)
        elif preset == 'quality_focus':
            where.append(f'CAST({json_col("quality_score")} AS REAL) >= ?'); params.append(70)
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
            where.append(f'CAST({json_col("avg_volume5_latest")} AS REAL) >= ?'); params.append(1000000)
        elif preset == 'low_false_break':
            where.append(f'CAST({json_col("false_break_risk_score")} AS REAL) <= ?'); params.append(35)
            where.append(f'CAST({json_col("quality_score")} AS REAL) >= ?'); params.append(60)
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
        elif preset == 'smart_market':
            where.append(f'CAST({json_col("quality_score")} AS REAL) >= ?'); params.append(70)
            where.append(f'CAST({json_col("false_break_risk_score")} AS REAL) <= ?'); params.append(35)
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
            where.append(f'CAST({json_col("avg_volume5_latest")} AS REAL) >= ?'); params.append(1000000)
            where.append(f'CAST({json_col("sector_score")} AS REAL) >= ?'); params.append(55)
        elif preset == 'trend_leader':
            where.append(f'CAST({json_col("rs_rank_pct")} AS REAL) >= ?'); params.append(70)
            where.append(f'CAST({json_col("sector_score")} AS REAL) >= ?'); params.append(55)
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
            where.append(f'CAST({json_col("avg_volume5_latest")} AS REAL) >= ?'); params.append(1000000)
            where.append(f'({json_col("setup_buy_trigger_price")} IS NULL OR CAST({json_col("entry_price")} AS REAL) <= CAST({json_col("setup_buy_trigger_price")} AS REAL) * 1.05)')
        elif preset == 'canslim_technical':
            where.append(f'CAST({json_col("rs_rank_pct")} AS REAL) >= ?'); params.append(75)
            where.append(f'CAST({json_col("sector_score")} AS REAL) >= ?'); params.append(55)
            where.append(f'CAST({json_col("b_accumulation_score")} AS REAL) >= ?'); params.append(14)
            where.append(f'(CAST({json_col("distance_to_high20_pct")} AS REAL) <= ? OR {json_col("distance_to_high20_pct")} IS NULL)'); params.append(8)
            where.append(f'(CAST({json_col("vol_dry_ratio")} AS REAL) <= ? OR {json_col("vol_dry_ratio")} IS NULL)'); params.append(1.0)
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
            where.append(f'CAST({json_col("avg_volume5_latest")} AS REAL) >= ?'); params.append(1000000)
        elif preset == 'vcp_compression':
            where.append(f'CAST({json_col("b_accumulation_score")} AS REAL) >= ?'); params.append(14)
            where.append(f'CAST({json_col("range20_pct")} AS REAL) <= ?'); params.append(10)
            where.append(f'CAST({json_col("distance_to_high20_pct")} AS REAL) <= ?'); params.append(5)
            where.append(f'CAST({json_col("vol_dry_ratio")} AS REAL) <= ?'); params.append(0.85)
            where.append(f'(CAST({json_col("distribution_days_20")} AS REAL) <= ? OR {json_col("distribution_days_20")} IS NULL)'); params.append(3)
            where.append(f'(CAST({json_col("rs_rank_pct")} AS REAL) >= ? OR {json_col("rs_rank_pct")} IS NULL)'); params.append(60)
            where.append(f'CAST({json_col("sector_score")} AS REAL) >= ?'); params.append(55)
        elif preset == 'retest_priority':
            where.append(f'CAST({json_col("retest_setup_score")} AS REAL) >= ?'); params.append(65)
            where.append(f'CAST({json_col("retest_distance_pct")} AS REAL) BETWEEN ? AND ?'); params.extend([-1.5, 2.5])
            where.append(f'CAST({json_col("reward_risk")} AS REAL) >= ?'); params.append(1.5)
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(8)
            where.append(f'CAST({json_col("sector_score")} AS REAL) >= ?'); params.append(55)
            where.append(f'(CAST({json_col("rs_rank_pct")} AS REAL) >= ? OR {json_col("rs_rank_pct")} IS NULL)'); params.append(60)
        elif preset == 'no_chase':
            where.append(f'{json_col("action_label")} <> ?'); params.append('Không mua đuổi')
            where.append(f'CAST({json_col("risk_pct")} AS REAL) <= ?'); params.append(10)
    return (' AND ' + ' AND '.join(where) if where else ''), params

def cache_rows(qs, order_sql: str = 'final_rank_score DESC, quality_score DESC, false_break_risk_score ASC, decision_score DESC', limit: int = 200) -> list[dict]:
    where, params = build_cache_where(qs)
    # whitelist order expressions used by dashboard endpoints
    allowed = {
        'decision_score DESC, action_score DESC': "CAST(json_extract(row_json, '$.decision_score') AS REAL) DESC, CAST(json_extract(row_json, '$.action_score') AS REAL) DESC",
        'final_rank_score DESC, quality_score DESC, false_break_risk_score ASC, decision_score DESC': "CAST(json_extract(row_json, '$.final_rank_score') AS REAL) DESC, CAST(json_extract(row_json, '$.quality_score') AS REAL) DESC, CAST(json_extract(row_json, '$.false_break_risk_score') AS REAL) ASC, CAST(json_extract(row_json, '$.decision_score') AS REAL) DESC",
        'signal_date DESC, action_score DESC': "signal_date DESC, CAST(json_extract(row_json, '$.action_score') AS REAL) DESC",
    }
    order = allowed.get(order_sql, allowed['final_rank_score DESC, quality_score DESC, false_break_risk_score ASC, decision_score DESC'])
    return _load_cache_rows(where, params, order, limit)

def compare_cache_with_query(qs, query_rows: list[dict], limit: int = 20) -> dict:
    cached = cache_rows(qs, limit=limit)
    def sig(rows):
        return [(r.get('signal_id'), r.get('ticker'), r.get('signal_date'), r.get('decision_score')) for r in rows]
    return {
        'cache_rows': len(cached),
        'query_rows': len(query_rows),
        'same_signature': sig(cached) == sig(query_rows),
        'cache_signature': sig(cached)[:5],
        'query_signature': sig(query_rows)[:5],
    }

def freshness(db: Path = DB, cache_version: str = CACHE_VERSION) -> dict:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        latest = con.execute('SELECT MAX(signal_date) latest_signal_date, COUNT(*) total_signals FROM daily_signals').fetchone()
        cache = con.execute('''
            SELECT MAX(signal_date) latest_cache_signal_date, COUNT(*) cache_rows, MAX(created_at) cache_created_at
            FROM dashboard_cache
            WHERE cache_version=?
        ''', (cache_version,)).fetchone()
        latest_date = latest['latest_signal_date'] if latest else None
        cache_date = cache['latest_cache_signal_date'] if cache else None
        total_signals = latest['total_signals'] if latest else 0
        cache_rows_count = cache['cache_rows'] if cache else 0
        ready = bool(cache_rows_count) and cache_date == latest_date and cache_rows_count >= total_signals
        reason = 'fresh' if ready else 'stale_or_incomplete'
        return {
            'cache_version': cache_version,
            'ready': ready,
            'reason': reason,
            'latest_signal_date': latest_date,
            'latest_cache_signal_date': cache_date,
            'total_signals': total_signals,
            'cache_rows': cache_rows_count,
            'cache_created_at': cache['cache_created_at'] if cache else None,
        }
    finally:
        con.close()
