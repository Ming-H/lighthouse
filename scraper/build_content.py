# -*- coding: utf-8 -*-
"""
Hugo 内容生成器
将分析结果 JSON → Hugo Markdown 文件
"""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

DATA_DIR = Path(__file__).parent.parent / "data"
ANALYTICS_DIR = DATA_DIR / "analytics"
DAILY_DIR = DATA_DIR / "daily"
CONTENT_DIR = Path(__file__).parent.parent / "site" / "content"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def sanitize_for_yaml(text: str) -> str:
    """清理文本中会导致 YAML/JSON 解析失败的字符"""
    text = text.replace('"', "'")
    text = text.replace('\\', '')
    text = text.replace('%', '%%')
    text = text.replace('\n', ' ')
    return text.strip()


def build_daily_page(date_str: str) -> bool:
    """生成每日新闻页面"""
    analytics = load_json(ANALYTICS_DIR / f"{date_str}.json")
    if not analytics:
        return False

    date_fmt = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:8])}日"
    articles = analytics.get('articles', [])
    economy_count = analytics.get('economy_count', 0)

    # Front matter
    fm = f"""---
title: "新闻联播 · {date_fmt}"
date: "{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
draft: false
layout: "daily"
economy_count: {economy_count}
total_count: {len(articles)}
---
"""

    # Body
    body = f"# 📺 新闻联播 · {date_fmt}\n\n"
    body += f"共 **{len(articles)}** 条新闻，其中 **{economy_count}** 条经济相关\n\n"
    body += "---\n\n"

    for art in articles:
        if not art.get('text') and not art.get('title'):
            continue

        is_econ = art.get('is_economy', False)
        icon = "💰" if is_econ else "📰"
        title = art.get('title', '').replace('"', '\\"')

        body += f"### {icon} {title}\n\n"

        # 经济标签
        tags = []
        if art.get('hit_sectors'):
            tags.extend(art.get('hit_sectors', []))
        if art.get('economy_keywords'):
            tags.extend(art.get('economy_keywords', [])[:5])
        if tags:
            body += f"> 🏷️ {' · '.join(tags[:8])}\n\n"

        # 用词强度
        intensity = art.get('intensity_level', '')
        if intensity:
            intensity_emoji = {'early': '🟡探索', 'advancing': '🟠推进', 'intensive': '🔴大力', 'results': '⚪成果'}
            body += f"> 📈 用词强度: {intensity_emoji.get(intensity, intensity)}\n\n"

        # 政策级别
        policy = art.get('policy_level', '')
        if policy:
            body += f"> 🏛️ 政策级别: {policy}\n\n"

        # 关键数据
        numbers = art.get('key_numbers', [])
        if numbers:
            nums = ' | '.join(n['value'] for n in numbers[:5])
            body += f"> 📊 关键数据: {nums}\n\n"

        # 正文
        text = art.get('text', '')
        if text:
            body += f"{text}\n\n"

        # 链接
        url = art.get('url', '')
        if url:
            body += f"[🔗 查看视频]({url})\n\n"

        body += "---\n\n"

    # 写入文件
    out_dir = CONTENT_DIR / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fm + body)

    print(f'  ✅ 每日新闻页: {out_path.name}')
    return True


def build_alerts_page(date_str: str) -> bool:
    """生成异动预警页面"""
    signals = load_json(ANALYTICS_DIR / "signals.json")
    if not signals:
        return False

    date_fmt = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:8])}日"

    fm = f"""---
title: "🚨 异动预警 · {date_fmt}"
date: "{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
draft: false
layout: "alerts"
---
"""

    body = f"# 🚨 异动预警 · {date_fmt}\n\n"

    alerts = signals.get('alerts', [])
    if not alerts:
        body += "今日无异动预警。\n"
    else:
        # 按级别分组
        for level in ['red', 'yellow', 'green', 'white']:
            level_alerts = [a for a in alerts if a.get('level') == level]
            if not level_alerts:
                continue

            level_info = {
                'red': ('🔴 突发升温', '关键词出现频率突然飙升，可能预示板块异动'),
                'yellow': ('🟡 首次密集', '关键词首次在单日密集出现，新政策信号'),
                'green': ('🟢 持续升温', '关键词连续多天出现，政策持续关注'),
                'white': ('⚪ 消失预警', '之前高频关键词消失，关注度转移'),
            }
            title, desc = level_info.get(level, (level, ''))

            body += f"## {title}\n\n"
            body += f"*{desc}*\n\n"

            for a in level_alerts:
                name = a.get('sector', a.get('keyword', ''))
                body += f"- **{name}** — {a.get('detail', '')}\n"

            body += "\n"

    out_dir = CONTENT_DIR / "alerts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "_index.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fm + body)

    print(f'  ✅ 异动预警页: alerts/_index.md')
    return True


