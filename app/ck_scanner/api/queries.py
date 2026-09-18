#!/usr/bin/env python3
from __future__ import annotations
import sqlite3
from pathlib import Path

DB = Path('/root/.openclaw/workspace/CK/db/ck_signals.sqlite')

SETUP_TRIGGER_EXPR = """
CASE
  WHEN b.setup_type LIKE '%Pullback%' THEN
    CASE
      WHEN br.prev_high5 IS NOT NULL AND b.display_price > br.prev_high5 * 1.003 THEN br.prev_high5 * 1.003
      WHEN br.prev_close IS NOT NULL THEN br.prev_close * 1.01
      ELSE b.display_price * 1.01
    END
  WHEN b.setup_type LIKE '%Tích%' THEN
    CASE
      WHEN br.high20_prev IS NOT NULL THEN br.high20_prev * 1.005
      WHEN br.prev_high5 IS NOT NULL THEN br.prev_high5 * 1.005
      ELSE b.display_price * 1.012
    END
  WHEN b.setup_type LIKE '%Dòng tiền%' THEN
    CASE
      WHEN br.prev_high5 IS NOT NULL THEN br.prev_high5 * 1.005
      WHEN br.high20_prev IS NOT NULL THEN br.high20_prev * 1.003
      ELSE b.display_price * 1.01
    END
  WHEN b.setup_type LIKE '%Breakout%' OR b.setup_type LIKE '%Vượt%' THEN
    CASE
      WHEN br.high20_prev IS NOT NULL THEN br.high20_prev * 1.005
      ELSE b.display_price * 1.01
    END
  ELSE
    CASE
      WHEN br.high20_prev IS NOT NULL THEN br.high20_prev * 1.005
      WHEN br.prev_high5 IS NOT NULL THEN br.prev_high5 * 1.005
      ELSE b.display_price * 1.01
    END
END
"""

SETUP_TRIGGER_NOTE_EXPR = """
CASE
  WHEN b.setup_type LIKE '%Pullback%' THEN 'Pullback: mua khi giá đóng cửa vượt đỉnh hồi phục 5 phiên +0.3%, xác nhận bật lại sau nhịp chỉnh'
  WHEN b.setup_type LIKE '%Tích%' THEN 'Tích lũy: mua khi giá đóng cửa vượt kháng cự nền/high 20 phiên +0.5%'
  WHEN b.setup_type LIKE '%Dòng tiền%' THEN 'Dòng tiền: mua khi giá đóng cửa vượt đỉnh 5 phiên +0.5% và volume tiếp tục cao'
  WHEN b.setup_type LIKE '%Breakout%' OR b.setup_type LIKE '%Vượt%' THEN 'Breakout: mua khi giá đóng cửa vượt high 20 phiên +0.5%, không mua khi chỉ chạm trong phiên'
  ELSE 'Momentum: mua khi giá đóng cửa vượt mốc xác nhận +0.5-1.0%'
END
"""

