#!/usr/bin/env python3
from __future__ import annotations
import json, sqlite3, os, subprocess, glob, signal, shutil
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

DB=Path('/root/.openclaw/workspace/CK/db/ck_signals.sqlite')
ACTION_SNAPSHOT_DIR=Path('/root/.openclaw/workspace/CK/action_board_snapshots')
HOST='127.0.0.1'
PORT=8765
ROOT=Path('/root/.openclaw/workspace')
RUN_OHLCV=ROOT/'skills/vietnam-stock-technical-scanner/scripts/run_ohlcv_close_daily.sh'
RUN_SCAN=ROOT/'skills/vietnam-stock-technical-scanner/scripts/scan_new_universe.py'
RUN_ICHIMOKU=ROOT/'skills/vietnam-stock-technical-scanner/scripts/run_ichimoku_mtf_daily.sh'
RUN_ICHIMOKU_BACKTEST=ROOT/'skills/vietnam-stock-technical-scanner/scripts/backtest_ichimoku_ticker_horizons_tp4_sl10.py'
RUN_FIXED_FILTER_BACKTEST=ROOT/'skills/vietnam-stock-technical-scanner/scripts/backtest_fixed_filter_tplus_tp4_sl10.py'
RUN_TRADING_PLAN=ROOT/'skills/vietnam-stock-technical-scanner/scripts/export_daily_trading_plan.py'
PY=ROOT/'CK/.venv/bin/python'
REFRESH_JOB={'process':None,'date':None,'started_at':None,'log':None,'cache_rebuilt':False}
SCAN_JOB={'process':None,'date':None,'started_at':None,'log':None,'cache_rebuilt':False}
ICHIMOKU_JOB={'process':None,'date':None,'started_at':None,'log':None}
DAILY_BACKTEST_JOB={'process':None,'date':None,'preset':None,'started_at':None,'log':None,'out':None}

import sys
SRC = ROOT / 'skills/vietnam-stock-technical-scanner/src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from ck_scanner.api.queries import add_change_pct, build_where, query, rows_sql, scalar, BASE_CTE
from ck_scanner.api.cache import CACHE_VERSION, cache_rows, cache_stats, compare_cache_with_query, freshness as cache_freshness, migrate as migrate_cache, rebuild_cache
from ck_scanner.explanations.score_explain import explain_score
from ck_scanner.scoring.registry import list_rules

APP_VERSION = '7.5.1'
DASHBOARD_VERSION = '7.5.1'
DASHBOARD_CODENAME = 'stock-decision-intelligence'
DASHBOARD_TEMPLATE = ROOT / 'skills/vietnam-stock-technical-scanner/src/ck_scanner/web/templates/dashboard.html'
STATIC_ROOT = ROOT / 'skills/vietnam-stock-technical-scanner/src/ck_scanner/web/static'


def load_dashboard_html() -> str:
    html = DASHBOARD_TEMPLATE.read_text(encoding='utf-8')
    return html.replace('Dashboard v3.1', f'Dashboard v{DASHBOARD_VERSION}')


def static_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == '.css':
        return 'text/css; charset=utf-8'
    if suffix == '.js':
        return 'application/javascript; charset=utf-8'
    if suffix == '.json':
        return 'application/json; charset=utf-8'
    return 'application/octet-stream'

def bangkok_today():
    return subprocess.check_output(['bash','-lc','TZ=Asia/Bangkok date +%F'], text=True).strip()

def find_external_ichimoku_process(day: str | None = None):
    """Detect Ichimoku scans started outside this web_dashboard process.

    Dashboard jobs are normally tracked in ICHIMOKU_JOB, but a restart or shell-run scan
    loses that in-memory handle. This keeps the UI from showing idle while the scanner is
    still running and prevents duplicate scans for the same day.
    """
    try:
        out = subprocess.check_output(['ps','-eo','pid=,args='], text=True)
    except Exception:
        return None
    needle = 'scan_ichimoku_mtf.py'
    runner = 'run_ichimoku_mtf_daily.sh'
    self_pid = os.getpid()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmd = parts[1]
        if pid == self_pid or 'grep' in cmd:
            continue
        if needle not in cmd and runner not in cmd:
            continue
        if day and (f'--date {day}' not in cmd and f'DATE_OVERRIDE={day}' not in cmd and runner not in cmd):
            continue
        return {'pid': pid, 'cmd': cmd}
    return None


def rebuild_cache_after_job(job_name: str):
    try:
        result = rebuild_cache()
        return f"\n[cache] Rebuilt after {job_name}: rows={result.get('rows')} version={result.get('cache_version')} at {result.get('created_at')}"
    except Exception as e:
        return f"\n[cache] Rebuild failed after {job_name}: {e}"


def latest_ichimoku_report():
    patterns = [
        'ichimoku_1h_t65_k129_breakout_v1_3_top*.xlsx',
        'ichimoku_mtf_v1_2_top20_*.xlsx',  # legacy reports
    ]
    files = []
    for pattern in patterns:
        files.extend((ROOT/'CK/reports').glob(pattern))
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None

