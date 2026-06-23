# -*- coding: utf-8 -*-
"""movers.py — 近一周/1月/3月涨幅榜 top5 + 真实股价 sparkline（akshare K 线）。

笑傲股市 L（领涨强度）+ 真实走势图。sparkline 用 akshare 前复权收盘价，
A 股涨红跌绿。输出 site/data/picks/movers.json（三周期 + SVG）。非投资建议。
"""
import os
os.environ['NO_PROXY'] = '*'   # 绕本地代理取 K 线
import json
import subprocess
import akshare as ak

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CLI = os.path.expanduser("~/.claude/skills/hithink-market-query/scripts/cli.py")
OUT = os.path.join(ROOT, "site", "data", "picks", "movers.json")
# (key, 问财措辞, K线天数)
PERIODS = [("1w", "近一周", 7), ("1m", "近一个月", 30), ("3m", "近三个月", 90)]


def _num(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def sparkline(prices, w=140, h=36):
    if not prices or len(prices) < 2:
        return ""
    mn, mx = min(prices), max(prices)
    rng = mx - mn or 1
    n = len(prices)
    pts = " ".join(f"{w*i/(n-1):.1f},{h-3-(h-6)*(p-mn)/rng:.1f}" for i, p in enumerate(prices))
    col = "var(--crimson)" if prices[-1] >= prices[0] else "var(--growth)"  # A股涨红跌绿
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" stroke-linejoin="round"/></svg>')


def kline(code, days):
    try:
        sym = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        df = ak.stock_zh_a_hist(symbol=sym, period='daily', adjust='qfq')
        return sparkline([float(x) for x in df['收盘'].tail(days).tolist()])
    except Exception:
        return ""


def query_top5(label):
    r = subprocess.run(["python3", CLI, "--query", f"{label}涨幅最大的前5只A股股票", "--limit", "5"],
                       capture_output=True, text=True, timeout=90)
    raw = r.stdout
    try:
        d = json.loads(raw[raw.find("{"):])
    except Exception:
        return []
    items = d.get("datas") or []
    chkey = None
    if items:
        for k in items[0]:
            if "涨跌幅[" in k and "-" in k:
                chkey = k
                break
    out = []
    for it in items[:5]:
        ch = _num(it.get(chkey)) if chkey else None
        if ch is None:
            continue
        out.append({"code": it.get("股票代码"), "name": it.get("股票简称"),
                    "price": it.get("最新价"), "ch": ch})
    return out


def build():
    result = {}
    cache = {}   # code → spark 去重
    for key, label, days in PERIODS:
        top5 = query_top5(label)
        for s in top5:
            c = s["code"]
            if c not in cache:
                cache[c] = kline(c, days)
            s["spark"] = cache[c]
            s["tags"] = ["超买⚠"] if s["ch"] >= 100 else (["强势"] if s["ch"] >= 30 else [])
        result[key] = {"label": label, "stocks": top5}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✓ 涨幅榜 三周期 top5 → movers.json")
    for key in result:
        print(f"  {result[key]['label']}: " + ", ".join(f"{s['name']}({s['ch']}%)" for s in result[key]['stocks']))


if __name__ == "__main__":
    build()