def build_sectors_page(date_str: str) -> bool:
    """生成板块热力图页面"""
    signals = load_json(ANALYTICS_DIR / "signals.json")
    multi = load_json(ANALYTICS_DIR / "multi_period.json")

    if not signals:
        return False

    date_fmt = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:8])}日"

    fm = f"""---
title: "🗺️ 板块热力图 · {date_fmt}"
date: "{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
draft: false
layout: "sectors"
---
"""

    body = f"# 🗺️ 板块热力图 · {date_fmt}\n\n"

    scores = signals.get('sector_scores', [])
    if not scores:
        body += "暂无板块数据。\n"
    else:
        body += "## 本周板块信号排行\n\n"
        body += "| 信号 | 板块 | 分数 | 趋势 | 次数 | 龙头股 |\n"
        body += "|:----:|:-----|:----:|:----:|:----:|:-------|\n"

        for s in scores:
            signal_emoji = '🔴' if s['score'] >= 80 else '🟡' if s['score'] >= 50 else '⚪'
            stocks = s.get('stocks', [])
            stock_names = ' · '.join(st['name'] for st in stocks[:3])
            trend = s.get('trend', '')
            trend_display = f'⬆️{trend}' if 'NEW' in trend or '+' in str(trend) else f'⬇️{trend}'

            body += f"| {signal_emoji} | **{s['sector']}** | {s['score']} | {trend_display} | {s['week_count']}次/周 | {stock_names} |\n"

        body += "\n\n"

        # 触发新闻详情
        body += "## 📰 触发新闻\n\n"
        for s in scores[:5]:
            body += f"### {s['sector']} ({s['score']}分)\n\n"
            for art in s.get('trigger_articles', [])[:3]:
                body += f"- {art.get('date', '')} {art.get('title', '')}\n"
            body += "\n"

    out_dir = CONTENT_DIR / "sectors"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "_index.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fm + body)

    print(f'  ✅ 板块热力图: sectors/_index.md')
    return True


def build_lifecycle_page(date_str: str) -> bool:
    """生成政策生命周期页面"""
    signals = load_json(ANALYTICS_DIR / "signals.json")
    if not signals:
        return False

    date_fmt = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:8])}日"

    fm = f"""---
title: "🔄 政策生命周期 · {date_fmt}"
date: "{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
draft: false
layout: "lifecycle"
---
"""

    body = f"# 🔄 政策生命周期 · {date_fmt}\n\n"

    lifecycles = signals.get('lifecycles', {})
    if not lifecycles:
        body += "暂无生命周期数据。\n"
    else:
        body += "> 政策生命周期：探索研究 → 积极推进 → 密集政策期 → 成果显现 → 退潮\n\n"

        stage_order = {'探索研究': 1, '积极推进': 2, '稳步推进': 2, '密集政策期': 3, '成果显现': 4}

        for name, lc in sorted(lifecycles.items(), key=lambda x: stage_order.get(x[1].get('stage', ''), 0)):
            stage = lc.get('stage', '未知')
            first = lc.get('first_seen', 'N/A')
            recent = lc.get('recent_hit_count', 0)

            stage_emoji = {'探索研究': '🟡', '积极推进': '🟠', '稳步推进': '🟠',
                           '密集政策期': '🔴', '成果显现': '⚪', '未出现': '⚫'}

            body += f"## {stage_emoji.get(stage, '⚪')} {name} — {stage}\n\n"
            body += f"- 首次出现: {first}\n"
            body += f"- 近7天出现: {recent}次\n"
            body += f"- 累计出现: {lc.get('hit_count', 0)}次\n\n"

    out_dir = CONTENT_DIR / "lifecycle"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "_index.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fm + body)

    print(f'  ✅ 生命周期页: lifecycle/_index.md')
    return True


