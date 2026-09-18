from __future__ import annotations

RULES = {
    'DECISION_SCORE': {
        'rule_id': 'DECISION_SCORE',
        'version': '1.1.0',
        'max_score': None,
        'label': 'Điểm quyết định',
        'description': 'Tổng hợp điểm hành động gốc, breakout, volume, R/R, rủi ro, sức mạnh ngành và phạt mua đuổi.',
    },
    'PULLBACK_QUALITY': {
        'rule_id': 'PULLBACK_QUALITY',
        'version': '1.0.0',
        'max_score': 95,
        'label': 'Pullback đẹp',
        'description': 'Đánh giá setup Chờ pullback bật lại dựa trên khoảng cách trigger, rủi ro, R/R, nền B và sức mạnh ngành.',
    },
    'B_ACCUMULATION': {
        'rule_id': 'B_ACCUMULATION',
        'version': '1.0.0',
        'max_score': 20,
        'label': 'B tích lũy',
        'description': 'Đánh giá chất lượng nền tích lũy: biên độ chặt, gần đỉnh, volume khô, tiền gom và ít phân phối.',
    },
}

def list_rules():
    return [dict(v, rule_version_id=f"{v['rule_id']}_v{v['version']}") for v in RULES.values()]

def get_rule(rule_id: str):
    return RULES.get((rule_id or '').upper())