BASE_CTE = f"""
WITH base AS (
  SELECT
    ds.*,
    vo.sector,
    vo.v21_adjusted_score,
    vo.rs20,
    vo.rs_rank_pct,
    vo.sector_score,
    sc.b_accumulation_score,
    sc.b_tight_range_score,
    sc.b_near_high_score,
    sc.b_volume_dry_score,
    sc.b_accumulation_money_score,
    sc.b_no_distribution_score,
    sc.range20_pct,
    sc.distance_to_high20_pct,
    sc.vol_dry_ratio,
    sc.up_volume_ratio_20,
    sc.distribution_days_20,
    CASE
      WHEN dp_latest.close IS NOT NULL AND ds.entry_price > 1000 AND dp_latest.close < 1000 THEN dp_latest.close * 1000
      WHEN dp_latest.close IS NOT NULL THEN dp_latest.close
      WHEN dp.close IS NOT NULL AND ds.entry_price > 1000 AND dp.close < 1000 THEN dp.close * 1000
      WHEN dp.close IS NOT NULL THEN dp.close
      ELSE ds.entry_price
    END AS display_price,
    CASE
      WHEN dp_latest.volume IS NOT NULL THEN dp_latest.volume
      WHEN dp.volume IS NOT NULL THEN dp.volume
      ELSE NULL
    END AS display_volume,
    CASE WHEN dp_latest.close IS NOT NULL THEN 'Giá mới nhất' WHEN dp.close IS NOT NULL THEN 'Giá đóng cửa ngày tín hiệu' ELSE 'Giá scan' END AS price_source
  FROM daily_signals ds
  LEFT JOIN v21_signal_overlay vo ON vo.signal_id = ds.signal_id
  LEFT JOIN score_components sc ON sc.signal_id = ds.signal_id
    AND sc.run_id = (SELECT run_id FROM score_runs ORDER BY created_at DESC LIMIT 1)
  LEFT JOIN daily_prices dp ON dp.ticker = ds.ticker AND dp.trade_date = ds.signal_date
  LEFT JOIN daily_prices dp_latest ON dp_latest.ticker = ds.ticker
    AND dp_latest.trade_date = (SELECT MAX(dpx.trade_date) FROM daily_prices dpx WHERE dpx.ticker = ds.ticker AND dpx.close IS NOT NULL)
), breakout AS (
  SELECT
    b.signal_id,
    (
      SELECT MAX(x.high)
      FROM (
        SELECT CASE WHEN b.entry_price > 1000 AND dp2.high < 1000 THEN dp2.high * 1000 ELSE dp2.high END AS high
        FROM daily_prices dp2
        WHERE dp2.ticker = b.ticker
          AND dp2.trade_date < b.signal_date
          AND dp2.high IS NOT NULL
        ORDER BY dp2.trade_date DESC
        LIMIT 20
      ) x
    ) AS high20_prev,
    (
      SELECT ROUND(AVG(x.volume), 0)
      FROM (
        SELECT dp2.volume
        FROM daily_prices dp2
        WHERE dp2.ticker = b.ticker
          AND dp2.trade_date < b.signal_date
          AND dp2.volume IS NOT NULL
        ORDER BY dp2.trade_date DESC
        LIMIT 20
      ) x
    ) AS avg_volume20_prev,
    (
      SELECT MAX(x.high)
      FROM (
        SELECT CASE WHEN b.entry_price > 1000 AND dp3.high < 1000 THEN dp3.high * 1000 ELSE dp3.high END AS high
        FROM daily_prices dp3
        WHERE dp3.ticker = b.ticker
          AND dp3.trade_date < b.signal_date
          AND dp3.high IS NOT NULL
        ORDER BY dp3.trade_date DESC
        LIMIT 5
      ) x
    ) AS prev_high5,
    (
      SELECT MIN(x.low)
      FROM (
        SELECT CASE WHEN b.entry_price > 1000 AND dp6.low < 1000 THEN dp6.low * 1000 ELSE dp6.low END AS low
        FROM daily_prices dp6
        WHERE dp6.ticker = b.ticker
          AND dp6.trade_date < b.signal_date
          AND dp6.low IS NOT NULL
        ORDER BY dp6.trade_date DESC
        LIMIT 5
      ) x
    ) AS prev_low5,
    (
      SELECT CASE WHEN b.entry_price > 1000 AND dp4.close < 1000 THEN dp4.close * 1000 ELSE dp4.close END
      FROM daily_prices dp4
      WHERE dp4.ticker = b.ticker
        AND dp4.trade_date < b.signal_date
        AND dp4.close IS NOT NULL
      ORDER BY dp4.trade_date DESC
      LIMIT 1
    ) AS prev_close
  FROM base b
), enriched AS (
  SELECT
    b.*,
    br.high20_prev,
    br.avg_volume20_prev,
    br.prev_low5,
    (
      SELECT ROUND(AVG(x.volume), 0)
      FROM (
        SELECT dp5.volume
        FROM daily_prices dp5
        WHERE dp5.ticker = b.ticker
          AND dp5.trade_date <= b.signal_date
          AND dp5.volume IS NOT NULL
        ORDER BY dp5.trade_date DESC
        LIMIT 5
      ) x
    ) AS avg_volume5_latest,
    ROUND(CASE WHEN br.high20_prev IS NOT NULL THEN br.high20_prev * 1.005 ELSE NULL END, 2) AS breakout_buy_price,
    ROUND({SETUP_TRIGGER_EXPR}, 2) AS setup_buy_trigger_price,
    {SETUP_TRIGGER_NOTE_EXPR} AS setup_buy_trigger_note,
    CASE
      WHEN br.high20_prev IS NULL THEN 'Chưa đủ dữ liệu 20 phiên'
      WHEN b.display_price > br.high20_prev * 1.005 THEN 'Đã vượt mốc breakout'
      ELSE 'Chờ giá đóng cửa > ' || ROUND(br.high20_prev * 1.005, 2)
    END AS breakout_status,
    CASE
      WHEN br.avg_volume20_prev IS NOT NULL AND br.avg_volume20_prev > 0 AND b.display_volume IS NOT NULL
      THEN ROUND(b.display_volume * 1.0 / br.avg_volume20_prev, 2)
      ELSE NULL
    END AS breakout_volume_ratio,
    CASE
      WHEN b.display_price IS NOT NULL AND b.stoploss IS NOT NULL AND b.target_1 IS NOT NULL AND b.display_price > b.stoploss
      THEN ROUND((b.target_1 - b.display_price) / (b.display_price - b.stoploss), 2)
      ELSE b.reward_risk
    END AS calc_reward_risk,
    CASE
      WHEN b.display_price IS NOT NULL AND b.stoploss IS NOT NULL AND b.display_price > 0
      THEN ROUND((b.display_price - b.stoploss) / b.display_price * 100, 2)
      ELSE b.risk_pct
    END AS calc_risk_pct,
    CASE
      WHEN br.high20_prev IS NOT NULL AND b.display_price > br.high20_prev * 1.005
      THEN ROUND(br.high20_prev * 1.005, 2)
      ELSE NULL
    END AS retest_buy_price,
    CASE
      WHEN br.high20_prev IS NOT NULL AND b.display_price > br.high20_prev * 1.005
      THEN ROUND(br.high20_prev * 1.005 * 0.99, 2)
      ELSE NULL
    END AS retest_zone_low,
    CASE
      WHEN br.high20_prev IS NOT NULL AND b.display_price > br.high20_prev * 1.005
      THEN ROUND(br.high20_prev * 1.005 * 1.015, 2)
      ELSE NULL
    END AS retest_zone_high,
    CASE
      WHEN br.high20_prev IS NOT NULL AND b.display_price > br.high20_prev * 1.005
      THEN ROUND((b.display_price / (br.high20_prev * 1.005) - 1) * 100, 2)
      ELSE NULL
    END AS retest_distance_pct,
    CASE
      WHEN b.setup_type LIKE '%Pullback%' AND b.stoploss IS NOT NULL THEN ROUND(b.stoploss * 1.02, 2)
      WHEN b.setup_type LIKE '%Pullback%' AND br.prev_low5 IS NOT NULL THEN ROUND(br.prev_low5 * 1.01, 2)
      ELSE NULL
    END AS pullback_wait_low,
    CASE
      WHEN b.setup_type LIKE '%Pullback%' AND br.prev_close IS NOT NULL THEN ROUND(br.prev_close * 1.01, 2)
      WHEN b.setup_type LIKE '%Pullback%' THEN ROUND({SETUP_TRIGGER_EXPR}, 2)
      ELSE NULL
    END AS pullback_wait_high,
    CASE
      WHEN b.setup_type LIKE '%Pullback%' THEN ROUND({SETUP_TRIGGER_EXPR}, 2)
      ELSE NULL
    END AS pullback_rebound_trigger,
    CASE
      WHEN b.setup_type LIKE '%Pullback%' AND ROUND({SETUP_TRIGGER_EXPR}, 2) > 0
      THEN ROUND((ROUND({SETUP_TRIGGER_EXPR}, 2) / b.display_price - 1) * 100, 2)
      ELSE NULL
    END AS pullback_to_trigger_pct
  FROM base b
  LEFT JOIN breakout br ON br.signal_id = b.signal_id
), decision AS (
  SELECT
    e.*,
    CASE
      WHEN e.high20_prev IS NOT NULL AND e.display_price > e.high20_prev * 1.005 THEN 15
      WHEN e.high20_prev IS NOT NULL AND e.display_price >= e.high20_prev * 0.98 THEN 8
      ELSE 0
    END AS breakout_score,
    CASE
      WHEN e.breakout_volume_ratio >= 1.5 THEN 10
      WHEN e.breakout_volume_ratio >= 1.2 THEN 6
      WHEN e.breakout_volume_ratio IS NULL THEN 0
      ELSE 2
    END AS volume_confirm_score,
    CASE
      WHEN e.calc_reward_risk >= 2 THEN 10
      WHEN e.calc_reward_risk >= 1.5 THEN 6
      WHEN e.calc_reward_risk >= 1.2 THEN 2
      ELSE -4
    END AS rr_score,
    CASE
      WHEN e.calc_risk_pct <= 6 THEN 10
      WHEN e.calc_risk_pct <= 8 THEN 6
      WHEN e.calc_risk_pct <= 10 THEN 1
      ELSE -8
    END AS risk_score,
    CASE
      WHEN e.sector_score >= 70 THEN 8
      WHEN e.sector_score >= 55 THEN 4
      WHEN e.sector_score IS NULL THEN 0
      ELSE -3
    END AS sector_rs_score,
    CASE
      WHEN e.buy_zone_label LIKE '%Không%' OR e.buy_zone_label LIKE '%Tránh%' THEN -12
      ELSE 0
    END AS no_chase_penalty,
    CASE
      WHEN e.retest_buy_price IS NULL THEN NULL
      ELSE
        20
        + CASE
            WHEN e.retest_distance_pct BETWEEN -1 AND 1.5 THEN 25
            WHEN e.retest_distance_pct > 1.5 AND e.retest_distance_pct <= 4 THEN 16
            WHEN e.retest_distance_pct > 4 AND e.retest_distance_pct <= 7 THEN 6
            ELSE 0
          END
        + CASE
            WHEN e.breakout_volume_ratio >= 1.5 THEN 20
            WHEN e.breakout_volume_ratio >= 1.2 THEN 14
            WHEN e.breakout_volume_ratio >= 1.0 THEN 8
            ELSE 2
          END
        + CASE
            WHEN e.calc_reward_risk >= 2 THEN 15
            WHEN e.calc_reward_risk >= 1.5 THEN 10
            WHEN e.calc_reward_risk >= 1.2 THEN 5
            ELSE 0
          END
        + CASE
            WHEN e.calc_risk_pct <= 5 THEN 12
            WHEN e.calc_risk_pct <= 8 THEN 8
            WHEN e.calc_risk_pct <= 10 THEN 3
            ELSE 0
          END
        + CASE
            WHEN e.sector_score >= 70 THEN 8
            WHEN e.sector_score >= 55 THEN 5
            WHEN e.sector_score IS NULL THEN 0
            ELSE 0
          END
    END AS retest_setup_score,
    CASE
      WHEN e.setup_type NOT LIKE '%Pullback%' THEN NULL
      ELSE
        15
        + CASE
            WHEN e.pullback_to_trigger_pct BETWEEN 0 AND 3 THEN 25
            WHEN e.pullback_to_trigger_pct > 3 AND e.pullback_to_trigger_pct <= 6 THEN 20
            WHEN e.pullback_to_trigger_pct > 6 AND e.pullback_to_trigger_pct <= 10 THEN 12
            WHEN e.pullback_to_trigger_pct < 0 AND e.pullback_to_trigger_pct >= -2 THEN 10
            ELSE 4
          END
        + CASE
            WHEN e.calc_risk_pct <= 5 THEN 15
            WHEN e.calc_risk_pct <= 8 THEN 10
            WHEN e.calc_risk_pct <= 10 THEN 4
            ELSE 0
          END
        + CASE
            WHEN e.calc_reward_risk >= 2 THEN 15
            WHEN e.calc_reward_risk >= 1.5 THEN 10
            WHEN e.calc_reward_risk >= 1.2 THEN 5
            ELSE 0
          END
        + CASE
            WHEN e.b_accumulation_score >= 17 THEN 15
            WHEN e.b_accumulation_score >= 14 THEN 10
            WHEN e.b_accumulation_score >= 11 THEN 5
            ELSE 0
          END
        + CASE
            WHEN e.sector_score >= 70 THEN 10
            WHEN e.sector_score >= 55 THEN 6
            WHEN e.sector_score IS NULL THEN 0
            ELSE 0
          END
    END AS pullback_quality_score
  FROM enriched e
), ranked AS (
  SELECT
    d.*,
    ROUND(
      COALESCE(d.action_score, 0)
      + d.breakout_score
      + d.volume_confirm_score
      + d.rr_score
      + d.risk_score
      + d.sector_rs_score
      + d.no_chase_penalty
    , 2) AS decision_score,
    CASE
      WHEN d.buy_zone_label LIKE '%Không%' OR d.buy_zone_label LIKE '%Tránh%' THEN 'Không mua đuổi'
      WHEN d.high20_prev IS NOT NULL AND d.display_price > d.high20_prev * 1.005 AND COALESCE(d.breakout_volume_ratio,0) >= 1.2 AND d.calc_risk_pct <= 8 AND d.calc_reward_risk >= 1.5 THEN 'Mua thăm dò'
      WHEN d.high20_prev IS NOT NULL AND d.display_price > d.high20_prev * 1.005 AND d.retest_setup_score >= 75 THEN 'Breakout tốt - canh retest'
      WHEN d.high20_prev IS NOT NULL AND d.display_price > d.high20_prev * 1.005 THEN 'Đã breakout - chờ volume/retest'
      WHEN d.high20_prev IS NOT NULL AND d.display_price >= d.high20_prev * 0.98 THEN 'Chờ vượt mốc'
      WHEN d.setup_type LIKE '%Pullback%' AND d.pullback_quality_score >= 75 THEN 'Chờ pullback bật lại đẹp'
      WHEN d.setup_type LIKE '%Pullback%' THEN 'Chờ pullback bật lại'
      WHEN d.setup_type LIKE '%Tích%' THEN 'Theo dõi nền tích lũy'
      ELSE 'Theo dõi'
    END AS action_label
  FROM decision d
)
"""

