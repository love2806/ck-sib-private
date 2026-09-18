from __future__ import annotations
from ck_scanner.scoring.registry import get_rule

def _num(v, digits=2):
    if v is None:
        return None
    try:
        return round(float(v), digits)
    except Exception:
        return v

def _component(name, score, max_score=None, reason=''):
    return {'name': name, 'score': _num(score, 2), 'max': max_score, 'reason': reason}

def explain_score(row: dict, score_name: str) -> dict:
    score_name = (score_name or '').upper()
    rule = get_rule(score_name) or {'rule_id': score_name, 'version': 'unknown', 'label': score_name, 'max_score': None, 'description': ''}
    if score_name == 'DECISION_SCORE':
        components = [
            _component('Điểm hành động gốc từ scanner', row.get('action_score'), None, 'Điểm nền do scanner hiện tại tạo.'),
            _component('Breakout / gần mốc xác nhận', row.get('breakout_score'), 15, 'Ưu tiên đã vượt/gần mốc mua xác nhận.'),
            _component('Volume xác nhận so với TB20', row.get('volume_confirm_score'), 10, f"Volume BO ratio: {_num(row.get('breakout_volume_ratio'),2)}"),
            _component('Lãi/Rủi ro', row.get('rr_score'), 10, f"R/R: {_num(row.get('reward_risk'),2)}"),
            _component('Rủi ro tới stoploss', row.get('risk_score'), 10, f"Risk: {_num(row.get('risk_pct'),2)}%"),
            _component('Sức mạnh ngành/RS', row.get('sector_rs_score'), 10, f"Sector score: {_num(row.get('sector_score'),2)}"),
            _component('Phạt mua đuổi/tránh', row.get('no_chase_penalty'), None, f"Nhãn vùng mua: {row.get('buy_zone_label') or '—'}"),
        ]
        suggestions = {'trigger_price': row.get('setup_buy_trigger_price'), 'trigger_note': row.get('setup_buy_trigger_note')}
        score = row.get('decision_score')
    elif score_name == 'PULLBACK_QUALITY':
        components = [
            _component('Điểm nền mặc định', 15, 15, 'Chỉ áp dụng cho setup Pullback.'),
            _component('Khoảng cách tới giá bật lại', None, 25, f"Trigger cách hiện tại: {_num(row.get('pullback_to_trigger_pct'),2)}%"),
            _component('Rủi ro tới stoploss', None, 15, f"Risk hiện tại: {_num(row.get('risk_pct'),2)}%"),
            _component('Lãi/Rủi ro', None, 15, f"R/R hiện tại: {_num(row.get('reward_risk'),2)}"),
            _component('Chất lượng nền B', None, 15, f"B tích lũy: {_num(row.get('b_accumulation_score'),0)}/20"),
            _component('Sức mạnh ngành', None, 10, f"Sector score: {_num(row.get('sector_score'),2)}"),
        ]
        suggestions = {
            'wait_low': row.get('pullback_wait_low'),
            'wait_high': row.get('pullback_wait_high'),
            'rebound_trigger': row.get('pullback_rebound_trigger'),
            'usage': 'Ưu tiên quan sát phản ứng giá + volume tại vùng chờ; chỉ xem là đẹp khi bật lại có xác nhận, không mua đuổi khi đã vượt quá xa.',
        }
        score = row.get('pullback_quality_score')
    elif score_name == 'B_ACCUMULATION':
        components = [
            _component('Biên độ 20 phiên chặt', row.get('b_tight_range_score'), 5, f"Range20: {_num(row.get('range20_pct'),2)}%"),
            _component('Gần đỉnh 20 phiên', row.get('b_near_high_score'), 4, f"Cách high20: {_num(row.get('distance_to_high20_pct'),2)}%"),
            _component('Volume khô', row.get('b_volume_dry_score'), 3, f"Vol dry ratio: {_num(row.get('vol_dry_ratio'),2)}"),
            _component('Tiền gom', row.get('b_accumulation_money_score'), 4, f"Up-volume ratio 20: {_num(row.get('up_volume_ratio_20'),4)}"),
            _component('Ít phiên phân phối', row.get('b_no_distribution_score'), 4, f"Distribution days 20: {row.get('distribution_days_20')}"),
        ]
        suggestions = {}
        score = row.get('b_accumulation_score')
    else:
        components, suggestions, score = [], {}, None
    return {
        'ticker': row.get('ticker'),
        'signal_date': row.get('signal_date'),
        'score_name': score_name,
        'label': rule.get('label'),
        'description': rule.get('description'),
        'score': score,
        'max_score': rule.get('max_score'),
        'rule_version': f"{rule.get('rule_id')}_v{rule.get('version')}",
        'components': components,
        'suggestions': suggestions,
    }
