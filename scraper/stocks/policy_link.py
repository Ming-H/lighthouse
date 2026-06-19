# -*- coding: utf-8 -*-
"""policy_link.py — 新闻联播当日板块信号 → 政策催化股票（CAN SLIM 的 N）。

读最新 analytics 的 daily_sectors（新闻联播当日提及的板块）+ economic_dict（板块→代表股），
生成 site/data/picks/policy.json，供 daily-picks 页展示「今日政策催化」。
这是宏观（新闻联播）与个股（N 催化）的咬合点。非投资建议。
"""
import os
import glob
import json

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
ANALYTICS = os.path.join(ROOT, "data", "analytics")
DICT = os.path.join(ROOT, "scraper", "economic_dict.yaml")
OUT = os.path.join(ROOT, "site", "data", "picks", "policy.json")


def latest_analytics():
    files = [f for f in glob.glob(os.path.join(ANALYTICS, "*.json"))
             if os.path.basename(f)[:8].isdigit()]
    return sorted(files, reverse=True)[0] if files else None


def _weight(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return float(v.get("count") or v.get("score") or v.get("intensity") or 0)
    if isinstance(v, list):
        return float(len(v))
    return 0.0


def build():
    f = latest_analytics()
    if not f:
        print("无 analytics，跳过")
        return
    d = json.load(open(f, encoding="utf-8"))
    date = str(d.get("date", ""))
    daily = d.get("daily_sectors") or d.get("sectors") or {}
    if isinstance(daily, list):
        daily = {x.get("sector") or x.get("name"): x for x in daily if isinstance(x, dict)}
    econ = yaml.safe_load(open(DICT, encoding="utf-8")) or {}
    sectors_def = econ.get("sectors", {}) or {}
    cats = []
    for sector, val in daily.items():
        sdef = sectors_def.get(sector)
        if not sdef:
            continue
        stocks = sdef.get("stocks", []) or []
        cats.append({
            "sector": sector,
            "weight": _weight(val),
            "stocks": [{"code": s.get("code", ""), "name": s.get("name", "")} for s in stocks[:6]],
        })
    cats.sort(key=lambda x: x["weight"], reverse=True)
    out = {"date": date, "sectors": cats[:10]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✓ 政策催化 {date}：{len(cats)} 板块命中 → policy.json")
    for c in cats[:6]:
        print(f"  {c['sector']:<8} ({c['weight']:.0f}) → {'、'.join(s['name'] for s in c['stocks'][:3])}")


if __name__ == "__main__":
    build()
