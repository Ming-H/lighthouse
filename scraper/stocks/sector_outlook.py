# -*- coding: utf-8 -*-
"""sector_outlook.py — 板块景气分析：静水景气标签 × CAN SLIM 板块强度 × 政策催化。

把旧的 sectors/charts/hotspots/alerts/lifecycle（纯新闻联播频次）升级为结合方法论的板块景气：
- 静水：行业→时代景气标签（主线 α / 周期 / 防御）
- CAN SLIM：板块内是否有今日候选股 + 板块龙头
- 政策催化：新闻联播提及强度（signals.sector_scores）
输出 site/data/picks/sectors.json，供板块景气页渲染。非投资建议。
"""
import os
import json
import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SIGNALS = os.path.join(ROOT, "data", "analytics", "signals.json")
LATEST = os.path.join(ROOT, "site", "data", "picks", "latest.json")
OUT = os.path.join(ROOT, "site", "data", "picks", "sectors.json")

# 静水：时代景气主线（高 α） / 周期 / 防御 —— 基于经济词典板块名
HOT_MAIN = {"半导体", "AI人工智能", "机器人", "新能源", "新能源汽车", "数据要素"}
CYCLE = {"基建投资", "工程机械", "地下管网", "钢铁", "煤炭", "石油能源", "黄金"}
DEFENSE = {"消费", "医药", "银行金融", "农业", "房地产", "外贸"}


def hot_label(sector):
    if sector in HOT_MAIN:
        return ("主线", "offense", "green")
    if sector in CYCLE:
        return ("周期", "watch", "yellow")
    if sector in DEFENSE:
        return ("防御", "defense", "red")
    return ("中性", "watch", "muted")


def build():
    if not os.path.exists(SIGNALS):
        print("无 signals.json，跳过"); return
    sig = json.load(open(SIGNALS, encoding="utf-8"))
    latest = json.load(open(LATEST, encoding="utf-8")) if os.path.exists(LATEST) else {}
    score_map = {s["code"]: s["score"] for s in latest.get("top20", [])}
    # 板块关键词（economic_dict）→ 把 CAN SLIM 候选按名称归入板块
    sector_kw = {}
    try:
        econ = yaml.safe_load(open(os.path.join(ROOT, "scraper", "economic_dict.yaml"), encoding="utf-8")) or {}
        sector_kw = {k: (v.get("keywords", []) or []) for k, v in (econ.get("sectors") or {}).items()}
    except Exception:
        pass

    secs = sig.get("sector_scores", []) or []
    out = []
    for s in secs:
        sector = s.get("sector", "")
        label, tone, lvl = hot_label(sector)
        leaders = s.get("stocks", []) or []
        kws = sector_kw.get(sector, [])
        cands = [{"code": st["code"], "name": st["name"], "score": st["score"]}
                 for st in latest.get("top20", [])
                 if kws and any(kw in st["name"] for kw in kws)]
        out.append({
            "sector": sector,
            "hot_label": label, "tone": tone, "lvl": lvl,
            "policy_score": s.get("score", 0),
            "week_count": s.get("week_count", 0),
            "trend": s.get("trend", ""),
            "intensity": s.get("intensity_level", ""),
            "policy_level": s.get("policy_level", ""),
            "leaders": [{"code": l.get("code", ""), "name": l.get("name", "")} for l in leaders[:5]],
            "candidates": cands,
            "has_canslim": len(cands) > 0,
        })
    # 排序：景气主线优先 → 政策分
    main_rank = {"主线": 3, "周期": 2, "中性": 1, "防御": 0}
    out.sort(key=lambda x: (main_rank.get(x["hot_label"], 1), x["policy_score"]), reverse=True)

    # 异动摘要（取 alerts 前 5，并入同一页，免单独 alerts 页）
    alerts = (sig.get("alerts") or [])[:5]

    res = {"date": sig.get("date"), "sectors": out[:15], "alerts": alerts}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    main_n = sum(1 for x in out if x["hot_label"] == "主线")
    print(f"✓ 板块景气 {sig.get('date')}：{len(out)} 板块（主线 {main_n}）→ sectors.json")


if __name__ == "__main__":
    build()