def build_where(qs, alias='ds'):
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
    def col(name): return f'{alias}.{name}'
    if start:
        where.append(f'{col("signal_date")} >= ?'); params.append(start)
    if end:
        where.append(f'{col("signal_date")} <= ?'); params.append(end)
    if setup:
        where.append(f'{col("setup_type")} = ?'); params.append(setup)
    if label:
        where.append(f'{col("buy_zone_label")} = ?'); params.append(label)
    if sector:
        where.append(f'{col("sector")} = ?'); params.append(sector)
    if ticker:
        where.append(f'{col("ticker")} LIKE ?'); params.append(f'%{ticker}%')
    if action:
        where.append(f'{col("action_label")} = ?'); params.append(action)
    if breakout:
        if breakout == 'triggered': where.append(f'{col("breakout_status")} = ?'); params.append('Đã vượt mốc breakout')
        elif breakout == 'waiting': where.append(f'{col("breakout_status")} LIKE ?'); params.append('Chờ giá đóng cửa >%')
        elif breakout == 'missing': where.append(f'{col("breakout_status")} = ?'); params.append('Chưa đủ dữ liệu 20 phiên')
    for raw, sqlcol in [(min_score,'decision_score'),(min_rr,'calc_reward_risk'),(max_risk,'calc_risk_pct'),(min_liquidity,'avg_volume5_latest'),(min_sector,'sector_score')]:
        if raw:
            try:
                val=float(raw)
            except ValueError:
                continue
            op='<=' if sqlcol=='calc_risk_pct' else '>='
            where.append(f'{col(sqlcol)} {op} ?'); params.append(val)
    if preset:
        if preset == 'actionable':
            # Backtest-tuned 2026-05-22: prioritize practical risk/reward first.
            # Additive/safe: UI preset only, no production scanner rule mutation.
            where.append(f'{col("decision_score")} >= ?'); params.append(65)
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
        elif preset == 'backtest_edge':
            # From 65-ticker/65-date vnstock backtest:
            # best practical edge came from risk<=6 plus setup-specific RSI/RVOL bands.
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(6)
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
            where.append(f'''(
              ({col("setup_type")} LIKE '%Pullback%' AND {col("relative_volume")} BETWEEN 1.0 AND 3.0 AND {col("rsi14")} BETWEEN 55 AND 75)
              OR ({col("setup_type")} LIKE '%Tích%' AND {col("relative_volume")} BETWEEN 0.8 AND 2.5 AND {col("rsi14")} BETWEEN 45 AND 72)
              OR ({col("setup_type")} LIKE '%Dòng tiền%' AND {col("relative_volume")} BETWEEN 0.6 AND 2.5 AND {col("rsi14")} BETWEEN 50 AND 75)
            )''')
        elif preset == 'volman_breakout':
            # Volman-style compression breakout: nền chặt, áp sát kháng cự, volume cạn, không mua đuổi, có RS/sector hỗ trợ.
            where.append(f'{col("b_accumulation_score")} >= ?'); params.append(14)
            where.append(f'{col("range20_pct")} <= ?'); params.append(12)
            where.append(f'{col("distance_to_high20_pct")} <= ?'); params.append(5)
            where.append(f'{col("vol_dry_ratio")} <= ?'); params.append(0.9)
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'({col("rs_rank_pct")} IS NULL OR {col("rs_rank_pct")} >= ?)'); params.append(55)
            where.append(f'({col("setup_buy_trigger_price")} IS NULL OR {col("display_price")} <= {col("setup_buy_trigger_price")} * 1.03)')
        elif preset == 'volman_retest':
            # Volman-style retest: đã có breakout/retest score, giá gần vùng retest, không chase, RS/sector còn ổn.
            where.append(f'{col("retest_setup_score")} >= ?'); params.append(60)
            where.append(f'{col("retest_distance_pct")} BETWEEN ? AND ?'); params.extend([-2, 3])
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'({col("rs_rank_pct")} IS NULL OR {col("rs_rank_pct")} >= ?)'); params.append(55)
        elif preset == 'breakout_retest':
            where.append(f'{col("retest_setup_score")} >= ?'); params.append(60)
        elif preset == 'pullback_good':
            where.append(f'{col("pullback_quality_score")} >= ?'); params.append(60)
        elif preset == 'accumulation_strong':
            where.append(f'{col("b_accumulation_score")} >= ?'); params.append(14)
        elif preset == 'sector_rs':
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'{col("decision_score")} >= ?'); params.append(70)
        elif preset == 'quality_focus':
            # Approximation of quality_score using base ranked fields; actual score is returned in SELECT.
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'({col("rs_rank_pct")} IS NULL OR {col("rs_rank_pct")} >= ?)'); params.append(55)
            where.append(f'({col("b_accumulation_score")} >= ? OR {col("pullback_quality_score")} >= ? OR {col("retest_setup_score")} >= ?)'); params.extend([14,60,60])
            where.append(f'({col("setup_buy_trigger_price")} IS NULL OR {col("display_price")} <= {col("setup_buy_trigger_price")} * 1.03)')
        elif preset == 'low_false_break':
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'({col("rs_rank_pct")} IS NULL OR {col("rs_rank_pct")} >= ?)'); params.append(55)
            where.append(f'({col("setup_buy_trigger_price")} IS NULL OR {col("display_price")} <= {col("setup_buy_trigger_price")} * 1.03)')
            where.append(f'({col("distribution_days_20")} IS NULL OR {col("distribution_days_20")} <= ?)'); params.append(4)
        elif preset == 'smart_market':
            # Same live approximation as quality_focus + low false-break constraints; returned final_rank_score does the ranking.
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'({col("rs_rank_pct")} IS NULL OR {col("rs_rank_pct")} >= ?)'); params.append(55)
            where.append(f'({col("b_accumulation_score")} >= ? OR {col("pullback_quality_score")} >= ? OR {col("retest_setup_score")} >= ?)'); params.extend([14,60,60])
            where.append(f'({col("setup_buy_trigger_price")} IS NULL OR {col("display_price")} <= {col("setup_buy_trigger_price")} * 1.03)')
        elif preset == 'trend_leader':
            # Minervini-style practical proxy: leader first, then setup/risk.
            where.append(f'{col("rs_rank_pct")} >= ?'); params.append(70)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
            where.append(f'({col("setup_buy_trigger_price")} IS NULL OR {col("display_price")} <= {col("setup_buy_trigger_price")} * 1.05)')
        elif preset == 'canslim_technical':
            # CANSLIM technical-only proxy: RS/sector leader + good base + breakout/retest potential.
            where.append(f'{col("rs_rank_pct")} >= ?'); params.append(75)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'{col("b_accumulation_score")} >= ?'); params.append(14)
            where.append(f'({col("distance_to_high20_pct")} IS NULL OR {col("distance_to_high20_pct")} <= ?)'); params.append(8)
            where.append(f'({col("vol_dry_ratio")} IS NULL OR {col("vol_dry_ratio")} <= ?)'); params.append(1.0)
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("avg_volume5_latest")} >= ?'); params.append(1000000)
        elif preset == 'vcp_compression':
            # VCP proxy: range contraction / dry-up / near high / low distribution.
            where.append(f'{col("b_accumulation_score")} >= ?'); params.append(14)
            where.append(f'{col("range20_pct")} <= ?'); params.append(10)
            where.append(f'{col("distance_to_high20_pct")} <= ?'); params.append(5)
            where.append(f'{col("vol_dry_ratio")} <= ?'); params.append(0.85)
            where.append(f'({col("distribution_days_20")} IS NULL OR {col("distribution_days_20")} <= ?)'); params.append(3)
            where.append(f'({col("rs_rank_pct")} IS NULL OR {col("rs_rank_pct")} >= ?)'); params.append(60)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
        elif preset == 'retest_priority':
            # Practical breakout-retest priority: near retest, low false-break, not chasing.
            where.append(f'{col("retest_setup_score")} >= ?'); params.append(65)
            where.append(f'{col("retest_distance_pct")} BETWEEN ? AND ?'); params.extend([-1.5, 2.5])
            where.append(f'{col("calc_reward_risk")} >= ?'); params.append(1.5)
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(8)
            where.append(f'{col("sector_score")} >= ?'); params.append(55)
            where.append(f'({col("rs_rank_pct")} IS NULL OR {col("rs_rank_pct")} >= ?)'); params.append(60)
        elif preset == 'no_chase':
            where.append(f'{col("action_label")} <> ?'); params.append('Không mua đuổi')
            where.append(f'{col("calc_risk_pct")} <= ?'); params.append(10)
    return (' WHERE ' + ' AND '.join(where) if where else ''), params

