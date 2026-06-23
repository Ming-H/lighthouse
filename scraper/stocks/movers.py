# -*- coding: utf-8 -*-
"""movers.py — 近一周/1月/3月 涨幅 top5（有序数组）+ 多周期共振（疯涨主线）+ K线 sparkline。

帮筛「近期疯狂涨价」的股：多周期共振 = 持续疯涨主线（非一日脉冲）。
sparkline 用 akshare 前复权收盘价，A 股涨红跌绿。非投资建议。
"""
import os
os.environ['NO_PROXY'] = '*'
import json
import subprocess
import akshare as ak

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CLI = os.path.expanduser("~/.claude/skills/hithink-market-query/scripts/cli.py")
OUT = os.path.join(ROOT, "site", "data", "picks", "movers.json")
# (key, 问财措辞, K线天数) —— 顺序即页面顺序：周→月→3月
PERIODS = [("1w", "近一周", 7), ("1m", "近一个月", 30), ("3m", "近三个月", 90)]
PLABEL = {"1w": "周", "1m": "月", "3m": "3月"}


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
    col = "var(--crimson)" if prices[-1] >= prices[0] else "var(--growth)"
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
    try:
        d = json.loads(r.stdout[r.stdout.find("{"):])
    except Exception:
        return []
    items = d.get("datas") or []
    chkey = next((k for k in (items[0] if items else {}) if ("涨跌幅[" in k and "-" in k)), None)
    out = []
    for it in items[:5]:
        ch = _num(it.get(chkey)) if chkey else None
        if ch is None:
            continue
        out.append({"code": it.get("股票代码"), "name": it.get("股票简称"),
                    "price": it.get("最新价"), "ch": ch})
    return out


def build():
    periods = []
    appear = {}
    cache = {}
    for key, label, days in PERIODS:
        top5 = query_top5(label)
        for s in top5:
            c = s["code"]
            if c not in cache:
                cache[c] = kline(c, days)
            s["spark"] = cache[c]
            if c not in appear:
                appear[c] = {"code": c, "name": s["name"], "keys": [], "ch_map": {}, "spark": s["spark"]}
            appear[c]["keys"].append(key)
            appear[c]["ch_map"][key] = s["ch"]
        periods.append({"key": key, "label": label, "stocks": top5})

    # 共振：出现在 ≥2 个周期 = 持续疯涨主线；按周期数 + 总涨幅排
    resonance = []
    for v in appear.values():
        if len(v["keys"]) >= 2:
            v["period_ch"] = [{"p": PLABEL[k], "ch": v["ch_map"][k]} for k in v["keys"]]
            v["n"] = len(v["keys"])
            v["total"] = sum(v["ch_map"].values())
            resonance.append(v)
    resonance.sort(key=lambda x: (x["n"], x["total"]), reverse=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"periods": periods, "resonance": resonance}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("✓ 三周期 + 共振 → movers.json")
    print("  共振主线:", ", ".join(f"{r['name']}({r['n']}周期)" for r in resonance) or "无")


if __name__ == "__main__":
    build()
