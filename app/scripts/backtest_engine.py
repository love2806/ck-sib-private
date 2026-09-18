#!/usr/bin/env python3
"""Backtest Engine — kiểm tra tín hiệu indicator với dữ liệu lịch sử.

Cách hoạt động:
  1. Nhận list signal (ticker, scan_date) từ indicator
  2. Với mỗi signal, mua tại close của scan_date (entry)
  3. Hold trong N ngày (horizon), hoặc chốt tại stoploss/target
  4. Tính metric: winrate, profit factor, avg return, drawdown, Sharpe

Usage:
  from backtest_engine import backtest_signals
  metrics = backtest_signals(signals, daily_prices_df, horizon=5)
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

DB = Path('/root/.openclaw/workspace/CK/db/ck_signals.sqlite')


def load_daily_prices(db_path: str | Path = DB, 
                       min_date: str | None = None,
                       max_date: str | None = None) -> pd.DataFrame:
    """Load daily_prices từ SQLite thành DataFrame."""
    con = sqlite3.connect(db_path)
    query = "SELECT ticker, trade_date, open, high, low, close, volume FROM daily_prices"
    conditions = []
    if min_date:
        conditions.append(f"trade_date >= '{min_date}'")
    if max_date:
        conditions.append(f"trade_date <= '{max_date}'")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY ticker, trade_date"
    df = pd.read_sql(query, con)
    con.close()
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def backtest_signals(
    signals: list[dict],
    prices: pd.DataFrame,
    horizon: int = 5,
    stoploss_pct: float | None = 0.05,
    takeprofit_pct: float | None = None,
    exit_on_signal_end: bool = True,
) -> dict[str, Any]:
    """Backtest một list signal.

    Args:
        signals: list[dict] với keys 'ticker', 'scan_date' (tối thiểu)
        prices: DataFrame daily_prices
        horizon: số ngày hold mặc định
        stoploss_pct: cắt lỗ % (VD 0.05 = 5%). None = không dùng
        takeprofit_pct: chốt lời % (VD 0.10 = 10%). None = không dùng
        exit_on_signal_end: True = bán đúng ngày cuối của horizon

    Returns:
        dict với key 'trades' (list trades) và 'stats' (dict metrics)
    """
    if not signals:
        trades = []
        return {'trades': trades, 'stats': _compute_metrics(trades)}
    
    prices = prices.copy()
    
    # Pre-index prices cho lookup nhanh
    ticker_dates = {}
    for t, g in prices.groupby('ticker'):
        g = g.sort_values('trade_date')
        ticker_dates[t] = {
            'dates': g['trade_date'].values,
            'closes': g['close'].values,
            'highs': g['high'].values if 'high' in g.columns else g['close'].values,
            'lows': g['low'].values if 'low' in g.columns else g['close'].values,
        }
    
    trades = []
    
    for sig in signals:
        ticker = sig['ticker']
        entry_date = sig.get('scan_date', sig.get('date', ''))
        
        if ticker not in ticker_dates:
            continue
        
        td = ticker_dates[ticker]
        dates = td['dates']
        
        # Tìm index của entry_date
        entry_idx = None
        for i, d in enumerate(dates):
            if d == entry_date:
                entry_idx = i
                break
        
        if entry_idx is None:
            continue
        
        entry_price = float(td['closes'][entry_idx])
        if np.isnan(entry_price) or entry_price <= 0:
            continue
        
        # Tìm exit
        exit_idx = entry_idx + horizon
        exit_date = None
        exit_price = None
        exit_reason = 'horizon_end'
        
        # Check stoploss/takeprofit từng ngày
        if stoploss_pct or takeprofit_pct:
            for i in range(entry_idx + 1, min(entry_idx + horizon + 1, len(dates))):
                high = float(td['highs'][i])
                low = float(td['lows'][i])
                
                if stoploss_pct and low <= entry_price * (1 - stoploss_pct):
                    exit_idx = i
                    exit_price = entry_price * (1 - stoploss_pct)
                    exit_reason = 'stoploss'
                    break
                    
                if takeprofit_pct and high >= entry_price * (1 + takeprofit_pct):
                    exit_idx = i
                    exit_price = entry_price * (1 + takeprofit_pct)
                    exit_reason = 'takeprofit'
                    break
        
        if exit_date is None and exit_on_signal_end and exit_idx < len(dates):
            exit_date = dates[exit_idx]
            exit_price = float(td['closes'][exit_idx])
        
        if exit_price is None or np.isnan(exit_price):
            continue
        
        gross_return = (exit_price - entry_price) / entry_price
        net_return = gross_return - 0.0015  # trừ phí ước tính 0.15% mỗi chiều
        
        trades.append({
            'ticker': ticker,
            'signal_date': entry_date,
            'entry_date': entry_date,
            'entry_price': round(entry_price, 2),
            'exit_date': str(dates[exit_idx]) if exit_idx < len(dates) else None,
            'exit_price': round(exit_price, 2),
            'exit_reason': exit_reason,
            'horizon': horizon,
            'gross_return_pct': round(gross_return * 100, 2),
            'net_return_pct': round(net_return * 100, 2),
        })
    
    return {'trades': trades, 'stats': _compute_metrics(trades)}


def backtest_multi_horizon(
    signals: list[dict],
    prices: pd.DataFrame,
    horizons: list[int] = [3, 5, 10, 20],
    stoploss_pct: float | None = 0.05,
    takeprofit_pct: float | None = None,
) -> dict[str, Any]:
    """Backtest với nhiều horizon cùng lúc."""
    all_trades = []
    all_stats = {}
    
    for h in horizons:
        result = backtest_signals(
            signals, prices,
            horizon=h,
            stoploss_pct=stoploss_pct,
            takeprofit_pct=takeprofit_pct,
        )
        stats = result['stats']
        stats['horizon'] = h
        all_stats[f'T+{h}'] = stats
        for t in result['trades']:
            t_copy = dict(t)
            t_copy['horizon'] = h
            all_trades.append(t_copy)
    
    return {
        'trades': all_trades,
        'stats_by_horizon': all_stats,
        'summary': {
            h: {
                'trades': s['trades'],
                'winrate_net': s['winrate_net'],
                'avg_return_pct': s['avg_return_pct'],
                'profit_factor': s['profit_factor'],
                'sharpe': s['sharpe'],
                'max_drawdown_pct': s['max_drawdown_pct'],
            }
            for h, s in all_stats.items()
        }
    }


def _compute_metrics(trades: list[dict]) -> dict[str, Any]:
    """Tính các metrics từ list trades."""
    if not trades:
        return _empty_result()
    
    df = pd.DataFrame(trades)
    wins = df[df['net_return_pct'] > 0]
    losses = df[df['net_return_pct'] <= 0]
    
    total = len(df)
    win_count = len(wins)
    loss_count = len(losses)
    winrate = win_count / total * 100 if total > 0 else 0
    
    avg_return = df['net_return_pct'].mean()
    med_return = df['net_return_pct'].median()
    
    total_gain = wins['net_return_pct'].sum() if win_count > 0 else 0
    total_loss = abs(losses['net_return_pct'].sum()) if loss_count > 0 else 0
    profit_factor = total_gain / total_loss if total_loss > 0 else (999 if total_gain > 0 else 0)
    
    # Sharpe (annualized, assuming daily returns)
    returns = df['net_return_pct'].values / 100
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 1 and returns.std() > 0 else 0
    
    # Max drawdown
    cumulative = (1 + returns).cumprod()
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max * 100
    max_dd = abs(float(drawdown.min())) if len(drawdown) > 0 else 0
    
    # Avg win / avg loss
    avg_win = wins['net_return_pct'].mean() if win_count > 0 else 0
    avg_loss = abs(losses['net_return_pct'].mean()) if loss_count > 0 else 0
    
    return {
        'trades': total,
        'wins': win_count,
        'losses': loss_count,
        'winrate_net': round(winrate, 2),
        'winrate_gross': round(len(df[df['gross_return_pct'] > 0]) / total * 100, 2) if total > 0 else 0,
        'avg_return_pct': round(float(avg_return), 2),
        'med_return_pct': round(float(med_return), 2),
        'avg_win_pct': round(float(avg_win), 2) if win_count > 0 else 0,
        'avg_loss_pct': round(float(avg_loss), 2) if loss_count > 0 else 0,
        'profit_factor': round(float(profit_factor), 2),
        'sharpe': round(float(sharpe), 2),
        'max_drawdown_pct': round(float(max_dd), 2),
        'total_gain_pct': round(float(total_gain), 2),
        'total_loss_pct': round(float(total_loss), 2),
        'net_total_pct': round(float(total_gain - total_loss), 2),
    }


def _empty_result() -> dict:
    return {
        'trades': 0, 'wins': 0, 'losses': 0,
        'winrate_net': 0, 'winrate_gross': 0,
        'avg_return_pct': 0, 'med_return_pct': 0,
        'avg_win_pct': 0, 'avg_loss_pct': 0,
        'profit_factor': 0, 'sharpe': 0,
        'max_drawdown_pct': 0,
        'total_gain_pct': 0, 'total_loss_pct': 0, 'net_total_pct': 0,
    }


if __name__ == '__main__':
    # Test nhanh
    prices = load_daily_prices()
    print(f"Loaded {len(prices)} price rows from {prices['trade_date'].min()} to {prices['trade_date'].max()}")
    
    # Fake signals để test
    test_signals = [
        {'ticker': 'ACB', 'scan_date': '2026-07-10'},
        {'ticker': 'CTG', 'scan_date': '2026-07-10'},
        {'ticker': 'VND', 'scan_date': '2026-07-10'},
    ]
    
    result = backtest_signals(test_signals, prices, horizon=5)
    stats = result['stats']
    print(f"\nBacktest T+5 trên {len(test_signals)} signals:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