def query(sql, params=()):
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    rows=[dict(r) for r in con.execute(sql, params).fetchall()]
    con.close(); return rows

def scalar(sql, params=()):
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    r=con.execute(sql, params).fetchone(); con.close(); return dict(r) if r else {}

SELECT_COLS = """
  ds.signal_id,
  ds.signal_date,
  ds.ticker,
  ds.sector,
  ROUND(ds.display_price, 2) AS entry_price,
  ds.price_source,
  ds.action_score,
  ROUND(ds.decision_score, 2) AS decision_score,
  ds.action_label,
  ds.b_accumulation_score,
  ds.b_tight_range_score,
  ds.b_near_high_score,
  ds.b_volume_dry_score,
  ds.b_accumulation_money_score,
  ds.b_no_distribution_score,
  ds.range20_pct,
  ds.distance_to_high20_pct,
  ds.vol_dry_ratio,
  ds.up_volume_ratio_20,
  ds.distribution_days_20,
  ds.breakout_buy_price,
  ds.setup_buy_trigger_price,
  ds.setup_buy_trigger_note,
  ds.breakout_status,
  ds.breakout_volume_ratio,
  ds.retest_buy_price,
  ds.retest_zone_low,
  ds.retest_zone_high,
  ds.retest_distance_pct,
  ds.retest_setup_score,
  ds.pullback_wait_low,
  ds.pullback_wait_high,
  ds.pullback_rebound_trigger,
  ds.pullback_to_trigger_pct,
  ds.pullback_quality_score,
  ds.breakout_score,
  ds.volume_confirm_score,
  ds.rr_score,
  ds.risk_score,
  ds.sector_rs_score,
  ds.no_chase_penalty,
  ds.buy_zone_label,
  ds.setup_type,
  ds.calc_reward_risk AS reward_risk,
  ds.calc_risk_pct AS risk_pct,
  ds.avg_volume5_latest,
  ds.relative_volume,
  ds.rsi14,
  ds.rs20,
  ds.rs_rank_pct,
  ds.sector_score,
  ROUND(
    CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END
  , 2) AS quality_score,
  ROUND(
    CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END
  , 2) AS false_break_risk_score,
  CASE
    WHEN (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
      + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
      + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
      + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
      + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
      + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
      + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) >= 45 THEN 'False break cao'
    WHEN (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
      + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
      + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
      + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
      + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
      + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
      + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) >= 25 THEN 'False break vừa'
    ELSE 'False break thấp'
  END AS false_break_risk_label,
  TRIM(
    (CASE WHEN ds.rs_rank_pct >= 70 AND ds.sector_score >= 55 AND ds.calc_reward_risk >= 1.5 AND ds.calc_risk_pct <= 8 AND (ds.setup_buy_trigger_price IS NULL OR ds.display_price <= ds.setup_buy_trigger_price * 1.05) THEN 'Trend Leader; ' ELSE '' END) ||
    (CASE WHEN ds.rs_rank_pct >= 75 AND ds.sector_score >= 55 AND ds.b_accumulation_score >= 14 AND (ds.distance_to_high20_pct IS NULL OR ds.distance_to_high20_pct <= 8) AND (ds.vol_dry_ratio IS NULL OR ds.vol_dry_ratio <= 1.0) THEN 'CANSLIM Technical; ' ELSE '' END) ||
    (CASE WHEN ds.b_accumulation_score >= 14 AND ds.range20_pct <= 10 AND ds.distance_to_high20_pct <= 5 AND ds.vol_dry_ratio <= 0.85 AND (ds.distribution_days_20 IS NULL OR ds.distribution_days_20 <= 3) THEN 'VCP nén giá; ' ELSE '' END) ||
    (CASE WHEN ds.retest_setup_score >= 65 AND ds.retest_distance_pct BETWEEN -1.5 AND 2.5 THEN 'Breakout Retest; ' ELSE '' END) ||
    (CASE WHEN ds.retest_setup_score >= 60 AND ds.calc_reward_risk >= 1.5 AND ds.calc_risk_pct <= 8 THEN 'Retest ưu tiên; ' ELSE '' END)
  ) AS setup_tags,
ROUND(
    COALESCE(ds.decision_score,0) * 0.35
    + (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) * 0.35
    - (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) * 0.20
    + CASE
        WHEN (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) >= 75 AND (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) <= 25 AND ds.sector_score >= 60 AND (ds.rs_rank_pct IS NULL OR ds.rs_rank_pct >= 60) THEN 10
        WHEN (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) >= 65 AND (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) <= 35 THEN 5
        WHEN (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) > 45 THEN -10
        ELSE 0
      END
    + CASE WHEN ds.calc_reward_risk >= 2 THEN 5 WHEN ds.calc_reward_risk >= 1.5 THEN 2 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct <= 6 THEN 4 WHEN ds.calc_risk_pct <= 8 THEN 2 ELSE -4 END
  , 2) AS final_rank_score,
  CASE
    WHEN (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) >= 75 AND (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) <= 25 THEN 'Ưu tiên thực chiến'
    WHEN (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) > 45 THEN 'Hạ hạng do false-break'
    WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 'Hạ hạng do mua đuổi'
    ELSE 'Xếp hạng cân bằng'
  END AS rank_reason,
  CASE
    WHEN ds.b_accumulation_score >= 14 AND ds.range20_pct <= 12 AND ds.distance_to_high20_pct <= 5 AND ds.vol_dry_ratio <= 0.9 THEN 'Volman Compression'
    WHEN ds.retest_setup_score >= 60 AND ds.retest_distance_pct BETWEEN -2 AND 3 THEN 'Volman Retest'
    WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 'No-chase warning'
    ELSE '—'
  END AS volman_setup,
  CASE
    WHEN ds.b_accumulation_score >= 17 AND ds.range20_pct <= 8 AND ds.distance_to_high20_pct <= 3 AND ds.vol_dry_ratio <= 0.8 THEN 'Nén tốt'
    WHEN ds.b_accumulation_score >= 14 AND ds.range20_pct <= 12 AND ds.distance_to_high20_pct <= 5 THEN 'Nén vừa'
    WHEN ds.retest_setup_score >= 60 AND ds.retest_distance_pct BETWEEN -2 AND 3 THEN 'Retest tốt'
    ELSE 'Chưa rõ'
  END AS volman_quality,
  CASE
    WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 'Tránh mua đuổi: xa trigger >3%'
    WHEN ds.b_accumulation_score >= 14 AND ds.range20_pct <= 12 AND ds.vol_dry_ratio > 1.1 THEN 'Nền chưa cạn volume'
    WHEN ds.sector_score < 55 THEN 'Thiếu hỗ trợ ngành'
    WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 'RS chưa mạnh hơn nhóm đủ rõ'
    ELSE 'Theo dõi breakout/retest + stoploss'
  END AS volman_warning,
  CASE
    WHEN (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) >= 75 AND (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) <= 25 AND ds.sector_score >= 60 AND (ds.rs_rank_pct IS NULL OR ds.rs_rank_pct >= 60) THEN 'Phù hợp market'
    WHEN (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) >= 65 AND (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) <= 35 THEN 'Chờ xác nhận'
    WHEN (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) > 45 THEN 'Không phù hợp khi market yếu'
    ELSE 'Theo dõi theo regime'
  END AS regime_fit,
  CASE
    WHEN ds.setup_type LIKE '%Dòng tiền%' AND ds.calc_risk_pct <= 6 AND (ds.setup_buy_trigger_price IS NULL OR ABS(ds.setup_buy_trigger_price / ds.display_price - 1) * 100 <= 2) THEN 'D/D+1'
    WHEN ds.setup_type LIKE '%Tích%' THEN 'D+2–D+4 hoặc khi vượt nền'
    WHEN ds.setup_type LIKE '%Breakout%' OR ds.setup_type LIKE '%Vượt%' THEN 'Chờ retest / không mua đuổi'
    WHEN ds.setup_type LIKE '%Pullback%' THEN 'Khi vượt đỉnh hồi phục 3–5 phiên'
    ELSE 'Chờ xác nhận'
  END AS suggested_buy_timing,
  CASE
    WHEN (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) >= 75 AND (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) <= 25 AND ds.sector_score >= 60 AND (ds.rs_rank_pct IS NULL OR ds.rs_rank_pct >= 60) THEN 'Phù hợp market'
    WHEN (CASE WHEN ds.rs_rank_pct >= 80 THEN 18 WHEN ds.rs_rank_pct >= 70 THEN 15 WHEN ds.rs_rank_pct >= 55 THEN 10 ELSE 4 END
    + CASE WHEN ds.sector_score >= 70 THEN 15 WHEN ds.sector_score >= 55 THEN 10 ELSE 3 END
    + CASE WHEN ds.calc_risk_pct <= 4 THEN 15 WHEN ds.calc_risk_pct <= 6 THEN 12 WHEN ds.calc_risk_pct <= 8 THEN 8 ELSE 2 END
    + CASE WHEN ds.calc_reward_risk >= 2.5 THEN 12 WHEN ds.calc_reward_risk >= 2 THEN 10 WHEN ds.calc_reward_risk >= 1.5 THEN 7 ELSE 2 END
    + CASE WHEN ds.b_accumulation_score >= 17 THEN 12 WHEN ds.b_accumulation_score >= 14 THEN 9 ELSE 4 END
    + CASE WHEN ds.vol_dry_ratio <= 0.8 THEN 8 WHEN ds.vol_dry_ratio <= 1.0 THEN 6 ELSE 2 END
    + CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 8 WHEN ds.breakout_volume_ratio >= 1.2 THEN 6 WHEN ds.relative_volume >= 1.0 THEN 4 ELSE 2 END
    + CASE WHEN ds.setup_buy_trigger_price IS NULL THEN 4 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 8 WHEN ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 5 ELSE -6 END
    + CASE WHEN ds.distribution_days_20 <= 2 THEN 6 WHEN ds.distribution_days_20 <= 4 THEN 3 ELSE -3 END
    + CASE WHEN ds.setup_type LIKE '%Dòng tiền%' THEN 6 WHEN ds.setup_type LIKE '%Tích%' THEN 4 WHEN ds.setup_type LIKE '%Pullback%' THEN 3 ELSE 2 END) >= 65 AND (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) <= 35 THEN 'Chờ xác nhận'
    WHEN (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 25 ELSE 0 END
    + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) < 1.2 THEN 20 ELSE 0 END
    + CASE WHEN ds.rs_rank_pct IS NOT NULL AND ds.rs_rank_pct < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.sector_score < 55 THEN 15 ELSE 0 END
    + CASE WHEN ds.distribution_days_20 >= 5 THEN 12 ELSE 0 END
    + CASE WHEN ds.calc_reward_risk < 1.5 THEN 10 ELSE 0 END
    + CASE WHEN ds.calc_risk_pct > 8 THEN 10 ELSE 0 END) > 45 THEN 'Không phù hợp khi market yếu'
    ELSE 'Theo dõi theo regime'
  END AS regime_fit,
  CASE
    WHEN ds.setup_type LIKE '%Dòng tiền%' THEN '83.25% chạm +2%, median D+1'
    WHEN ds.setup_type LIKE '%Tích%' THEN '71.09% chạm +2%, median D+3'
    WHEN ds.setup_type LIKE '%Breakout%' OR ds.setup_type LIKE '%Vượt%' THEN '80.00% chạm +2%, median D+1; T+20 yếu'
    WHEN ds.setup_type LIKE '%Pullback%' THEN '78.56% chạm +2%, median D+1; stop risk cao'
    ELSE 'Chưa đủ thống kê setup'
  END AS timing_probability_note,
  CASE
    WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 'Xa trigger >3%: tránh mua đuổi'
    WHEN ds.setup_type LIKE '%Breakout%' OR ds.setup_type LIKE '%Vượt%' THEN 'Breakout dễ spike ngắn: ưu tiên retest/chốt nhanh'
    WHEN ds.setup_type LIKE '%Pullback%' AND (ds.pullback_to_trigger_pct IS NULL OR ds.pullback_to_trigger_pct > 3) THEN 'Pullback chưa bật rõ: chờ xác nhận'
    WHEN ds.setup_type LIKE '%Tích%' THEN 'Nền tích lũy thường chậm: chờ vượt nền hoặc retest'
    ELSE 'Theo timing plan + stoploss'
  END AS timing_warning,

  CASE
    WHEN ds.decision_score >= 110 AND ds.calc_risk_pct <= 6 THEN 'Mua thăm dò, có thể nâng tỷ trọng khi xác nhận'
    WHEN ds.decision_score >= 90 AND ds.calc_risk_pct <= 8 THEN 'Mua thăm dò nhỏ / chờ đóng cửa xác nhận'
    WHEN ds.decision_score >= 75 THEN 'Chỉ watchlist, mua khi vượt trigger/retest giữ được'
    ELSE 'Chưa mua, chỉ theo dõi'
  END AS trade_plan,
  CASE
    WHEN ds.decision_score >= 110 AND ds.calc_risk_pct <= 6 AND calc_risk_pct <= 6 THEN '30-40% vị thế kế hoạch'
    WHEN ds.decision_score >= 90 AND ds.calc_risk_pct <= 8 THEN '20-30% vị thế kế hoạch'
    WHEN ds.decision_score >= 75 THEN '10-20% thăm dò nếu có xác nhận'
    ELSE '0%, chưa giải ngân'
  END AS suggested_position,
  CASE
    WHEN setup_buy_trigger_price IS NOT NULL THEN 'Quanh ' || ROUND(setup_buy_trigger_price,2) || '; không mua nếu xa trigger >3%'
    WHEN retest_buy_price IS NOT NULL THEN 'Canh retest ' || ROUND(retest_zone_low,2) || ' - ' || ROUND(retest_zone_high,2)
    ELSE 'Chỉ mua khi có nến xác nhận + volume'
  END AS valid_entry,
  ROUND(COALESCE(stoploss, display_price * (1 - COALESCE(calc_risk_pct,8)/100.0)), 2) AS plan_stoploss,
  ROUND(COALESCE(target_1, display_price * 1.08), 2) AS plan_target_near,
  CASE
    WHEN ds.decision_score >= 110 THEN 'T+10/T+20: giữ nếu giá không thủng trigger/MA20; chốt từng phần khi +5-8%'
    WHEN ds.decision_score >= 90 THEN 'T+5/T+10: ưu tiên chốt từng phần khi +3-5% hoặc yếu volume'
    ELSE 'Ngắn hạn: chỉ giữ nếu xác nhận rõ, sai là thoát nhanh'
  END AS target_plan,
  CASE
    WHEN (ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03) THEN 'Hủy kèo: false-break cao; không mua nếu chưa retest lại'
    WHEN setup_buy_trigger_price IS NOT NULL AND display_price > setup_buy_trigger_price * 1.03 THEN 'Hủy kèo: giá xa trigger >3%, tránh mua đuổi'
    WHEN sector_score < 55 THEN 'Hủy/giảm tỷ trọng: thiếu hỗ trợ ngành'
    WHEN rs_rank_pct IS NOT NULL AND rs_rank_pct < 55 THEN 'Hủy/giảm tỷ trọng: RS yếu hơn thị trường'
    ELSE 'Hủy kèo nếu đóng cửa dưới stoploss/trigger hoặc VNINDEX chuyển Defensive'
  END AS cancel_condition,
  CASE
    WHEN ds.decision_score >= 110 AND ds.calc_risk_pct <= 6 THEN 'Không all-in; chia 2 lần: thăm dò trước, thêm khi xác nhận.'
    WHEN ds.decision_score >= 90 THEN 'Giữ vốn linh hoạt; ưu tiên lệnh nhỏ vì market chưa Bullish rõ.'
    ELSE 'Ưu tiên bảo toàn vốn; chờ tín hiệu đẹp hơn.'
  END AS capital_note,

  /* Lux-style BUY_SCORE v1: điểm mua tại vùng giá hiện tại, dùng cho Bộ lọc cố định gợi ý ABCDE. */
  ROUND(
    MIN(25,
      CASE WHEN ds.decision_score >= 110 THEN 20 WHEN ds.decision_score >= 90 THEN 16 WHEN ds.decision_score >= 75 THEN 12 ELSE 6 END
      + CASE WHEN ds.b_accumulation_score >= 17 THEN 5 WHEN ds.b_accumulation_score >= 14 THEN 3 ELSE 0 END
    )
    + MIN(20,
      CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 9
           WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 6
           WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 0
           ELSE 4 END
      + CASE WHEN ds.retest_setup_score >= 75 THEN 6 WHEN ds.retest_setup_score >= 60 THEN 4 ELSE 0 END
      + CASE WHEN ds.pullback_quality_score >= 75 THEN 5 WHEN ds.pullback_quality_score >= 60 THEN 3 ELSE 0 END
    )
    + MIN(15,
      CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 9 WHEN ds.breakout_volume_ratio >= 1.2 THEN 7 WHEN ds.relative_volume >= 1.0 THEN 5 ELSE 2 END
      + CASE WHEN ds.vol_dry_ratio <= 0.85 THEN 4 WHEN ds.vol_dry_ratio <= 1.0 THEN 2 ELSE 0 END
      + CASE WHEN ds.distribution_days_20 <= 2 THEN 2 WHEN ds.distribution_days_20 <= 4 THEN 1 ELSE 0 END
    )
    + MIN(15,
      CASE WHEN ds.rs_rank_pct >= 80 THEN 8 WHEN ds.rs_rank_pct >= 70 THEN 6 WHEN ds.rs_rank_pct >= 55 THEN 4 ELSE 1 END
      + CASE WHEN ds.sector_score >= 70 THEN 7 WHEN ds.sector_score >= 55 THEN 5 ELSE 1 END
    )
    + MIN(10,
      CASE WHEN ds.b_accumulation_score >= 17 AND ds.range20_pct <= 8 AND ds.distance_to_high20_pct <= 3 THEN 5
           WHEN ds.b_accumulation_score >= 14 AND ds.range20_pct <= 12 AND ds.distance_to_high20_pct <= 5 THEN 4 ELSE 1 END
      + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) >= 1.2 THEN 3 ELSE 0 END
      + CASE WHEN ds.retest_distance_pct BETWEEN -1.5 AND 2.5 THEN 2 ELSE 0 END
    )
    + MIN(10,
      CASE WHEN ds.calc_reward_risk >= 2 THEN 5 WHEN ds.calc_reward_risk >= 1.5 THEN 3 WHEN ds.calc_reward_risk >= 1.2 THEN 1 ELSE 0 END
      + CASE WHEN ds.calc_risk_pct <= 4 THEN 5 WHEN ds.calc_risk_pct <= 6 THEN 4 WHEN ds.calc_risk_pct <= 8 THEN 2 ELSE 0 END
    )
    + CASE WHEN ds.sector_score >= 55 AND COALESCE(ds.calc_risk_pct,99) <= 8 THEN 5 WHEN COALESCE(ds.calc_risk_pct,99) <= 10 THEN 3 ELSE 1 END
    - CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 12 ELSE 0 END
    - CASE WHEN ds.calc_risk_pct > 10 THEN 10 ELSE 0 END
    - CASE WHEN ds.calc_reward_risk < 1.2 THEN 6 ELSE 0 END
  , 2) AS buy_score,
  CASE
    WHEN ds.calc_risk_pct > 10 THEN 'RISK_HIGH'
    WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 'NO_CHASE'
    WHEN ROUND(
      MIN(25, CASE WHEN ds.decision_score >= 110 THEN 20 WHEN ds.decision_score >= 90 THEN 16 WHEN ds.decision_score >= 75 THEN 12 ELSE 6 END + CASE WHEN ds.b_accumulation_score >= 17 THEN 5 WHEN ds.b_accumulation_score >= 14 THEN 3 ELSE 0 END)
      + MIN(20, CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 9 WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 6 WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 0 ELSE 4 END + CASE WHEN ds.retest_setup_score >= 75 THEN 6 WHEN ds.retest_setup_score >= 60 THEN 4 ELSE 0 END + CASE WHEN ds.pullback_quality_score >= 75 THEN 5 WHEN ds.pullback_quality_score >= 60 THEN 3 ELSE 0 END)
      + MIN(15, CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 9 WHEN ds.breakout_volume_ratio >= 1.2 THEN 7 WHEN ds.relative_volume >= 1.0 THEN 5 ELSE 2 END + CASE WHEN ds.vol_dry_ratio <= 0.85 THEN 4 WHEN ds.vol_dry_ratio <= 1.0 THEN 2 ELSE 0 END + CASE WHEN ds.distribution_days_20 <= 2 THEN 2 WHEN ds.distribution_days_20 <= 4 THEN 1 ELSE 0 END)
      + MIN(15, CASE WHEN ds.rs_rank_pct >= 80 THEN 8 WHEN ds.rs_rank_pct >= 70 THEN 6 WHEN ds.rs_rank_pct >= 55 THEN 4 ELSE 1 END + CASE WHEN ds.sector_score >= 70 THEN 7 WHEN ds.sector_score >= 55 THEN 5 ELSE 1 END)
      + MIN(10, CASE WHEN ds.b_accumulation_score >= 17 AND ds.range20_pct <= 8 AND ds.distance_to_high20_pct <= 3 THEN 5 WHEN ds.b_accumulation_score >= 14 AND ds.range20_pct <= 12 AND ds.distance_to_high20_pct <= 5 THEN 4 ELSE 1 END + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) >= 1.2 THEN 3 ELSE 0 END + CASE WHEN ds.retest_distance_pct BETWEEN -1.5 AND 2.5 THEN 2 ELSE 0 END)
      + MIN(10, CASE WHEN ds.calc_reward_risk >= 2 THEN 5 WHEN ds.calc_reward_risk >= 1.5 THEN 3 WHEN ds.calc_reward_risk >= 1.2 THEN 1 ELSE 0 END + CASE WHEN ds.calc_risk_pct <= 4 THEN 5 WHEN ds.calc_risk_pct <= 6 THEN 4 WHEN ds.calc_risk_pct <= 8 THEN 2 ELSE 0 END)
      + CASE WHEN ds.sector_score >= 55 AND COALESCE(ds.calc_risk_pct,99) <= 8 THEN 5 WHEN COALESCE(ds.calc_risk_pct,99) <= 10 THEN 3 ELSE 1 END
      - CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 12 ELSE 0 END
      - CASE WHEN ds.calc_risk_pct > 10 THEN 10 ELSE 0 END
      - CASE WHEN ds.calc_reward_risk < 1.2 THEN 6 ELSE 0 END
    , 2) >= 85 THEN 'BUY 4'
    WHEN ROUND(
      MIN(25, CASE WHEN ds.decision_score >= 110 THEN 20 WHEN ds.decision_score >= 90 THEN 16 WHEN ds.decision_score >= 75 THEN 12 ELSE 6 END + CASE WHEN ds.b_accumulation_score >= 17 THEN 5 WHEN ds.b_accumulation_score >= 14 THEN 3 ELSE 0 END)
      + MIN(20, CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 9 WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 6 WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 0 ELSE 4 END + CASE WHEN ds.retest_setup_score >= 75 THEN 6 WHEN ds.retest_setup_score >= 60 THEN 4 ELSE 0 END + CASE WHEN ds.pullback_quality_score >= 75 THEN 5 WHEN ds.pullback_quality_score >= 60 THEN 3 ELSE 0 END)
      + MIN(15, CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 9 WHEN ds.breakout_volume_ratio >= 1.2 THEN 7 WHEN ds.relative_volume >= 1.0 THEN 5 ELSE 2 END + CASE WHEN ds.vol_dry_ratio <= 0.85 THEN 4 WHEN ds.vol_dry_ratio <= 1.0 THEN 2 ELSE 0 END + CASE WHEN ds.distribution_days_20 <= 2 THEN 2 WHEN ds.distribution_days_20 <= 4 THEN 1 ELSE 0 END)
      + MIN(15, CASE WHEN ds.rs_rank_pct >= 80 THEN 8 WHEN ds.rs_rank_pct >= 70 THEN 6 WHEN ds.rs_rank_pct >= 55 THEN 4 ELSE 1 END + CASE WHEN ds.sector_score >= 70 THEN 7 WHEN ds.sector_score >= 55 THEN 5 ELSE 1 END)
      + MIN(10, CASE WHEN ds.b_accumulation_score >= 17 AND ds.range20_pct <= 8 AND ds.distance_to_high20_pct <= 3 THEN 5 WHEN ds.b_accumulation_score >= 14 AND ds.range20_pct <= 12 AND ds.distance_to_high20_pct <= 5 THEN 4 ELSE 1 END + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) >= 1.2 THEN 3 ELSE 0 END + CASE WHEN ds.retest_distance_pct BETWEEN -1.5 AND 2.5 THEN 2 ELSE 0 END)
      + MIN(10, CASE WHEN ds.calc_reward_risk >= 2 THEN 5 WHEN ds.calc_reward_risk >= 1.5 THEN 3 WHEN ds.calc_reward_risk >= 1.2 THEN 1 ELSE 0 END + CASE WHEN ds.calc_risk_pct <= 4 THEN 5 WHEN ds.calc_risk_pct <= 6 THEN 4 WHEN ds.calc_risk_pct <= 8 THEN 2 ELSE 0 END)
      + CASE WHEN ds.sector_score >= 55 AND COALESCE(ds.calc_risk_pct,99) <= 8 THEN 5 WHEN COALESCE(ds.calc_risk_pct,99) <= 10 THEN 3 ELSE 1 END
      - CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 12 ELSE 0 END
      - CASE WHEN ds.calc_risk_pct > 10 THEN 10 ELSE 0 END
      - CASE WHEN ds.calc_reward_risk < 1.2 THEN 6 ELSE 0 END
    , 2) >= 70 THEN 'BUY 3'
    WHEN ROUND(
      MIN(25, CASE WHEN ds.decision_score >= 110 THEN 20 WHEN ds.decision_score >= 90 THEN 16 WHEN ds.decision_score >= 75 THEN 12 ELSE 6 END + CASE WHEN ds.b_accumulation_score >= 17 THEN 5 WHEN ds.b_accumulation_score >= 14 THEN 3 ELSE 0 END)
      + MIN(20, CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price <= ds.setup_buy_trigger_price * 1.01 THEN 9 WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price <= ds.setup_buy_trigger_price * 1.03 THEN 6 WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 0 ELSE 4 END + CASE WHEN ds.retest_setup_score >= 75 THEN 6 WHEN ds.retest_setup_score >= 60 THEN 4 ELSE 0 END + CASE WHEN ds.pullback_quality_score >= 75 THEN 5 WHEN ds.pullback_quality_score >= 60 THEN 3 ELSE 0 END)
      + MIN(15, CASE WHEN ds.breakout_volume_ratio >= 1.5 THEN 9 WHEN ds.breakout_volume_ratio >= 1.2 THEN 7 WHEN ds.relative_volume >= 1.0 THEN 5 ELSE 2 END + CASE WHEN ds.vol_dry_ratio <= 0.85 THEN 4 WHEN ds.vol_dry_ratio <= 1.0 THEN 2 ELSE 0 END + CASE WHEN ds.distribution_days_20 <= 2 THEN 2 WHEN ds.distribution_days_20 <= 4 THEN 1 ELSE 0 END)
      + MIN(15, CASE WHEN ds.rs_rank_pct >= 80 THEN 8 WHEN ds.rs_rank_pct >= 70 THEN 6 WHEN ds.rs_rank_pct >= 55 THEN 4 ELSE 1 END + CASE WHEN ds.sector_score >= 70 THEN 7 WHEN ds.sector_score >= 55 THEN 5 ELSE 1 END)
      + MIN(10, CASE WHEN ds.b_accumulation_score >= 17 AND ds.range20_pct <= 8 AND ds.distance_to_high20_pct <= 3 THEN 5 WHEN ds.b_accumulation_score >= 14 AND ds.range20_pct <= 12 AND ds.distance_to_high20_pct <= 5 THEN 4 ELSE 1 END + CASE WHEN ds.breakout_status LIKE 'Đã%' AND COALESCE(ds.breakout_volume_ratio,0) >= 1.2 THEN 3 ELSE 0 END + CASE WHEN ds.retest_distance_pct BETWEEN -1.5 AND 2.5 THEN 2 ELSE 0 END)
      + MIN(10, CASE WHEN ds.calc_reward_risk >= 2 THEN 5 WHEN ds.calc_reward_risk >= 1.5 THEN 3 WHEN ds.calc_reward_risk >= 1.2 THEN 1 ELSE 0 END + CASE WHEN ds.calc_risk_pct <= 4 THEN 5 WHEN ds.calc_risk_pct <= 6 THEN 4 WHEN ds.calc_risk_pct <= 8 THEN 2 ELSE 0 END)
      + CASE WHEN ds.sector_score >= 55 AND COALESCE(ds.calc_risk_pct,99) <= 8 THEN 5 WHEN COALESCE(ds.calc_risk_pct,99) <= 10 THEN 3 ELSE 1 END
      - CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 12 ELSE 0 END
      - CASE WHEN ds.calc_risk_pct > 10 THEN 10 ELSE 0 END
      - CASE WHEN ds.calc_reward_risk < 1.2 THEN 6 ELSE 0 END
    , 2) >= 55 THEN 'Candidate'
    ELSE 'Watchlist'
  END AS buy_label,
  TRIM(
    (CASE WHEN ds.setup_buy_trigger_price IS NOT NULL AND ds.display_price > ds.setup_buy_trigger_price * 1.03 THEN 'Giá xa trigger >3%, tránh mua đuổi; ' ELSE '' END) ||
    (CASE WHEN ds.calc_risk_pct > 10 THEN 'Risk >10%; ' WHEN ds.calc_risk_pct <= 6 THEN 'Risk đẹp <=6%; ' ELSE '' END) ||
    (CASE WHEN ds.calc_reward_risk >= 2 THEN 'R/R >=2; ' WHEN ds.calc_reward_risk < 1.2 THEN 'R/R thấp; ' ELSE '' END) ||
    (CASE WHEN ds.rs_rank_pct >= 70 THEN 'RS mạnh; ' ELSE '' END) ||
    (CASE WHEN ds.sector_score >= 55 THEN 'Ngành ủng hộ; ' ELSE '' END) ||
    (CASE WHEN ds.retest_setup_score >= 65 THEN 'Retest tốt; ' ELSE '' END) ||
    (CASE WHEN ds.pullback_quality_score >= 65 THEN 'Pullback đẹp; ' ELSE '' END) ||
    (CASE WHEN ds.b_accumulation_score >= 14 THEN 'Nền tích lũy đạt; ' ELSE '' END)
  ) AS buy_score_reason,
  ds.main_reason,
  ds.warning,
  NULL AS change_pct
"""

