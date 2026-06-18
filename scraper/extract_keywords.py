# -*- coding: utf-8 -*-
"""
经济关键词提取 + 用词强度分析 + 板块映射 + 信号打分
"""
import json
import re
import yaml
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

import jieba

DICT_PATH = Path(__file__).parent / "economic_dict.yaml"
DATA_DIR = Path(__file__).parent.parent / "data"
DAILY_DIR = DATA_DIR / "daily"
ANALYTICS_DIR = DATA_DIR / "analytics"


def load_dict() -> dict:
    """加载经济词库"""
    with open(DICT_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def build_keyword_sets(econ_dict: dict) -> tuple[set, dict, dict, dict]:
    """构建查找用的集合和映射"""
    # 经济判断关键词集合
    economy_kw = set(econ_dict['economy_keywords'])

    # 行业关键词 → 板块名映射
    kw_to_sector = {}
    sector_stocks = {}
    for sector_name, sector_data in econ_dict['sectors'].items():
        for kw in sector_data['keywords']:
            kw_to_sector[kw] = sector_name
        sector_stocks[sector_name] = sector_data.get('stocks', [])

    # 用词强度映射
    intensity_map = {}
    for level, words in econ_dict['intensity_words'].items():
        for w in words:
            intensity_map[w] = level

    return economy_kw, kw_to_sector, sector_stocks, intensity_map


def is_economy_related(title: str, text: str, economy_kw: set) -> bool:
    """判断新闻是否经济相关"""
    content = (title + ' ' + text).lower()
    for kw in economy_kw:
        if kw in content:
            return True
    return False


def extract_economy_keywords(title: str, text: str, economy_kw: set) -> list[str]:
    """提取经济关键词"""
    content = title + ' ' + text
    found = []
    for kw in economy_kw:
        if kw in content:
            found.append(kw)
    return found


def extract_sector_keywords(title: str, text: str, kw_to_sector: dict) -> list[str]:
    """提取板块相关关键词"""
    content = title + ' ' + text
    found = []
    for kw, sector in kw_to_sector.items():
        if kw in content:
            found.append(kw)
    return found


def detect_intensity(text: str, intensity_map: dict) -> list[dict]:
    """检测用词强度"""
    found = []
    for word, level in intensity_map.items():
        if word in text:
            found.append({'word': word, 'level': level})
    return found


def detect_policy_level(title: str, text: str) -> str:
    """检测政策级别"""
    content = title + ' ' + text
    if '国常会' in content or '国务院常务会议' in content:
        return '国常会'
    if '中央政治局' in content:
        return '中央政治局'
    if '国务院' in content:
        return '国务院'
    if '发改委' in content or '国家发展改革委' in content:
        return '国家发改委'
    if '工信部' in content:
        return '工信部'
    if '财政部' in content:
        return '财政部'
    if '央行' in content or '人民银行' in content:
        return '央行'
    return ''


def extract_numbers(text: str) -> list[dict]:
    """提取关键数字指标"""
    patterns = [
        (r'(\d+\.?\d*)\s*万亿', '万亿'),
        (r'(\d+\.?\d*)\s*千亿', '千亿'),
        (r'投资\s*(\d+\.?\d*)\s*(?:亿元|亿)', '亿'),
        (r'同比(?:增长|增加|上涨|上升)\s*(\d+\.?\d*)\s*%', '同比增长%'),
        (r'同比(?:下降|减少|回落)\s*(\d+\.?\d*)\s*%', '同比下降%'),
        (r'销售\s*(\d+[\d,]*)\s*(?:台|辆|套|件)', '销量'),
    ]
    results = []
    for pattern, label in patterns:
        for m in re.finditer(pattern, text):
            results.append({'value': m.group(0), 'label': label})
    return results


def compute_signal_score(
    frequency: int,
    prev_frequency: int,
    policy_level: str,
    intensity_level: str,
    is_first_mention: bool,
    scoring_config: dict
) -> int:
    """计算投资信号分数 (0-100)"""
    # 频率分 (0-25)
    max_freq = max(frequency, 1)
    freq_score = min(25, max_freq * 5)

    # 加速度分 (0-25)
    if prev_frequency == 0:
        accel_score = 25 if frequency > 0 else 0
    else:
        ratio = frequency / prev_frequency
        if ratio >= 3:
            accel_score = 25
        elif ratio >= 2:
            accel_score = 20
        elif ratio >= 1.5:
            accel_score = 15
        elif ratio >= 1:
            accel_score = 10
        else:
            accel_score = 5

    # 政策级别分 (0-20)
    policy_scores = scoring_config.get('policy_levels', {})
    pol_score = policy_scores.get(policy_level, 30) * 0.2

    # 用词强度分 (0-15)
    intensity_scores = scoring_config.get('intensity_scores', {})
    int_score = intensity_scores.get(intensity_level, 10) * 0.15

    # 首次出现分 (0-15)
    first_score = 15 if is_first_mention else 0

    total = min(100, int(freq_score + accel_score + pol_score + int_score + first_score))
    return total


def analyze_daily(date_str: str = None) -> dict:
    """分析某天的新闻数据"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')

    daily_path = DAILY_DIR / f"{date_str}.json"
    if not daily_path.exists():
        print(f'❌ 未找到数据: {daily_path}')
        return {}

    with open(daily_path, 'r', encoding='utf-8') as f:
        daily_data = json.load(f)

    econ_dict = load_dict()
    economy_kw, kw_to_sector, sector_stocks, intensity_map = build_keyword_sets(econ_dict)

    # 分析每条新闻
    analyzed_articles = []
    daily_sector_hits = defaultdict(lambda: {'count': 0, 'articles': [], 'keywords': set()})
    daily_economy_kws = defaultdict(int)
    daily_intensities = defaultdict(int)
    daily_policy_levels = []

    for art in daily_data.get('articles', []):
        if not art.get('text') and not art.get('title'):
            continue

        title = art.get('title', '')
        text = art.get('text', '')

        # 经济相关性
        is_econ = is_economy_related(title, text, economy_kw)
        econ_kws = extract_economy_keywords(title, text, economy_kw) if is_econ else []

        # 板块映射
        sector_kws = extract_sector_keywords(title, text, kw_to_sector)
        hit_sectors = set()
        for kw in sector_kws:
            sector = kw_to_sector[kw]
            hit_sectors.add(sector)
            daily_sector_hits[sector]['count'] += 1
            daily_sector_hits[sector]['keywords'].add(kw)

        for sector in hit_sectors:
            daily_sector_hits[sector]['articles'].append({
                'title': title,
                'url': art.get('url', ''),
            })

        # 记录经济关键词
        for kw in econ_kws:
            daily_economy_kws[kw] += 1

        # 用词强度
        intensities = detect_intensity(text, intensity_map)
        for inten in intensities:
            daily_intensities[inten['level']] += 1

        # 政策级别
        policy_level = detect_policy_level(title, text)
        if policy_level:
            daily_policy_levels.append(policy_level)

        # 数字指标
        numbers = extract_numbers(text)

        # 最高强度级别
        max_intensity = ''
        intensity_order = {'early': 1, 'advancing': 2, 'intensive': 3, 'results': 4}
        for inten in intensities:
            if intensity_order.get(inten['level'], 0) > intensity_order.get(max_intensity, 0):
                max_intensity = inten['level']

        analyzed_articles.append({
            **art,
            'is_economy': is_econ,
            'economy_keywords': econ_kws,
            'sector_keywords': sector_kws,
            'hit_sectors': list(hit_sectors),
            'policy_level': policy_level,
            'intensity_level': max_intensity,
            'intensity_words': [i['word'] for i in intensities],
            'key_numbers': numbers,
        })

    # 转换 set 为 list（JSON 序列化）
    for sector_data in daily_sector_hits.values():
        sector_data['keywords'] = list(sector_data['keywords'])

    # 统计结果
    economy_count = sum(1 for a in analyzed_articles if a.get('is_economy'))
    result = {
        'date': date_str,
        'analyzed_at': datetime.now().isoformat(),
        'total_articles': len(analyzed_articles),
        'economy_count': economy_count,
        'articles': analyzed_articles,
        'daily_keywords': dict(daily_economy_kws),
        'daily_sectors': dict(daily_sector_hits),
        'daily_intensities': dict(daily_intensities),
        'daily_policy_levels': daily_policy_levels,
        'summary': _generate_summary(analyzed_articles, daily_sector_hits, daily_economy_kws),
    }

    # 保存
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ANALYTICS_DIR / f"{date_str}.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'📊 分析完成: {economy_count}/{len(analyzed_articles)} 条经济相关')
    print(f'🏷️ 涉及板块: {", ".join(daily_sector_hits.keys())}')
    print(f'📈 用词强度: {dict(daily_intensities)}')
    print(f'💾 已保存: {out_path}')

    return result


def _generate_summary(articles: list, sectors: dict, keywords: dict) -> str:
    """生成当日经济摘要"""
    econ_articles = [a for a in articles if a.get('is_economy')]
    if not econ_articles:
        return '今日无重要经济相关新闻。'

    parts = []
    if sectors:
        sector_names = list(sectors.keys())[:5]
        parts.append(f"涉及板块：{'、'.join(sector_names)}")

    key_numbers = []
    for a in econ_articles:
        for n in a.get('key_numbers', []):
            key_numbers.append(n['value'])
    if key_numbers:
        parts.append(f"关键数据：{'; '.join(key_numbers[:5])}")

    return ' | '.join(parts)


def analyze_multi_period(date_str: str = None) -> dict:
    """多周期分析（日/周/月/年）"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')

    date = datetime.strptime(date_str, '%Y%m%d')
    periods = {
        'daily': 1,
        'weekly': 7,
        'monthly': 30,
        'half_year': 180,
        'yearly': 365,
    }

    results = {}
    for period_name, days in periods.items():
        sector_agg = defaultdict(lambda: {'count': 0, 'keywords': defaultdict(int), 'articles': []})
        kw_agg = defaultdict(int)

        for d in range(days):
            check_date = (date - timedelta(days=d)).strftime('%Y%m%d')
            analytics_path = ANALYTICS_DIR / f"{check_date}.json"
            if not analytics_path.exists():
                continue

            with open(analytics_path, 'r', encoding='utf-8') as f:
                day_data = json.load(f)

            for sector, sdata in day_data.get('daily_sectors', {}).items():
                sector_agg[sector]['count'] += sdata.get('count', 0)
                for kw in sdata.get('keywords', []):
                    sector_agg[sector]['keywords'][kw] += 1

            for kw, cnt in day_data.get('daily_keywords', {}).items():
                kw_agg[kw] += cnt

        # 排序
        sorted_sectors = sorted(sector_agg.items(), key=lambda x: x[1]['count'], reverse=True)
        sorted_kws = sorted(kw_agg.items(), key=lambda x: x[1], reverse=True)

        results[period_name] = {
            'sectors': [
                {
                    'name': name,
                    'count': data['count'],
                    'keywords': dict(sorted(data['keywords'].items(), key=lambda x: x[1], reverse=True)[:10]),
                }
                for name, data in sorted_sectors
            ],
            'top_keywords': sorted_kws[:30],
        }

    # 保存
    out_path = ANALYTICS_DIR / "multi_period.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'periods': results}, f, ensure_ascii=False, indent=2)

    print(f'📊 多周期分析完成: {out_path}')
    for period_name, data in results.items():
        top = [f"{s['name']}({s['count']})" for s in data['sectors'][:3]]
        print(f'  {period_name}: {", ".join(top) if top else "无数据"}')

    return results


if __name__ == '__main__':
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    analyze_daily(date_str)
    analyze_multi_period(date_str)