def build_hotspots_page(date_str: str) -> bool:
    """生成经济热点页面"""
    multi = load_json(ANALYTICS_DIR / "multi_period.json")
    if not multi:
        return False

    date_fmt = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:8])}月"

    fm = f"""---
title: "🔥 经济热点 · {date_fmt}"
date: "{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
draft: false
layout: "hotspots"
---
"""

    body = f"# 🔥 经济热点 · {date_fmt}\n\n"

    periods = multi.get('periods', {})
    period_names = {
        'daily': ('今日热点', '当日出现的经济关键词'),
        'weekly': ('本周热点', '近 7 天高频关键词'),
        'monthly': ('本月热点', '近 30 天趋势'),
        'yearly': ('年度热点', '近 365 天 Top 关键词'),
    }

    for period_key, (period_title, period_desc) in period_names.items():
        data = periods.get(period_key, {})
        top_kws = data.get('top_keywords', [])

        body += f"## {period_title}\n\n"
        body += f"*{period_desc}*\n\n"

        if not top_kws:
            body += "暂无数据\n\n"
            continue

        body += "| 排名 | 关键词 | 出现次数 |\n|:----:|:-------|:--------:|\n"
        for i, (kw, count) in enumerate(top_kws[:20], 1):
            body += f"| {i} | **{kw}** | {count} |\n"
        body += "\n"

        # 板块排行
        sectors = data.get('sectors', [])
        if sectors:
            body += "**涉及板块**: " + ' · '.join(f"{s['name']}({s['count']})" for s in sectors[:8]) + "\n\n"

        body += "---\n\n"

    out_dir = CONTENT_DIR / "hotspots"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "_index.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fm + body)

    print(f'  ✅ 经济热点页: hotspots/_index.md')
    return True


def build_homepage(date_str: str) -> bool:
    """生成首页"""
    signals = load_json(ANALYTICS_DIR / "signals.json")
    analytics = load_json(ANALYTICS_DIR / f"{date_str}.json")
    multi = load_json(ANALYTICS_DIR / "multi_period.json")

    date_fmt = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:8])}日"
    economy_count = analytics.get('economy_count', 0) if analytics else 0
    total = analytics.get('total_articles', 0) if analytics else 0

    fm = f"""---
title: "📺 央视联播 · 投资参考"
description: "新闻联播经济信号追踪，捕捉投资机会"
layout: "home"
---
"""

    body = f"# 📺 央视联播 · 投资参考\n\n"
    body += f"**{date_fmt}** · 共 {total} 条新闻 · {economy_count} 条经济相关\n\n"

    # 预警摘要
    if signals:
        alerts = signals.get('alerts', [])
        red_alerts = [a for a in alerts if a.get('level') == 'red']
        if red_alerts:
            body += "## 🚨 今日预警\n\n"
            for a in red_alerts[:5]:
                name = a.get('sector', a.get('keyword', ''))
                body += f"- 🔴 **{name}** — {a.get('detail', '')}\n"
            body += "\n"

    # 板块热度 Top 5
    if signals:
        scores = signals.get('sector_scores', [])[:5]
        if scores:
            body += "## 🗺️ 板块热度 Top 5\n\n"
            for s in scores:
                emoji = '🔴' if s['score'] >= 80 else '🟡' if s['score'] >= 50 else '⚪'
                stocks = s.get('stocks', [])
                stock_str = ' · '.join(st['name'] for st in stocks[:3])
                body += f"{emoji} **{s['sector']}** {s['score']}分 {s.get('trend', '')} — {stock_str}\n\n"

    # 导航链接
    body += "## 📋 板块导航\n\n"
    body += "- [📰 每日新闻](/daily/)\n"
    body += "- [🔥 经济热点](/hotspots/)\n"
    body += "- [🗺️ 板块热力图](/sectors/)\n"
    body += "- [🚨 异动预警](/alerts/)\n"
    body += "- [🔄 政策生命周期](/lifecycle/)\n\n"

    out_path = CONTENT_DIR / "_index.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fm + body)

    print(f'  ✅ 首页: _index.md')
    return True


def build_all(date_str: str = None):
    """生成所有页面"""
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')

    print(f'📝 生成 Hugo 内容: {date_str}')
    print('-' * 30)

    build_homepage(date_str)
    build_daily_page(date_str)
    build_hotspots_page(date_str)
    build_sectors_page(date_str)
    build_alerts_page(date_str)
    build_lifecycle_page(date_str)

    print(f'\n✅ 内容生成完成')


if __name__ == '__main__':
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    build_all(date_str)