def add_change_pct(rows):
    if not rows:
        return rows
    tickers=sorted({r.get('ticker') for r in rows if r.get('ticker')})
    dates=[r.get('signal_date') for r in rows if r.get('signal_date')]
    if not tickers or not dates:
        return rows
    start=min(dates); end=max(dates)
    placeholders=','.join('?' for _ in tickers)
    price_rows=query(f'''
SELECT ticker, trade_date,
       CASE WHEN close IS NOT NULL AND close < 1000 THEN close*1000 ELSE close END AS close
FROM daily_prices
WHERE ticker IN ({placeholders}) AND trade_date BETWEEN ? AND ? AND close IS NOT NULL
ORDER BY ticker, trade_date
''', tickers+[start,end])
    first={}; last={}
    for pr in price_rows:
        t=pr.get('ticker'); c=pr.get('close')
        if t not in first and c:
            first[t]=float(c)
        if c:
            last[t]=float(c)
    for r in rows:
        b=first.get(r.get('ticker'))
        e=last.get(r.get('ticker'))
        if b and e is not None:
            r['change_pct']=round((e-b)/b*100,2)
        else:
            r['change_pct']=None
    return rows

def rows_sql(where, order="final_rank_score DESC, quality_score DESC, false_break_risk_score ASC, decision_score DESC", limit=200):
    return f"""
{BASE_CTE}
SELECT {SELECT_COLS}
FROM ranked ds
{where}
ORDER BY {order}
LIMIT {int(limit)}
"""