def ensure_ma20_ema_schema():
    con = sqlite3.connect(DB)
    con.execute('''
CREATE TABLE IF NOT EXISTS ma20_ema_signals (
  scan_date TEXT NOT NULL,
  ticker TEXT NOT NULL,
  close REAL,
  ema99 REAL,
  ema200 REAL,
  ema_gap_pct REAL,
  ma20 REAL,
  vol_ma20 REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(scan_date, ticker)
)
''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_ma20_date ON ma20_ema_signals(scan_date)')
    con.commit(); return con


def ensure_ichimoku_schema():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    con.execute("""
CREATE TABLE IF NOT EXISTS ichimoku_mtf_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scan_date TEXT NOT NULL, ticker TEXT NOT NULL, ok_tf_count INTEGER, ok_timeframes TEXT,
  rank_score REAL, mtf_score REAL, action_status TEXT, current_price REAL, entry_low REAL, entry_high REAL, trigger_price REAL,
  stoploss REAL, risk_pct REAL, target_near REAL, target_extended REAL, reward_risk_near REAL, no_chase_above REAL,
  confirm_condition TEXT, cancel_condition TEXT, volume_1d REAL, avg_volume30_1d REAL, avg_value30_est REAL, volume_confirm TEXT,
  status_15m TEXT, score_15m REAL, dist_t65_15m_pct REAL, status_1h TEXT, score_1h REAL, dist_t65_1h_pct REAL,
  status_1d TEXT, score_1d REAL, dist_t65_1d_pct REAL, tenkan9_d REAL, kijun17_d REAL, tenkan65_d REAL, kijun129_d REAL,
  relvol_15m REAL, relvol_1h REAL, relvol_1d REAL, reason TEXT, raw_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  _main_tf TEXT DEFAULT '1H',
  UNIQUE(scan_date, ticker)
)
""")
    for col in [('_main_tf','TEXT')]:
        try: con.execute(f'ALTER TABLE ichimoku_mtf_signals ADD COLUMN {col[0]} {col[1]}')
        except sqlite3.OperationalError: pass
    con.execute("CREATE INDEX IF NOT EXISTS idx_ichimoku_main_tf ON ichimoku_mtf_signals(_main_tf)")
    con.commit(); return con

def _sqlite_has_key(r, key):
    try:
        return key in r.keys()
    except Exception:
        return False

def sqlite_to_ui_row(r):
    scan_price = r['current_price']
    latest_close = r['latest_close'] if _sqlite_has_key(r, 'latest_close') else None
    latest_trade_date = r['latest_trade_date'] if _sqlite_has_key(r, 'latest_trade_date') else None
    latest_price_created_at = r['latest_price_created_at'] if _sqlite_has_key(r, 'latest_price_created_at') else None
    latest_price_source = r['latest_price_source'] if _sqlite_has_key(r, 'latest_price_source') else None
    display_price = latest_close if latest_close is not None else scan_price
    price_source = 'Giá đóng cửa mới nhất' if latest_close is not None else 'Giá lúc lọc'
    price_diff_pct = None
    try:
        if latest_close is not None and scan_price:
            price_diff_pct = round((float(latest_close) / float(scan_price) - 1) * 100, 2)
    except Exception:
        price_diff_pct = None
    return {
      'Mã': r['ticker'], 'Số khung đạt': r['ok_tf_count'], 'Khung đạt': r['ok_timeframes'],
      'Điểm xếp hạng v1.3': r['rank_score'], 'Điểm Ichimoku 1H v1.3': r['mtf_score'], 'Trạng thái hành động': r['action_status'],
      'Giá hiện tại': display_price, 'Giá lúc lọc': scan_price, 'Giá mới nhất': latest_close, 'Ngày giá mới nhất': latest_trade_date, 'Nguồn giá': price_source, 'File/API giá': latest_price_source, 'Giá cập nhật lúc': latest_price_created_at, 'Lệch giá %': price_diff_pct, 'Vùng mua thấp': r['entry_low'], 'Vùng mua cao/trigger': r['entry_high'], 'Giá trigger': r['trigger_price'],
      'Stoploss': r['stoploss'], 'Rủi ro %': r['risk_pct'], 'Mục tiêu gần': r['target_near'], 'Mục tiêu mở rộng': r['target_extended'],
      'Lãi/Rủi ro mục tiêu gần': r['reward_risk_near'], 'Không mua đuổi nếu >': r['no_chase_above'], 'Điều kiện xác nhận': r['confirm_condition'],
      'Điều kiện huỷ': r['cancel_condition'], 'Volume 1D': r['volume_1d'], 'Volume TB30 1D': r['avg_volume30_1d'],
      'GTGD TB30 ước tính': r['avg_value30_est'], 'Volume xác nhận': r['volume_confirm'], 'Trạng thái 15m': r['status_15m'],
      'Điểm 15m': r['score_15m'], 'KC T65 15m %': r['dist_t65_15m_pct'], 'Trạng thái 1h': r['status_1h'], 'Điểm 1h': r['score_1h'],
      'KC T65 1h %': r['dist_t65_1h_pct'], 'Trạng thái 1D': r['status_1d'], 'Điểm 1D': r['score_1d'], 'KC T65 1D %': r['dist_t65_1d_pct'],
      'Tenkan9 D': r['tenkan9_d'], 'Kijun17 D': r['kijun17_d'], 'Tenkan65 D': r['tenkan65_d'], 'Kijun129 D': r['kijun129_d'],
      'Volume tương đối 15m': r['relvol_15m'], 'Volume tương đối 1h': r['relvol_1h'], 'Volume tương đối 1D': r['relvol_1d'], 'Lý do': r['reason'], 'Timing score': r['timing_score'] if 'timing_score' in r.keys() else None, 'Timing label': r['timing_label'] if 'timing_label' in r.keys() else None, 'D1 setup score': r['d1_setup_score'] if 'd1_setup_score' in r.keys() else None, '15M timing score': r['m15_timing_score'] if 'm15_timing_score' in r.keys() else None, 'Volume score': r['timing_volume_score'] if 'timing_volume_score' in r.keys() else None, 'No-chase score': r['no_chase_score'] if 'no_chase_score' in r.keys() else None
    }

def load_ichimoku_top20(qs=None):
    qs = qs or {}
    con = ensure_ichimoku_schema()
    date = (qs.get('date') or qs.get('end') or [''])[0] if qs else ''
    tf = (qs.get('tf') or [''])[0] if qs else ''
    if not date:
        # Lấy ngày có dữ liệu cho đúng tf
        if tf == '1D':
            row = con.execute("SELECT MAX(scan_date) d FROM ichimoku_mtf_signals WHERE _main_tf='1D'").fetchone()
        elif tf == '1H':
            row = con.execute("SELECT MAX(scan_date) d FROM ichimoku_mtf_signals WHERE _main_tf='1H' OR _main_tf IS NULL").fetchone()
        else:
            row = con.execute('SELECT MAX(scan_date) d FROM ichimoku_mtf_signals').fetchone()
        date = row['d'] if row else None
    if not date:
        # Gợi ý chuyển khung nếu tf hiện tại không có dữ liệu
        hint = ''
        alt_tf = '1D' if tf == '1H' else '1H'
        alt_row = con.execute('SELECT MAX(scan_date) d FROM ichimoku_mtf_signals WHERE _main_tf=?', (alt_tf,)).fetchone()
        if alt_row and alt_row['d']:
            hint = f' Khung {tf} chưa có dữ liệu. Chuyển sang khung {alt_tf} (có dữ liệu {alt_row["d"]}) để xem kết quả.'
        con.close(); return {'source':'sqlite','date':None,'rows':[], 'summary':[], 'message':'Chưa có dữ liệu SQLite. Bấm Quét Ichimoku để tạo.' + hint}
    action = (qs.get('action') or [''])[0] if qs else ''
    ticker = ((qs.get('ticker') or [''])[0] if qs else '').strip().upper()
    where=['i.scan_date=?']; params=[date]
    if action: where.append('i.action_status=?'); params.append(action)
    if ticker: where.append('i.ticker=?'); params.append(ticker)
    if tf == '1D':
        where.append('i._main_tf = ?'); params.append('1D')
        # D1: chỉ lấy mã đạt thực tế (ok_tf_count > 0)
        where.append('i.ok_tf_count > 0')
    elif tf == '1H':
        where.append('(i._main_tf = ? OR i._main_tf IS NULL)'); params.append('1H')
    sql='''
SELECT i.*,
       CASE WHEN dp.close IS NOT NULL AND i.current_price > 1000 AND dp.close < 1000 THEN dp.close * 1000
            WHEN dp.close IS NOT NULL THEN dp.close
            ELSE NULL END AS latest_close,
       dp.trade_date AS latest_trade_date,
       dp.source AS latest_price_source,
       dp.created_at AS latest_price_created_at
FROM ichimoku_mtf_signals i
LEFT JOIN daily_prices dp
  ON dp.ticker = i.ticker
 AND dp.trade_date = (
      SELECT MAX(p2.trade_date) FROM daily_prices p2
      WHERE p2.ticker = i.ticker AND p2.trade_date <= i.scan_date
 )
WHERE ''' + ' AND '.join(where) + '''
ORDER BY COALESCE(i.timing_score,0) DESC, i.rank_score DESC, i.ok_tf_count DESC LIMIT 20'''
    rows=[sqlite_to_ui_row(r) for r in con.execute(sql, params).fetchall()]
    # Add _main_tf to returned data for UI detection
    for row in rows:
        row['_main_tf'] = tf or '1H'
    sum_where=['scan_date=?']; sum_params=[date]
    if tf == '1D':
        sum_where.append('_main_tf = ?'); sum_params.append('1D')
    elif tf == '1H':
        sum_where.append('(_main_tf = ? OR _main_tf IS NULL)'); sum_params.append('1H')
    summary=[dict(r) for r in con.execute('SELECT action_status AS "Trạng thái hành động", COUNT(*) AS "Số_mã", ROUND(AVG(rank_score),1) AS "Điểm_TB" FROM ichimoku_mtf_signals WHERE ' + ' AND '.join(sum_where) + ' GROUP BY action_status ORDER BY "Số_mã" DESC',sum_params).fetchall()]
    dates_where=[]; dates_params=[]
    if tf == '1D':
        dates_where.append('_main_tf=?'); dates_params.append('1D')
    elif tf == '1H':
        dates_where.append('(_main_tf=? OR _main_tf IS NULL)'); dates_params.append('1H')
    dates=[dict(r) for r in con.execute('SELECT scan_date, COUNT(*) total FROM ichimoku_mtf_signals' + (' WHERE ' + ' AND '.join(dates_where) if dates_where else '') + ' GROUP BY scan_date ORDER BY scan_date DESC LIMIT 60',dates_params).fetchall()]
    # Thêm hint khi có date nhưng 0 rows - gợi ý chuyển khung
    extra_msg = ''
    if len(rows) == 0 and date:
        alt_tf = '1D' if tf == '1H' else '1H'
        alt_cnt = con.execute('SELECT COUNT(*) FROM ichimoku_mtf_signals WHERE scan_date=? AND _main_tf=?', (date, alt_tf)).fetchone()[0]
        if alt_cnt and alt_cnt > 0:
            extra_msg = f' Khung {tf} không có mã đạt. Chuyển sang khung {alt_tf} (có {alt_cnt} mã) để xem kết quả.'
    con.close(); return {'source':'sqlite','date':date,'rows':rows,'summary':summary,'dates':dates, 'tf': tf or '1H', 'message': extra_msg}

def has_ichimoku_rows(day: str, tf: str = '1H') -> int:
    try:
        con = sqlite3.connect(DB)
        n = con.execute('SELECT COUNT(*) FROM ichimoku_mtf_signals WHERE scan_date=? AND COALESCE(_main_tf,?) = ?', (day, tf, tf)).fetchone()[0]
        con.close()
        return int(n or 0)
    except Exception:
        return 0

def ichimoku_status():
    proc=ICHIMOKU_JOB.get('process')
    day=ICHIMOKU_JOB.get('date') or bangkok_today()
    log=ICHIMOKU_JOB.get('log') or str(ROOT/f'CK/logs/ichimoku_mtf_scan_{day}.log')
    tail=''
    try:
        lp=Path(log)
        if lp.exists(): tail=''.join(lp.read_text(errors='replace').splitlines(True)[-80:])
    except Exception as e:
        tail=f'Không đọc được log: {e}'
    if proc and proc.poll() is None:
        return {'status':'running','date':day,'message':f'Đang quét Ichimoku 1H T65/K129 Breakout v1.3 cho {day}.', 'pid': proc.pid, 'log_tail':tail}
    external=find_external_ichimoku_process(day)
    if external:
        return {'status':'running','date':day,'message':f'Đang quét Ichimoku 1H T65/K129 Breakout v1.3 cho {day} bằng process ngoài dashboard.', 'pid': external['pid'], 'external': True, 'log_tail':tail}
    if proc:
        code=proc.returncode; ICHIMOKU_JOB['process']=None
        return {'status':'success' if code==0 else 'failed','date':day,'message':('Quét Ichimoku hoàn tất.' if code==0 else f'Quét Ichimoku lỗi, exit code {code}.'),'log_tail':tail}
    return {'status':'idle','date':day,'message':'Chưa có job Ichimoku đang chạy.', 'log_tail':tail}

def scan_status():
    proc=SCAN_JOB.get('process')
    day=SCAN_JOB.get('date') or bangkok_today()
    log=SCAN_JOB.get('log') or str(ROOT/f'CK/logs/scan_new_universe_{day}.log')
    tail=''
    try:
        lp=Path(log)
        if lp.exists(): tail=''.join(lp.read_text(errors='replace').splitlines(True)[-80:])
    except Exception as e:
        tail=f'Không đọc được log: {e}'
    if proc and proc.poll() is None:
        return {'status':'running','date':day,'message':f'Đang quét mã mới ngày {day}. Vui lòng đợi...', 'log_tail':tail}
    if proc:
        code=proc.returncode; SCAN_JOB['process']=None
        status='success' if code==0 else 'failed'
        msg=f'Quét mã mới ngày {day} hoàn tất.' if code==0 else f'Quét mã mới ngày {day} lỗi, exit code {code}.'
        if code==0 and not SCAN_JOB.get('cache_rebuilt'):
            cache_msg = rebuild_cache_after_job('scan_new')
            SCAN_JOB['cache_rebuilt']=True
            msg += ' Đã rebuild dashboard cache.'
            tail += cache_msg
        return {'status':status,'date':day,'message':msg,'log_tail':tail}
    return {'status':'idle','date':day,'message':'Chưa có job quét mã mới đang chạy.', 'log_tail':tail}

def load_data_status():
    proc=REFRESH_JOB.get('process')
    day=REFRESH_JOB.get('date') or bangkok_today()
    log=REFRESH_JOB.get('log') or str(ROOT/f'CK/logs/ohlcv_close_{day}.log')
    tail=''
    try:
        lp=Path(log)
        if lp.exists():
            tail=''.join(lp.read_text(errors='replace').splitlines(True)[-60:])
    except Exception as e:
        tail=f'Không đọc được log: {e}'
    if proc and proc.poll() is None:
        return {'status':'running','date':day,'message':f'Đang nạp data ngày {day}. Vui lòng đợi...', 'log_tail':tail}
    if proc:
        code=proc.returncode
        REFRESH_JOB['process']=None
        status='success' if code==0 else 'failed'
        msg=f'Nạp data ngày {day} hoàn tất.' if code==0 else f'Nạp data ngày {day} lỗi, exit code {code}.'
        if code==0 and not REFRESH_JOB.get('cache_rebuilt'):
            cache_msg = rebuild_cache_after_job('load_data')
            REFRESH_JOB['cache_rebuilt']=True
            msg += ' Đã rebuild dashboard cache.'
            tail += cache_msg
        return {'status':status,'date':day,'message':msg,'log_tail':tail}
    return {'status':'idle','date':day,'message':'Chưa có job nạp data đang chạy.', 'log_tail':tail}



def daily_backtest_status():
    proc=DAILY_BACKTEST_JOB.get('process')
    day=DAILY_BACKTEST_JOB.get('date') or bangkok_today()
    preset=DAILY_BACKTEST_JOB.get('preset') or ''
    out=DAILY_BACKTEST_JOB.get('out') or str(ROOT/'CK/backtests'/f'daily_preset_backtest_{day}_{preset or "all"}.json')
    log=DAILY_BACKTEST_JOB.get('log') or str(ROOT/'CK/logs'/f'daily_preset_backtest_{day}_{preset or "all"}.log')
    tail=''
    try:
        lp=Path(log)
        if lp.exists():
            tail=''.join(lp.read_text(errors='replace').splitlines(True)[-80:])
    except Exception as e:
        tail=f'Không đọc được log: {e}'
    if proc and proc.poll() is None:
        return {'status':'running','date':day,'preset':preset,'message':f'Đang chạy backtest ngày {day} cho preset {preset or "Tất cả"}.', 'log_tail':tail, 'out':out}
    data=None
    if Path(out).exists():
        try:
            data=json.loads(Path(out).read_text(encoding='utf-8'))
        except Exception as e:
            data={'error':f'Không đọc được file kết quả: {e}'}
    if proc:
        code=proc.returncode; DAILY_BACKTEST_JOB['process']=None
        return {'status':'success' if code==0 else 'failed','date':day,'preset':preset,'message':('Backtest ngày hoàn tất.' if code==0 else f'Backtest ngày lỗi, exit code {code}.'),'log_tail':tail,'out':out,'result':data}
    return {'status':'idle','date':day,'preset':preset,'message':'Chưa có job backtest ngày đang chạy.', 'log_tail':tail, 'out':out, 'result':data}

def market_regime_snapshot():
    idx = query("""
SELECT trade_date,
       CASE WHEN close IS NOT NULL AND close < 1000 THEN close*1000 ELSE close END AS close
FROM daily_prices
WHERE ticker IN ('VNINDEX','VNINDEX.VN','^VNINDEX','VN30','VN30INDEX') AND close IS NOT NULL
ORDER BY trade_date DESC
LIMIT 80
""")
    idx = list(reversed(idx))
    closes = [float(r['close']) for r in idx if r.get('close') is not None]
    latest_date = idx[-1]['trade_date'] if idx else None
    latest_close = closes[-1] if closes else None
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    ret5 = (latest_close / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None
    ret20 = (latest_close / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else None
    breadth = scalar(f"""
{BASE_CTE}
SELECT COUNT(*) total,
       SUM(CASE WHEN ds.rs_rank_pct >= 60 THEN 1 ELSE 0 END) rs_strong,
       SUM(CASE WHEN ds.sector_score >= 55 THEN 1 ELSE 0 END) sector_supported,
       SUM(CASE WHEN (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
         + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
         + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
         + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
         + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
         + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
         + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
         + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
         + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
         + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) >= 70 THEN 1 ELSE 0 END) quality_high,
       SUM(CASE WHEN (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
         + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
         + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
         + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
         + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
         + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
         + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) <= 35 THEN 1 ELSE 0 END) low_false_break,
       COUNT(DISTINCT CASE WHEN ds.sector_score >= 55 THEN ds.sector END) strong_sectors
FROM ranked ds
WHERE ds.signal_date = (SELECT MAX(signal_date) FROM daily_signals)
""")
    total = float(breadth.get('total') or 0)
    rs_pct = (breadth.get('rs_strong') or 0) / total * 100 if total else 0
    sector_pct = (breadth.get('sector_supported') or 0) / total * 100 if total else 0
    quality_pct = (breadth.get('quality_high') or 0) / total * 100 if total else 0
    low_fb_pct = (breadth.get('low_false_break') or 0) / total * 100 if total else 0
    score = 0
    score += 20 if latest_close and ma20 and latest_close > ma20 else 8
    score += 15 if latest_close and ma50 and latest_close > ma50 else 6
    score += 15 if ret5 is not None and ret5 > 0 else 6
    score += 10 if ret20 is not None and ret20 > 0 else 4
    score += 15 if rs_pct >= 45 else 10 if rs_pct >= 30 else 5
    score += 10 if sector_pct >= 45 else 6 if sector_pct >= 30 else 3
    score += 10 if quality_pct >= 25 else 6 if quality_pct >= 15 else 3
    score += 5 if low_fb_pct >= 50 else 3 if low_fb_pct >= 35 else 1
    regime = 'Bullish' if score >= 70 else 'Neutral' if score >= 50 else 'Defensive'
    strategy = {
      'Bullish': 'Có thể ưu tiên Quality focus, Dòng tiền và breakout không xa trigger; vẫn tránh mua đuổi.',
      'Neutral': 'Ưu tiên Low false break, tích lũy/retest/pullback đẹp; mua thăm dò, chờ xác nhận.',
      'Defensive': 'Phòng thủ: chỉ giữ RS cao + Sector mạnh + risk thấp; hạn chế mua mới, ưu tiên quan sát.'
    }[regime]
    return {
      'latest_date': latest_date, 'vnindex_close': latest_close, 'ma20': ma20, 'ma50': ma50,
      'return_5d_pct': ret5, 'return_20d_pct': ret20,
      'market_score': round(score,2), 'regime': regime, 'strategy': strategy,
      'breadth': {**breadth, 'rs_strong_pct': round(rs_pct,2), 'sector_supported_pct': round(sector_pct,2), 'quality_high_pct': round(quality_pct,2), 'low_false_break_pct': round(low_fb_pct,2)}
    }


def action_status_for_row(r, market_regime='Neutral'):
    decision=float(r.get('decision_score') or 0)
    quality=float(r.get('quality_score') or 0)
    false_break=float(r.get('false_break_risk_score') or 0)
    rr=float(r.get('reward_risk') or 0)
    risk=float(r.get('risk_pct') or 999)
    trigger=r.get('setup_buy_trigger_price')
    price=r.get('entry_price') or r.get('display_price')
    sector=float(r.get('sector_score') or 0)
    rs=float(r.get('rs_rank_pct') or 0)
    far_trigger=False
    try:
        far_trigger = bool(trigger and price and float(price) > float(trigger) * 1.03)
    except Exception:
        far_trigger = False
    if market_regime == 'Defensive' and (quality < 75 or false_break > 25):
        return 'cancel', 'HỦY / ĐỨNG NGOÀI', 'VNINDEX Defensive, chỉ giữ setup rất mạnh'
    if false_break >= 45 or risk > 10 or rr < 1.2 or sector < 45 or (rs and rs < 45):
        return 'cancel', 'HỦY / LOẠI', 'Rủi ro cao hoặc thiếu RS/Sector/RR'
    if far_trigger:
        return 'no_chase', 'KHÔNG MUA ĐUỔI', 'Giá đã xa trigger >3%, chờ retest'
    if decision >= 75 and quality >= 75 and false_break <= 25 and rr >= 1.8 and risk <= 6 and market_regime != 'Defensive':
        return 'actionable', 'MUA THĂM DÒ / THEO TRIGGER', 'Đủ điểm hành động, vẫn chia vị thế'
    if decision >= 65 and quality >= 80 and false_break <= 15 and rr >= 2.0 and risk <= 6 and market_regime != 'Defensive':
        return 'actionable', 'MUA KHI VƯỢT TRIGGER', 'Quality/RR tốt; chỉ mua khi trigger xác nhận'
    if quality >= 60 and false_break <= 40 and rr >= 1.3 and risk <= 9:
        return 'watch', 'CHỜ XÁC NHẬN', 'Setup ổn nhưng cần trigger/volume/regime xác nhận'
    return 'watch', 'THEO DÕI', 'Chưa đủ điều kiện hành động'

ACTION_STATUS_EXPLAIN = {
    'MUA THĂM DÒ / THEO TRIGGER': {'group':'actionable','meaning':'Có thể giải ngân thăm dò nhưng phải bám trigger/stoploss, không all-in.','criteria':['Decision ≥ 75','Quality ≥ 75','False-break ≤ 25','R/R ≥ 1.8','Risk ≤ 6%','VNINDEX không Defensive'],'do':['Chia vị thế 2 lần','Ưu tiên mua quanh trigger/vùng hợp lệ','Dừng ngay nếu đóng cửa dưới stoploss/trigger'],'avoid':['Không mua đuổi quá 3% so với trigger','Không tăng tỷ trọng khi VNINDEX chuyển Defensive']},
    'MUA KHI VƯỢT TRIGGER': {'group':'actionable','meaning':'Setup chất lượng tốt nhưng lệnh chỉ hợp lệ khi giá vượt trigger xác nhận.','criteria':['Decision ≥ 65','Quality ≥ 80','False-break ≤ 15','R/R ≥ 2.0','Risk ≤ 6%','VNINDEX không Defensive'],'do':['Đặt cảnh báo trigger','Chờ đóng cửa/volume xác nhận','Giải ngân nhỏ trước nếu xác nhận rõ'],'avoid':['Không mua trước khi trigger xuất hiện nếu volume yếu','Không mua nếu mở gap xa trigger']},
    'CHỜ XÁC NHẬN': {'group':'watch','meaning':'Setup còn dùng để theo dõi, nhưng thiếu trigger/volume/regime hoặc điểm hành động chưa đủ.','criteria':['Quality ≥ 60','False-break ≤ 40','R/R ≥ 1.3','Risk ≤ 9%'],'do':['Theo dõi trigger, volume và phản ứng VNINDEX','Chỉ nâng lên actionable nếu có xác nhận'],'avoid':['Không giải ngân chỉ vì điểm đẹp','Không mua khi chưa có điểm cắt lỗ rõ']},
    'THEO DÕI': {'group':'watch','meaning':'Chưa đủ điều kiện giao dịch; chỉ giữ trong radar.','criteria':['Không rơi vào nhóm hủy nhưng chưa đủ điều kiện watch mạnh/actionable'],'do':['Chờ setup rõ hơn','So với các mã actionable/watch tốt hơn'],'avoid':['Không ưu tiên vốn']},
    'KHÔNG MUA ĐUỔI': {'group':'no_chase','meaning':'Giá đã chạy xa trigger, R/R thực chiến dễ xấu đi.','criteria':['Giá hiện tại > trigger 3%'],'do':['Chờ retest','Chỉ xem lại nếu giá quay về vùng mua hợp lệ'],'avoid':['Không FOMO','Không nâng tỷ trọng sau nến kéo mạnh']},
    'HỦY / ĐỨNG NGOÀI': {'group':'cancel','meaning':'Market regime xấu làm setup không còn phù hợp để mở mua mới.','criteria':['VNINDEX Defensive','Quality < 75 hoặc False-break > 25'],'do':['Bảo toàn vốn','Chờ VNINDEX hồi phục regime'],'avoid':['Không mở mua mới theo tín hiệu yếu']},
    'HỦY / LOẠI': {'group':'cancel','meaning':'Không đạt chuẩn tối thiểu về rủi ro, R/R, RS/Sector hoặc false-break.','criteria':['False-break ≥ 45 hoặc Risk > 10% hoặc R/R < 1.2 hoặc Sector < 45 hoặc RS < 45'],'do':['Loại khỏi danh sách mua hôm nay','Chỉ xem lại khi dữ liệu/rule ngày mới cải thiện'],'avoid':['Không cố bắt đáy','Không dùng vốn cho setup kém ưu tiên']},
}

def action_explain(status=None):
    if status:
        return {'status': status, **ACTION_STATUS_EXPLAIN.get(status, {'meaning':'Chưa có giải thích cho trạng thái này.','criteria':[],'do':[],'avoid':[]})}
    return ACTION_STATUS_EXPLAIN

def ensure_action_snapshot_schema():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    con.execute("""
CREATE TABLE IF NOT EXISTS action_board_snapshots (
  snapshot_date TEXT NOT NULL,
  ticker TEXT NOT NULL,
  action_group TEXT,
  action_status TEXT,
  entry_price REAL,
  trigger_price REAL,
  stoploss REAL,
  target REAL,
  reward_risk REAL,
  risk_pct REAL,
  decision_score REAL,
  quality_score REAL,
  false_break_risk_score REAL,
  sector_score REAL,
  rs_rank_pct REAL,
  position_size TEXT,
  cancel_condition TEXT,
  action_reason TEXT,
  market_regime TEXT,
  dashboard_version TEXT,
  raw_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(snapshot_date, ticker)
)
""")
    con.commit(); return con

def save_action_board_snapshot(board):
    date = board.get('date') or bangkok_today()
    ACTION_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    con = ensure_action_snapshot_schema()
    rows=[]
    for group_name, group in (board.get('groups') or {}).items():
        for r in group.get('rows') or []:
            rows.append((date, r.get('ticker'), group_name, r.get('action_status'), r.get('entry_price'), r.get('trigger_price'), r.get('stoploss'), r.get('target'), r.get('reward_risk'), r.get('risk_pct'), r.get('decision_score'), r.get('quality_score'), r.get('false_break_risk_score'), r.get('sector_score'), r.get('rs_rank_pct'), r.get('position_size'), r.get('cancel_condition'), r.get('action_reason'), board.get('market_regime'), board.get('dashboard_version'), json.dumps(r, ensure_ascii=False)))
    con.executemany("""
INSERT OR REPLACE INTO action_board_snapshots (
  snapshot_date,ticker,action_group,action_status,entry_price,trigger_price,stoploss,target,reward_risk,risk_pct,
  decision_score,quality_score,false_break_risk_score,sector_score,rs_rank_pct,position_size,cancel_condition,action_reason,
  market_regime,dashboard_version,raw_json
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
""", rows)
    con.commit(); con.close()
    out = ACTION_SNAPSHOT_DIR / f'{date}_action_board.json'
    out.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding='utf-8')
    latest = ACTION_SNAPSHOT_DIR / 'latest_action_board.json'
    latest.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'date': date, 'rows': len(rows), 'json_path': str(out), 'latest_path': str(latest)}

def action_snapshot_history(limit=20):
    con=ensure_action_snapshot_schema()
    rows=[dict(r) for r in con.execute("""
SELECT snapshot_date, market_regime, dashboard_version, COUNT(*) total,
       SUM(action_group='actionable') actionable, SUM(action_group='watch') watch,
       SUM(action_group='no_chase') no_chase, SUM(action_group='cancel') cancel,
       MAX(created_at) created_at
FROM action_board_snapshots
GROUP BY snapshot_date, market_regime, dashboard_version
ORDER BY snapshot_date DESC
LIMIT ?
""", [limit]).fetchall()]
    con.close(); return rows

def action_snapshot_compare(days=10):
    con=ensure_action_snapshot_schema()
    dates=[r['snapshot_date'] for r in con.execute('SELECT DISTINCT snapshot_date FROM action_board_snapshots ORDER BY snapshot_date DESC LIMIT ?', [days]).fetchall()]
    if len(dates) < 2:
        con.close(); return {'dates': dates, 'changes': [], 'message': 'Cần ít nhất 2 ngày snapshot để so sánh day-over-day.'}
    today, prev = dates[0], dates[1]
    cur={r['ticker']:dict(r) for r in con.execute('SELECT * FROM action_board_snapshots WHERE snapshot_date=?', [today]).fetchall()}
    old={r['ticker']:dict(r) for r in con.execute('SELECT * FROM action_board_snapshots WHERE snapshot_date=?', [prev]).fetchall()}
    changes=[]
    for t in sorted(set(cur)|set(old)):
        c=cur.get(t); o=old.get(t)
        if not o: kind='new'
        elif not c: kind='removed'
        elif c.get('action_group') != o.get('action_group') or c.get('action_status') != o.get('action_status'): kind='changed'
        else: continue
        changes.append({'ticker':t,'change':kind,'from_group':o.get('action_group') if o else None,'to_group':c.get('action_group') if c else None,'from_status':o.get('action_status') if o else None,'to_status':c.get('action_status') if c else None,'from_price':o.get('entry_price') if o else None,'to_price':c.get('entry_price') if c else None})
    con.close(); return {'dates':[today,prev], 'changes':changes, 'summary':{'new':sum(x['change']=='new' for x in changes),'removed':sum(x['change']=='removed' for x in changes),'changed':sum(x['change']=='changed' for x in changes)}}

def action_board(qs):
    market=market_regime_snapshot()
    regime=market.get('regime') or 'Neutral'
    qdict={k:list(v) for k,v in qs.items()}
    if not qdict.get('start') and not qdict.get('end'):
        drow = query('SELECT MAX(signal_date) AS d FROM daily_signals', [])[0]
        latest_signal_date = drow.get('d') or bangkok_today()
        qdict['start'] = [latest_signal_date]
        qdict['end'] = [latest_signal_date]
    elif qdict.get('end') and not qdict.get('start'):
        # Daily Action Board is an action page, not a cumulative historical report.
        # End-only date filters should resolve to one deterministic trading day.
        qdict['start'] = list(qdict['end'])
    where, params = build_where(qdict, 'ds')
    rows = rows_with_cache(qdict, where, params, limit=80)
    groups={
        'actionable': {'label':'Có thể hành động', 'rows':[]},
        'watch': {'label':'Chờ xác nhận', 'rows':[]},
        'no_chase': {'label':'Không mua đuổi', 'rows':[]},
        'cancel': {'label':'Hủy / loại', 'rows':[]},
    }
    for r in rows:
        group,status,reason=action_status_for_row(r, regime)
        r=dict(r)
        r['action_group']=group
        r['action_status']=status
        r['action_reason']=reason
        r['action_explain']=action_explain(status)
        r['entry_zone']=r.get('valid_entry') or ('Quanh trigger ' + str(r.get('setup_buy_trigger_price')) if r.get('setup_buy_trigger_price') else 'Chờ xác nhận')
        r['trigger_price']=r.get('setup_buy_trigger_price') or r.get('pullback_rebound_trigger')
        r['stoploss']=r.get('plan_stoploss')
        r['target']=r.get('plan_target_near')
        r['position_size']=r.get('suggested_position')
        r['main_reason_short']=r.get('rank_reason') or r.get('main_reason') or r.get('action_reason')
        groups[group]['rows'].append(r)
    for g in groups.values():
        g['rows']=g['rows'][:20]
        g['count']=len(g['rows'])
    board={'date': (qdict.get('end') or qdict.get('start') or [''])[0], 'dashboard_version': DASHBOARD_VERSION, 'market_regime': regime, 'market': market, 'groups': groups, 'summary': {k:v['count'] for k,v in groups.items()}, 'status_explain': ACTION_STATUS_EXPLAIN}
    if (qs.get('save_snapshot') or [''])[0] in ('1','true','yes'):
        board['snapshot_saved']=save_action_board_snapshot(board)
    return board

HTML = load_dashboard_html()



def latest_unique_by_ticker(rows):
    """Keep only the latest signal per ticker for decision tables.
    Important: choose latest signal_date first, then highest final rank within that date.
    This prevents older high-score rows from showing stale market prices after price refresh.
    """
    best = {}
    for r in rows:
        t = (r.get('ticker') or '').upper()
        if not t:
            continue
        cur = best.get(t)
        key = (
            r.get('signal_date') or '',
            float(r.get('final_rank_score') or 0),
            float(r.get('decision_score') or 0),
            float(r.get('action_score') or 0),
        )
        cur_key = (
            (cur or {}).get('signal_date') or '',
            float((cur or {}).get('final_rank_score') or 0),
            float((cur or {}).get('decision_score') or 0),
            float((cur or {}).get('action_score') or 0),
        )
        if cur is None or key > cur_key:
            best[t] = r
    # Return selected rows sorted by practical rank after dedupe.
    return sorted(best.values(), key=lambda r: (float(r.get('final_rank_score') or 0), float(r.get('quality_score') or 0), -float(r.get('false_break_risk_score') or 999), float(r.get('decision_score') or 0)), reverse=True)

def wants_history(qs):
    return (qs.get('history') or qs.get('include_history') or [''])[0] in ('1', 'true', 'yes')

def scoped_latest_qs(qs):
    """Default decision tables to the latest signal date, not cumulative history.
    Use history=1/include_history=1 to intentionally search across all dates.
    """
    qdict = {k: list(v) for k, v in qs.items()}
    if wants_history(qdict):
        return qdict
    if not qdict.get('date') and not qdict.get('start') and not qdict.get('end'):
        drow = query('SELECT MAX(signal_date) AS d FROM daily_signals', [])[0]
        latest_signal_date = drow.get('d') or bangkok_today()
        qdict['start'] = [latest_signal_date]
        qdict['end'] = [latest_signal_date]
    elif qdict.get('date') and not qdict.get('start') and not qdict.get('end'):
        qdict['start'] = list(qdict['date'])
        qdict['end'] = list(qdict['date'])
    elif qdict.get('end') and not qdict.get('start'):
        qdict['start'] = list(qdict['end'])
    return qdict

def rows_with_cache(qs, where, params, *, order="final_rank_score DESC, quality_score DESC, false_break_risk_score ASC, decision_score DESC", cache_order="final_rank_score DESC, quality_score DESC, false_break_risk_score ASC, decision_score DESC", limit=200, unique_latest=True):
    scoped_qs = scoped_latest_qs(qs)
    if scoped_qs != qs:
        where, params = build_where(scoped_qs, 'ds')
    fetch_limit = max(limit * 5, limit) if unique_latest and not wants_history(scoped_qs) else limit
    st = cache_freshness()
    if st.get('ready'):
        try:
            rows = cache_rows(scoped_qs, order_sql=cache_order, limit=fetch_limit)
            if unique_latest and not wants_history(scoped_qs):
                rows = latest_unique_by_ticker(rows)
            return add_change_pct(rows[:limit])
        except Exception as e:
            print(f'[cache fallback] {e}')
    rows = query(rows_sql(where, order=order, limit=fetch_limit), params)
    if unique_latest and not wants_history(scoped_qs):
        rows = latest_unique_by_ticker(rows)
    return add_change_pct(rows[:limit])


def _pct(a, b):
    try:
        if b in (None, 0): return None
        return (float(a) / float(b) - 1.0) * 100.0
    except Exception:
        return None

def ma20_ema_persist(day: str, rows: list, con=None):
    """Lưu kết quả scan MA20/EMA vào DB."""
    own_con = False
    if con is None:
        con = ensure_ma20_ema_schema()
        own_con = True
    try:
        con.execute('DELETE FROM ma20_ema_signals WHERE scan_date=?', (day,))
        if rows:
            for r in rows:
                con.execute(
                    'INSERT OR REPLACE INTO ma20_ema_signals(scan_date,ticker,close,ema99,ema200,ema_gap_pct,ma20,vol_ma20) VALUES(?,?,?,?,?,?,?,?)',
                    (day, r['ticker'], r['close'], r['ema99'], r['ema200'], r['ema_gap_pct'], r['ma20'], r['vol_ma20'])
                )
        else:
            # Preserve marker so the UI knows this date was scanned
            con.execute(
                'INSERT OR REPLACE INTO ma20_ema_signals(scan_date,ticker,close,ema99,ema200,ema_gap_pct,ma20,vol_ma20) VALUES(?,?,?,?,?,?,?,?)',
                (day, '_ZERO_MATCH', 0, 0, 0, 0, 0, 0)
            )
        con.commit()
    finally:
        if own_con:
            con.close()


def ma20_ema_scan(qs):
    import pandas as pd, math
    day=(qs.get('date') or qs.get('end') or [''])[0]
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    if not day:
        r=con.execute("SELECT MAX(trade_date) d FROM daily_prices WHERE ticker<>'VNINDEX'").fetchone(); day=r['d'] if r else bangkok_today()
    params={
      'ema_gap_max': float((qs.get('ema_gap') or ['3.0'])[0] or 3.0),
    }
    ticker_filter=((qs.get('ticker') or [''])[0] or '').strip().upper()
    
    # Ưu tiên đọc từ DB nếu đã có dữ liệu persist cho ngày này
    try:
        from_db = list(con.execute(
            'SELECT scan_date, ticker, close, ema99, ema200, ema_gap_pct, ma20, vol_ma20 FROM ma20_ema_signals WHERE scan_date=? AND ticker<>? ORDER BY ema_gap_pct',
            (day, '_ZERO_MATCH')
        ))
        if from_db and not ticker_filter:
            out = [dict(r) for r in from_db]
            con.close()
            summary = {'signal_count': len(out), 'source': 'persisted'}
            return {'date':day,'rows':out,'summary':summary,'params':params}
    except Exception:
        pass
    
    start=(datetime.fromisoformat(day)-timedelta(days=430)).strftime('%Y-%m-%d')
    rows=con.execute("""
      SELECT ticker, trade_date, open, high, low, close, volume, value, source
      FROM daily_prices
      WHERE trade_date BETWEEN ? AND ? AND ticker <> 'VNINDEX'
      ORDER BY ticker, trade_date
    """, (start, day)).fetchall(); con.close()
    if not rows: return {'date':day,'rows':[], 'summary':{}, 'params':params, 'message':'Chưa có daily_prices'}
    df=pd.DataFrame([dict(r) for r in rows])
    out=[]
    for t,g in df.groupby('ticker'):
        if ticker_filter and t != ticker_filter: continue
        g=g.sort_values('trade_date').copy()
        if len(g)<205: continue
        for col in ['open','high','low','close','volume']:
            g[col]=pd.to_numeric(g[col], errors='coerce')
        g['ema99']=g['close'].ewm(span=99, adjust=False).mean()
        g['ema200']=g['close'].ewm(span=200, adjust=False).mean()
        g['ma20_low']=g['low'].rolling(20).mean(); g['ma20_close']=g['close'].rolling(20).mean(); g['ma20_high']=g['high'].rolling(20).mean()
        g['vol_ma20']=g['volume'].rolling(20).mean(); g['avg_value20']=(g['close']*g['volume']*1000).rolling(20).mean(); g['avg_volume20']=g['vol_ma20']
        ix=g.index[g['trade_date']==day]
        if len(ix)==0: continue
        i=ix[-1]; r=g.loc[i]
        # MA20 + volume TB20 tính để so sánh
        close_vals = g['close'].values; volume_vals = g['volume'].values; lookback = g.index.get_loc(i)
        ma20 = close_vals[max(0,lookback-19):lookback+1].mean()
        vol_ma20 = volume_vals[max(0,lookback-19):lookback+1].mean()
        vals=[r.get(x) for x in ['ema99','ema200','close']]
        if any(pd.isna(x) for x in vals) or pd.isna(ma20) or pd.isna(vol_ma20): continue
        ema99=float(r.ema99); ema200=float(r.ema200)
        ema_gap=abs(ema99-ema200)/ema200*100
        cl_low = min(ema99, ema200)
        # Điều kiện: ema_gap 0.1-3%  +  Volume TB20 >= 1tr  +  Close >= MA20×0.97
        if not (0.1 < ema_gap <= params['ema_gap_max'] and vol_ma20 >= 1000000 and float(r.close) >= ma20 * 0.97): continue
        out.append({'ticker':t,'scan_date':day,'close':round(float(r.close),2),
          'ema99':round(ema99,2),'ema200':round(ema200,2),'ema_gap_pct':round(ema_gap,2),
          'ma20':round(float(ma20),2),'vol_ma20':round(float(vol_ma20),0)})
    out=sorted(out, key=lambda x: x['ema_gap_pct'])[:300]
    # Persist results
    try:
        ma20_ema_persist(day, out)
    except Exception as e:
        pass  # non-fatal
    summary={}
    summary['signal_count']=len(out)
    return {'date':day,'rows':out,'summary':summary,'params':params}

def ma20_ema_backtest(qs):
    import pandas as pd
    start=(qs.get('start') or ['2024-01-01'])[0]; end=(qs.get('end') or [bangkok_today()])[0]
    horizons=[3,5,10,20]; rows=ma20_ema_scan({'end':[end]}).get('rows', [])
    # lightweight: latest-signal forward simulation for current matched list
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    trades=[]; stats={}
    for sig in rows[:80]:
        t=sig['ticker']; bars=[dict(r) for r in con.execute("SELECT trade_date, open, high, low, close FROM daily_prices WHERE ticker=? AND trade_date>? ORDER BY trade_date LIMIT 25",(t,sig['scan_date'])).fetchall()]
        if not bars: continue
        entry=float(bars[0]['open'] or bars[0]['close']); tp=entry*1.04; sl=entry*0.97
        for h in horizons:
            exitp=None; reason='TIMEOUT'; exitd=bars[min(h,len(bars))-1]['trade_date']; hb=min(h,len(bars))
            mfe=0; mae=0
            for i,b in enumerate(bars[:h],1):
                o=float(b['open'] or b['close']); hi=float(b['high'] or b['close']); lo=float(b['low'] or b['close']); c=float(b['close'])
                mfe=max(mfe,(hi/entry-1)*100); mae=min(mae,(lo/entry-1)*100)
                if o<=sl: exitp=o; reason='SL_GAP'
                elif o>=tp: exitp=o; reason='TP_GAP'
                elif lo<=sl and hi>=tp: exitp=sl; reason='SL_SAME_BAR'
                elif lo<=sl: exitp=sl; reason='SL'
                elif hi>=tp: exitp=tp; reason='TP'
                if exitp is not None: exitd=b['trade_date']; hb=i; break
            if exitp is None: exitp=float(bars[min(h,len(bars))-1]['close'])
            gross=(exitp/entry-1)*100; net=gross-0.4
            trades.append({'ticker':t,'horizon':h,'signal_date':sig['scan_date'],'entry_date':bars[0]['trade_date'],'entry_price':round(entry,2),'exit_date':exitd,'exit_price':round(exitp,2),'exit_reason':reason,'gross_return_pct':round(gross,2),'net_return_pct':round(net,2),'holding_bars':hb,'mfe_pct':round(mfe,2),'mae_pct':round(mae,2)})
    con.close()
    for h in horizons:
        rs=[x for x in trades if x['horizon']==h]; rets=[x['net_return_pct'] for x in rs]
        wins=sum(1 for x in rets if x>0); losses=len(rets)-wins
        gp=sum(x for x in rets if x>0); gl=abs(sum(x for x in rets if x<0))
        stats[f'T+{h}']={'trades':len(rs),'winrate_net':round(wins/len(rs)*100,2) if rs else 0,'avg_return_pct':round(sum(rets)/len(rets),2) if rets else 0,'profit_factor':round(gp/gl,2) if gl else None,'tp_hit_rate':round(sum(1 for x in rs if x['exit_reason'].startswith('TP'))/len(rs)*100,2) if rs else 0,'sl_hit_rate':round(sum(1 for x in rs if x['exit_reason'].startswith('SL'))/len(rs)*100,2) if rs else 0}
    return {'ok':True,'note':'Backtest nhanh trên danh sách BREAK_CONFIRMED mới nhất; bản lịch sử đầy đủ sẽ chạy job riêng. TP +4%, SL -3%, phí 0.4%, entry next open.','stats':stats,'trades':trades[:200]}

class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype='application/json'):
        self.send_response(code); self.send_header('Content-Type',ctype); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers(); self.wfile.write(body.encode())
    def do_GET(self):
        u=urlparse(self.path); p=u.path; qs=parse_qs(u.query); where,params=build_where(qs, 'ds')
        try:
            if p=='/': return self.send(200,HTML,'text/html; charset=utf-8')
            if p.startswith('/static/'):
                rel = p.removeprefix('/static/').strip('/')
                target = (STATIC_ROOT / rel).resolve()
                if not str(target).startswith(str(STATIC_ROOT.resolve())) or not target.is_file():
                    return self.send(404, 'Not found', 'text/plain; charset=utf-8')
                return self.send(200, target.read_text(encoding='utf-8'), static_mime(target))
            if p=='/api/sib/v3':
                def sv(key, default=''): return (qs.get(key) or [default])[0]
                filters=[]; params=[]
                if sv('from'): filters.append('snapshot_date>=?'); params.append(sv('from'))
                if sv('to'): filters.append('snapshot_date<=?'); params.append(sv('to'))
                if sv('variant'): filters.append('variant=?'); params.append(sv('variant'))
                if sv('regime'): filters.append('regime=?'); params.append(sv('regime'))
                wh=(' WHERE '+' AND '.join(filters)) if filters else ''
                report=query('SELECT * FROM sib_eval_v3_report WHERE 1=1'+((' AND variant=?') if sv('variant') else '')+((' AND regime=?') if sv('regime') else '')+' ORDER BY horizon,variant,regime',([sv('variant')] if sv('variant') else [])+([sv('regime')] if sv('regime') else []))
                trades=query('SELECT * FROM sib_eval_v3_trades'+wh+' ORDER BY snapshot_date DESC,sib_score DESC LIMIT 500',params)
                return self.send(200,json.dumps({'report':report,'trades':trades},ensure_ascii=False))
            if p=='/api/sib/overview':
                def val(key, default=''):
                    return (qs.get(key) or [default])[0]
                report_filters=[]; report_params=[]; trade_filters=[]; trade_params=[]
                # Report table is pre-aggregated without date dimensions; date
                # filters apply to the detailed trade table. Report remains the
                # persisted all-period reference for selected bucket/regime.
                if val('from'): trade_filters.append('snapshot_date>=?'); trade_params.append(val('from'))
                if val('to'): trade_filters.append('snapshot_date<=?'); trade_params.append(val('to'))
                if val('bucket'): report_filters.append('score_bucket=?'); report_params.append(val('bucket')); trade_filters.append('score_bucket=?'); trade_params.append(val('bucket'))
                if val('regime'): report_filters.append('regime=?'); report_params.append(val('regime')); trade_filters.append('regime=?'); trade_params.append(val('regime'))
                report_where=(' WHERE '+' AND '.join(report_filters)) if report_filters else ''
                trade_where=(' WHERE '+' AND '.join(trade_filters)) if trade_filters else ''
                report=query('SELECT * FROM sib_eval_v2_report'+report_where+' ORDER BY horizon, score_bucket, regime',report_params)
                trades=query('SELECT * FROM sib_eval_v2_trades'+trade_where+' ORDER BY snapshot_date DESC, sib_score DESC, ticker LIMIT 500',trade_params)
                return self.send(200,json.dumps({'report':report,'trades':trades},ensure_ascii=False))
            if p=='/api/health':
                st=cache_stats()
                return self.send(200,json.dumps({'status':'ok','app_version':APP_VERSION,'dashboard_version':DASHBOARD_VERSION,'codename':DASHBOARD_CODENAME,'cache':st,'freshness':cache_freshness()},ensure_ascii=False))
            if p=='/api/meta/version':
                return self.send(200,json.dumps({'app_version':APP_VERSION,'dashboard_version':DASHBOARD_VERSION,'codename':DASHBOARD_CODENAME},ensure_ascii=False))
            if p=='/api/rules':
                return self.send(200,json.dumps(list_rules(),ensure_ascii=False))
            if p=='/api/cache/status':
                return self.send(200,json.dumps(cache_stats(),ensure_ascii=False))
            if p=='/api/cache/freshness':
                return self.send(200,json.dumps(cache_freshness(),ensure_ascii=False))
            if p=='/api/cache/rebuild':
                result=rebuild_cache()
                return self.send(200,json.dumps(result,ensure_ascii=False))
            if p=='/api/cache/top20':
                return self.send(200,json.dumps(add_change_pct(cache_rows(qs, limit=20)),ensure_ascii=False))
            if p=='/api/cache/screener':
                return self.send(200,json.dumps(add_change_pct(cache_rows(qs, limit=300)),ensure_ascii=False))
            if p=='/api/cache/latest':
                return self.send(200,json.dumps(add_change_pct(cache_rows(qs, order_sql='signal_date DESC, action_score DESC', limit=200)),ensure_ascii=False))
            if p=='/api/cache/compare':
                query_rows=add_change_pct(query(rows_sql(where, limit=20),params))
                return self.send(200,json.dumps(compare_cache_with_query(qs, query_rows, limit=20),ensure_ascii=False))
            if p=='/api/score/explain':
                signal_id=(qs.get('signal_id') or [''])[0]
                score_name=(qs.get('score_name') or [''])[0]
                ticker=(qs.get('ticker') or [''])[0].strip().upper()
                signal_date=(qs.get('signal_date') or [''])[0]
                row=[]
                if signal_id:
                    row=query(rows_sql(' WHERE ds.signal_id = ?', limit=1), [signal_id])
                elif ticker and signal_date:
                    row=query(rows_sql(' WHERE ds.ticker = ? AND ds.signal_date = ?', limit=1), [ticker, signal_date])
                if not row:
                    return self.send(404,json.dumps({'error':'score row not found'},ensure_ascii=False))
                return self.send(200,json.dumps(explain_score(row[0], score_name),ensure_ascii=False))
            if p=='/api/dates': return self.send(200,json.dumps(query("SELECT ds.signal_date, COUNT(*) total FROM daily_signals ds GROUP BY ds.signal_date ORDER BY ds.signal_date DESC"),ensure_ascii=False))
            if p=='/api/load_data':
                st=load_data_status()
                if st['status']=='running': return self.send(200,json.dumps(st,ensure_ascii=False))
                day=bangkok_today(); log=str(ROOT/f'CK/logs/ohlcv_close_{day}.log')
                env=os.environ.copy(); env['DATE_OVERRIDE']=day
                # Mặc định Nạp giá luôn kèm Ichimoku — user muốn dashboard luôn fresh
                include_ichimoku = (qs.get('ichimoku') or qs.get('include_ichimoku') or ['1'])[0] != '0'
                if include_ichimoku:
                    env['INCLUDE_ICHIMOKU']='1'
                proc=subprocess.Popen([str(RUN_OHLCV)], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                REFRESH_JOB.update({'process':proc,'date':day,'started_at':datetime.now().isoformat(timespec='seconds'),'log':log,'cache_rebuilt':False})
                msg=f'Đã bắt đầu nạp data ngày {day}.' + (' Có chạy kèm Ichimoku.' if include_ichimoku else ' Ichimoku không chạy kèm; dùng /api/ichimoku/scan?force=1 hoặc /api/load_data?ichimoku=1 nếu muốn quét lại.')
                return self.send(200,json.dumps({'status':'running','date':day,'include_ichimoku':include_ichimoku,'message':msg, 'log_tail':''},ensure_ascii=False))
            if p=='/api/load_data_status': return self.send(200,json.dumps(load_data_status(),ensure_ascii=False))
            if p=='/api/scan_new':
                st=scan_status()
                if st['status']=='running': return self.send(200,json.dumps(st,ensure_ascii=False))
                day=bangkok_today(); log=str(ROOT/f'CK/logs/scan_new_universe_{day}.log')
                cmd=[str(PY),str(RUN_SCAN),'--date',day,'--tickers-file',str(ROOT/'CK/config/universe_tickers.txt'),'--max-symbols','120','--top','20','--sleep','3.5','--batch-size','18','--batch-pause','70']
                f=open(log,'a',encoding='utf-8')
                f.write(f'[{datetime.now().isoformat(timespec="seconds")}] START scan_new_universe {day}\n')
                f.flush()
                proc=subprocess.Popen(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
                SCAN_JOB.update({'process':proc,'date':day,'started_at':datetime.now().isoformat(timespec='seconds'),'log':log,'cache_rebuilt':False})
                return self.send(200,json.dumps({'status':'running','date':day,'message':f'Đã bắt đầu quét mã mới ngày {day}.', 'log_tail':''},ensure_ascii=False))
            if p=='/api/scan_status': return self.send(200,json.dumps(scan_status(),ensure_ascii=False))
            if p=='/api/backtest/daily_run':
                st=daily_backtest_status()
                if st['status']=='running': return self.send(200,json.dumps(st,ensure_ascii=False))
                day=(qs.get('date') or qs.get('end') or [''])[0] or bangkok_today()
                preset=(qs.get('preset') or [''])[0]
                safe_preset=''.join(ch for ch in (preset or 'all') if ch.isalnum() or ch in ('_','-')) or 'all'
                out=str(ROOT/'CK/backtests'/f'daily_preset_backtest_{day}_{safe_preset}.json')
                log=str(ROOT/'CK/logs'/f'daily_preset_backtest_{day}_{safe_preset}.log')
                cmd=[str(PY),str(ROOT/'skills/vietnam-stock-technical-scanner/scripts/backtest_daily_preset.py'),'--date',day,'--preset',preset,'--out',out]
                f=open(log,'a',encoding='utf-8')
                f.write(f'[{datetime.now().isoformat(timespec="seconds")}] START daily preset backtest date={day} preset={preset or "all"}\n')
                f.flush()
                proc=subprocess.Popen(cmd,cwd=str(ROOT),stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
                DAILY_BACKTEST_JOB.update({'process':proc,'date':day,'preset':preset,'started_at':datetime.now().isoformat(timespec='seconds'),'log':log,'out':out})
                return self.send(200,json.dumps({'status':'running','date':day,'preset':preset,'message':f'Đã bắt đầu backtest ngày {day} cho preset {preset or "Tất cả"}.','log_tail':'','out':out},ensure_ascii=False))
            if p=='/api/ma20-ema-d1/dates':
                try:
                    con2 = sqlite3.connect(DB)
                    con2.row_factory = sqlite3.Row
                    d = [dict(r) for r in con2.execute("SELECT scan_date, SUM(CASE WHEN ticker='_ZERO_MATCH' THEN 0 ELSE 1 END) cnt, MAX(CASE WHEN ticker='_ZERO_MATCH' THEN 1 ELSE 0 END) zero_match FROM ma20_ema_signals GROUP BY scan_date ORDER BY scan_date DESC LIMIT 60").fetchall()]
                    con2.close()
                    return self.send(200, json.dumps(d, ensure_ascii=False))
                except Exception as e:
                    return self.send(200, json.dumps([]))
            if p=='/api/backtest/daily_status': return self.send(200,json.dumps(daily_backtest_status(),ensure_ascii=False))
            if p=='/api/backtest/fixed_filter':
                preset=(qs.get('preset') or ['backtest_edge'])[0].strip()
                start=(qs.get('start') or ['2024-01-01'])[0].strip() or '2024-01-01'
                end=(qs.get('end') or [bangkok_today()])[0].strip() or bangkok_today()
                proc=subprocess.run([str(PY), str(RUN_FIXED_FILTER_BACKTEST), '--preset', preset, '--start', start, '--end', end], cwd=str(ROOT), text=True, capture_output=True, timeout=180)
                if proc.returncode != 0:
                    return self.send(500,json.dumps({'ok':False,'error':proc.stderr[-3000:] or proc.stdout[-3000:]},ensure_ascii=False))
                try:
                    data=json.loads(proc.stdout[proc.stdout.find('{'):])
                except Exception:
                    return self.send(500,json.dumps({'ok':False,'error':'Không parse được output fixed filter backtest','raw':proc.stdout[-3000:]},ensure_ascii=False))
                data['ok']=True
                return self.send(200,json.dumps(data,ensure_ascii=False))
            if p=='/api/backtest/preset_performance':
                perf_path=ROOT/'CK/backtests/preset_performance_2026-05-21.json'
                if not perf_path.exists():
                    return self.send(404,json.dumps({'error':'preset performance file not found'},ensure_ascii=False))
                return self.send(200,perf_path.read_text(encoding='utf-8'))
            if p=='/api/backtest/entry_timing':
                timing_path=ROOT/'CK/backtests/entry_timing_recent_top20_3m.json'
                if not timing_path.exists():
                    return self.send(404,json.dumps({'error':'entry timing file not found'},ensure_ascii=False))
                return self.send(200,timing_path.read_text(encoding='utf-8'))
            if p=='/api/backtest/quality_preset_performance':
                quality_path=ROOT/'CK/backtests/quality_preset_performance_2026-05-21.json'
                if not quality_path.exists():
                    return self.send(404,json.dumps({'error':'quality preset performance file not found'},ensure_ascii=False))
                return self.send(200,quality_path.read_text(encoding='utf-8'))
            if p=='/api/market/regime':
                return self.send(200,json.dumps(market_regime_snapshot(),ensure_ascii=False))
            if p=='/api/action/today':
                return self.send(200,json.dumps(action_board(qs),ensure_ascii=False))
            if p=='/api/action/explain':
                status=(qs.get('status') or [''])[0]
                return self.send(200,json.dumps(action_explain(status or None),ensure_ascii=False))
            if p=='/api/action/snapshot/save':
                q2={k:list(v) for k,v in qs.items()}; q2['save_snapshot']=['1']
                return self.send(200,json.dumps(action_board(q2).get('snapshot_saved',{}),ensure_ascii=False))
            if p=='/api/action/snapshots':
                return self.send(200,json.dumps(action_snapshot_history(),ensure_ascii=False))
            if p=='/api/action/compare':
                return self.send(200,json.dumps(action_snapshot_compare(),ensure_ascii=False))
            if p=='/api/trading-plan/export':
                day=(qs.get('date') or qs.get('end') or [''])[0] or bangkok_today()
                proc=subprocess.run([str(PY), str(RUN_TRADING_PLAN), '--date', day], cwd=str(ROOT), text=True, capture_output=True, timeout=120)
                if proc.returncode != 0:
                    return self.send(500,json.dumps({'ok':False,'error':proc.stderr[-2000:] or proc.stdout[-2000:]},ensure_ascii=False))
                return self.send(200,proc.stdout)
            if p=='/api/backtest/regime_preset_performance':
                regime_path=ROOT/'CK/backtests/regime_preset_performance_2026-05-21.json'
                if not regime_path.exists():
                    return self.send(404,json.dumps({'error':'regime preset performance file not found'},ensure_ascii=False))
                return self.send(200,regime_path.read_text(encoding='utf-8'))

            if p=='/api/ma20-ema-d1/scan':
                return self.send(200,json.dumps(ma20_ema_scan(qs),ensure_ascii=False))
            if p=='/api/ma20-ema-d1/backtest':
                return self.send(200,json.dumps(ma20_ema_backtest(qs),ensure_ascii=False))
            if p=='/api/ma20-ema/backtest_ticker':
                ticker=(qs.get('ticker') or [''])[0].strip().upper()
                start=(qs.get('start') or ['2024-01-01'])[0].strip() or '2024-01-01'
                end=(qs.get('end') or [bangkok_today()])[0].strip() or bangkok_today()
                if not ticker or not ticker.replace('.','').isalnum() or len(ticker)>12:
                    return self.send(400,json.dumps({'ok':False,'error':'ticker không hợp lệ'},ensure_ascii=False))
                proc=subprocess.run([str(PY),str(ROOT/'skills/vietnam-stock-technical-scanner/scripts/backtest_ma20ema_ticker.py'),'--ticker',ticker,'--start',start,'--end',end],cwd=str(ROOT),text=True,capture_output=True,timeout=180)
                if proc.returncode!=0:
                    return self.send(500,json.dumps({'ok':False,'error':proc.stderr[-3000:] or proc.stdout[-3000:]},ensure_ascii=False))
                try:
                    data=json.loads(proc.stdout[proc.stdout.find('{'):])
                except Exception:
                    return self.send(500,json.dumps({'ok':False,'error':'Không parse được output backtest','raw':proc.stdout[-3000:]},ensure_ascii=False))
                data['ok']=True
                return self.send(200,json.dumps(data,ensure_ascii=False))
            if p=='/api/ichimoku/top20':
                return self.send(200,json.dumps(load_ichimoku_top20(qs),ensure_ascii=False))
            if p=='/api/ichimoku/scan':
                st=ichimoku_status()
                if st['status']=='running': return self.send(200,json.dumps(st,ensure_ascii=False))
                day=bangkok_today(); log=str(ROOT/f'CK/logs/ichimoku_mtf_scan_{day}.log')
                tf = (qs.get('tf') or ['1H'])[0]
                existing_rows = has_ichimoku_rows(day, tf)
                force = (qs.get('force') or [''])[0] == '1'
                ver_name = '1D T65/K129 Breakout v1.0' if tf == '1D' else '1H T65/K129 Breakout v1.3'
                if existing_rows and not force:
                    return self.send(200,json.dumps({'status':'success','date':day,'message':f'Ichimoku {ver_name} ngày {day} đã có {existing_rows} mã trong SQLite. Không chạy lại để tránh quét trùng; thêm force=1 nếu cần quét lại có chủ đích.', 'existing_rows': existing_rows, 'log_tail':''},ensure_ascii=False))
                env=os.environ.copy(); env['DATE_OVERRIDE']=day; env.setdefault('UPLOAD_DRIVE','0')
                if tf == '1D':
                    # D1 scan: call scanner directly with --tf 1D
                    scanner=str(ROOT/'skills/vietnam-stock-technical-scanner/scripts/scan_ichimoku_mtf.py')
                    f=open(log,'a',encoding='utf-8')
                    f.write(f'[{datetime.now().isoformat(timespec="seconds")}] START ichimoku_d1_scan {day}\n')
                    f.flush()
                    proc=subprocess.Popen([str(PY), scanner, '--date', day, '--max-symbols', '100', '--top', '20',
                        '--near-below-pct', '0.012', '--equal-tol-pct', '0.0015',
                        '--max-above-pct', '0.018', '--sleep', '1.8', '--sleep-between-tickers', '0.7',
                        '--api-error-threshold-pct', '0.35', '--tf', '1D'],
                        cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
                else:
                    # 1H scan: use the existing safe pipeline runner
                    f=open(log,'a',encoding='utf-8')
                    f.write(f'[{datetime.now().isoformat(timespec="seconds")}] START ichimoku_1h_daily_runner {day}\n')
                    f.flush()
                    proc=subprocess.Popen([str(RUN_ICHIMOKU)], cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
                ICHIMOKU_JOB.update({'process':proc,'date':day,'started_at':datetime.now().isoformat(timespec='seconds'),'log':log})
                return self.send(200,json.dumps({'status':'running','date':day,'message':f'Đã bắt đầu quét {ver_name} ngày {day}.', 'log_tail':''},ensure_ascii=False))
            if p=='/api/ichimoku/status': return self.send(200,json.dumps(ichimoku_status(),ensure_ascii=False))
            if p=='/api/ichimoku/backtest':
                ticker=(qs.get('ticker') or [''])[0].strip().upper()
                start=(qs.get('start') or ['2024-01-01'])[0].strip() or '2024-01-01'
                end=(qs.get('end') or [bangkok_today()])[0].strip() or bangkok_today()
                if not ticker or not ticker.replace('.', '').isalnum() or len(ticker) > 12:
                    return self.send(400,json.dumps({'ok':False,'error':'ticker không hợp lệ'},ensure_ascii=False))
                proc=subprocess.run([str(PY), str(RUN_ICHIMOKU_BACKTEST), '--ticker', ticker, '--start', start, '--end', end], cwd=str(ROOT), text=True, capture_output=True, timeout=180)
                if proc.returncode != 0:
                    return self.send(500,json.dumps({'ok':False,'error':proc.stderr[-3000:] or proc.stdout[-3000:]},ensure_ascii=False))
                try:
                    data=json.loads(proc.stdout[proc.stdout.find('{'):])
                except Exception:
                    return self.send(500,json.dumps({'ok':False,'error':'Không parse được output backtest','raw':proc.stdout[-3000:]},ensure_ascii=False))
                data['ok']=True
                return self.send(200,json.dumps(data,ensure_ascii=False))
            if p=='/api/options':
                sectors=[r['sector'] for r in query(f"{BASE_CTE} SELECT DISTINCT sector FROM ranked WHERE sector IS NOT NULL AND sector<>'' ORDER BY sector")]
                actions=[r['action_label'] for r in query(f"{BASE_CTE} SELECT DISTINCT action_label FROM ranked WHERE action_label IS NOT NULL AND action_label<>'' ORDER BY action_label")]
                return self.send(200,json.dumps({'sectors':sectors,'actions':actions},ensure_ascii=False))
            if p=='/api/overview':
                a=scalar(f"""
{BASE_CTE}
SELECT COUNT(*) tong_tin_hieu, COUNT(DISTINCT ds.signal_date) so_ngay,
       ROUND(AVG(ds.action_score),2) diem_hanh_dong_tb,
       ROUND(AVG(ds.decision_score),2) decision_score_tb,
       ROUND(MAX(ds.decision_score),2) top_decision_score,
       ROUND(AVG(ds.calc_reward_risk),2) lai_rui_ro_tb,
       ROUND(AVG(ds.calc_risk_pct),2) rui_ro_tb,
       SUM(CASE WHEN ds.breakout_status='Đã vượt mốc breakout' THEN 1 ELSE 0 END) da_breakout,
       SUM(CASE WHEN ds.breakout_status LIKE 'Chờ giá đóng cửa >%' THEN 1 ELSE 0 END) cho_breakout
FROM ranked ds
{where}
""",params)
                return self.send(200,json.dumps(a,ensure_ascii=False))
            if p=='/api/daily': return self.send(200,json.dumps(query(f"{BASE_CTE} SELECT ds.signal_date, COUNT(*) total, ROUND(AVG(ds.action_score),2) avg_score, ROUND(AVG(ds.decision_score),2) avg_decision, ROUND(AVG(ds.calc_reward_risk),2) avg_rr, ROUND(AVG(ds.calc_risk_pct),2) avg_risk FROM ranked ds {where} GROUP BY ds.signal_date ORDER BY ds.signal_date",params),ensure_ascii=False))
            if p=='/api/setup': return self.send(200,json.dumps(query(f"{BASE_CTE} SELECT ds.setup_type, COUNT(*) total, ROUND(AVG(ds.decision_score),2) avg_score FROM ranked ds {where} GROUP BY ds.setup_type ORDER BY total DESC",params),ensure_ascii=False))
            if p=='/api/labels': return self.send(200,json.dumps(query(f"{BASE_CTE} SELECT ds.buy_zone_label, COUNT(*) total, ROUND(AVG(ds.decision_score),2) avg_score FROM ranked ds {where} GROUP BY ds.buy_zone_label ORDER BY total DESC",params),ensure_ascii=False))
            if p=='/api/v21/sectors': return self.send(200,json.dumps(query(f"{BASE_CTE} SELECT ds.sector, ROUND(AVG(ds.sector_score),2) sector_score, COUNT(*) ticker_count, GROUP_CONCAT(ds.ticker) top_tickers FROM ranked ds {where} AND ds.sector IS NOT NULL AND ds.sector<>'' GROUP BY ds.sector ORDER BY sector_score DESC, ticker_count DESC" if where else f"{BASE_CTE} SELECT ds.sector, ROUND(AVG(ds.sector_score),2) sector_score, COUNT(*) ticker_count, GROUP_CONCAT(ds.ticker) top_tickers FROM ranked ds WHERE ds.sector IS NOT NULL AND ds.sector<>'' GROUP BY ds.sector ORDER BY sector_score DESC, ticker_count DESC",params),ensure_ascii=False))
            if p=='/api/v21/rs':
                rs_history=(qs.get('rs_history') or [''])[0] == '1'
                source = f"ranked ds {where}" if rs_history else f"(SELECT ds.*, ROW_NUMBER() OVER (PARTITION BY ds.ticker ORDER BY ds.signal_date DESC, ds.v21_adjusted_score DESC, ds.decision_score DESC) AS rn FROM ranked ds {where}) ds WHERE ds.rn = 1"
                rows=query(f"""
{BASE_CTE}
SELECT
  ds.signal_id,
  ds.signal_date,
  ds.ticker,
  ds.sector,
  ROUND(ds.display_price,2) entry_price,
  NULL AS change_pct,
  ds.v21_adjusted_score,
  ROUND(ds.rs20,2) rs20,
  ds.rs_rank_pct,
  ds.sector_score,
  ds.action_label,
  ds.setup_type,
  ds.buy_zone_label,
  ROUND(ds.decision_score,2) decision_score,
  ds.b_accumulation_score,
  ds.pullback_quality_score,
  ds.setup_buy_trigger_price,
  ds.pullback_wait_low,
  ds.pullback_wait_high,
  ds.pullback_rebound_trigger,
  ds.pullback_to_trigger_pct,
  ds.calc_reward_risk reward_risk,
  ds.calc_risk_pct risk_pct,
  ds.avg_volume5_latest,
  ds.main_reason
FROM {source}
ORDER BY ds.v21_adjusted_score DESC, ds.decision_score DESC
LIMIT 30
""",params)
                return self.send(200,json.dumps(add_change_pct(rows),ensure_ascii=False))
            if p=='/api/top20': return self.send(200,json.dumps(rows_with_cache(qs, where, params, limit=20),ensure_ascii=False))
            if p=='/api/screener': return self.send(200,json.dumps(rows_with_cache(qs, where, params, limit=300),ensure_ascii=False))
            if p=='/api/latest':
                return self.send(200,json.dumps(rows_with_cache(qs, where, params, order="ds.signal_date DESC, ds.action_score DESC", cache_order="signal_date DESC, action_score DESC", limit=200),ensure_ascii=False))
            return self.send(404,json.dumps({'error':'not found'}))
        except Exception as e:
            return self.send(500,json.dumps({'error':str(e)},ensure_ascii=False))

def main():
    print(f'ABCDE web dashboard: http://{HOST}:{PORT}')
    ThreadingHTTPServer((HOST,PORT),H).serve_forever()
if __name__=='__main__': main()
