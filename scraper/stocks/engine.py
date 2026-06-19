# -*- coding: utf-8 -*-
"""
engine.py — akshare 全市场 CAN SLIM 打分主流程。

两阶段策略（避免对 5000+ 股逐个拉财务/资金的性能崩溃）：
  阶段1  全市场 spot 一次取数 → 动量/技术面（L 领涨强度 / S 供需）初筛
  阶段2  TOP 候选逐个 enrich → 财务（C/A）+ 主力资金（I）+ 52周高（N）→ 完整七要素
最终输出 TOP20 + 全市场排行（JSON，供 Hugo 页面渲染）。

CI 主数据源（akshare，免费无 key）。本地问财 skill 仅做深度体检，不进此流程。
非投资建议。
"""
import os
import sys
import json
import pandas as pd
import akshare as ak

sys.path.insert(0, os.path.dirname(__file__))
from score import (score_C, score_A, score_N, score_S, score_L, score_I,
                   lighthouse_score, is_excluded)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
PICKS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "site", "data", "picks")


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------- 阶段 1：全市场 spot 快速初筛 ----------------
def fetch_spot() -> pd.DataFrame:
    """东财全市场快照。含价/量比/换手/流通市值/60日&年初至今涨跌幅。"""
    df = ak.stock_zh_a_spot_em()
    df = df.rename(columns={
        "代码": "code", "名称": "name", "最新价": "price",
        "量比": "volume_ratio", "换手率": "turnover",
        "流通市值": "float_mv", "60日涨跌幅": "ch60d", "年初至今涨跌幅": "ch_ytd",
    })
    for c in ["price", "volume_ratio", "turnover", "float_mv", "ch60d", "ch_ytd"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["float_mv_yi"] = df.get("float_mv") / 1e8
    df["st"] = df["name"].astype(str).str.contains(r"ST|\*ST|退", na=False, regex=True)
    df["board"] = df["code"].astype(str).str[0].map(
        {"0": "SZ", "3": "SZ", "6": "SH", "8": "BJ", "4": "BJ"})
    return df


def quick_screen(spot: pd.DataFrame, market_state: str = "watch") -> pd.DataFrame:
    """全市场初筛：用 L（60日涨幅百分位）+ S（供需）打 quick_score。"""
    df = spot.dropna(subset=["ch60d"]).copy()
    df["L"] = df["ch60d"].rank(pct=True) * 100
    rows = []
    for _, r in df.iterrows():
        meta = {"st": bool(r["st"]), "board": r.get("board")}
        excl, reason = is_excluded(meta)
        if excl:
            continue
        s_L = score_L(r["L"])
        s_S = score_S(r.get("volume_ratio"), r.get("turnover"), r.get("float_mv_yi"))
        # 只 L+S 参与，按其权重和归一到 0–100（C/A/N/I 待 enrich）
        w_used = 0.20 + 0.10
        raw = s_L * 0.20 + s_S * 0.10
        quick = raw / w_used if w_used else raw
        rows.append({
            "code": r["code"], "name": r["name"], "price": r.get("price"),
            "float_mv_yi": round(r.get("float_mv_yi") or 0, 1),
            "ch60d": round(r.get("ch60d") or 0, 2),
            "L": round(s_L, 1), "S": round(s_S, 1),
            "quick_score": round(min(100, quick), 1),
        })
    return pd.DataFrame(rows).sort_values("quick_score", ascending=False).reset_index(drop=True)


# ---------------- 阶段 2：候选深度取数 ----------------
def enrich_one(code: str) -> dict:
    """单股深度取数：52周高(N) + 主力资金(I) + 财务(C/A)。全部容错。"""
    out = {"pct_from_high52": None, "main_net_5d": None,
           "quarter_yoy": None, "cagr3": None, "roe": None}
    # 52 周高（N）
    try:
        hist = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        if len(hist):
            high52 = pd.to_numeric(hist["最高"], errors="coerce").tail(252).max()
            last = pd.to_numeric(hist["收盘"], errors="coerce").iloc[-1]
            if high52 and last:
                out["pct_from_high52"] = round((high52 - last) / high52 * 100, 2)
    except Exception:
        pass
    # 主力资金近 5 日净流入（I）
    try:
        mkt = "sh" if str(code).startswith("6") else "sz"
        ff = ak.stock_individual_fund_flow(stock=code, market=mkt)
        if len(ff):
            ff["主力净流入-净额"] = pd.to_numeric(ff["主力净流入-净额"], errors="coerce")
            out["main_net_5d"] = round(ff["主力净流入-净额"].tail(5).sum() / 1e8, 3)  # 亿元
    except Exception:
        pass
    # 财务 C：当季净利同比（stock_financial_abstract，字段随版本变，模糊容错）
    try:
        fa = ak.stock_financial_abstract(symbol=code)
        if fa is not None and len(fa):
            mask = fa.astype(str).apply(lambda r: r.str.contains("净利润", na=False).any(), axis=1)
            net = fa[mask]
            if len(net):
                yoy_cols = [c for c in net.columns if "同比" in str(c)]
                if yoy_cols:
                    out["quarter_yoy"] = _safe_float(net[yoy_cols[0]].iloc[0])
    except Exception:
        pass
    # 财务 A：ROE（stock_financial_analysis_indicator，取最近一期）
    try:
        ind = ak.stock_financial_analysis_indicator(symbol=code)
        if ind is not None and len(ind):
            roe_cols = [c for c in ind.columns if "净资产收益率" in str(c)]
            if roe_cols:
                series = pd.to_numeric(ind[roe_cols[0]], errors="coerce").dropna()
                if len(series):
                    out["roe"] = round(float(series.iloc[0]), 2)
    except Exception:
        pass
    return out


def final_score(row: dict, market_state: str) -> dict:
    """把 quick_screen 行 + enrich 结果合成完整灯塔分。"""
    e = row.get("enrich", {}) or {}
    f = {
        "C": score_C(e.get("quarter_yoy")),
        "A": score_A(e.get("cagr3"), e.get("roe")),
        "N": score_N(e.get("pct_from_high52"), has_catalyst=bool(row.get("catalyst"))),
        "S": row["S"],
        "L": row["L"],
        "I": score_I(e.get("main_net_5d"), None),
    }
    res = lighthouse_score(f, market_state)
    return {**row, "score": res["score"], "factors": res["factors"]}


# ---------------- 主流程 ----------------
def score_market(market_state: str = "watch", enrich_top: int = 100, final_top: int = 20) -> dict:
    spot = fetch_spot()
    quick = quick_screen(spot, market_state)
    # 阶段2：对前 enrich_top 只深度取数
    top = quick.head(enrich_top).to_dict("records")
    for r in top:
        r["enrich"] = enrich_one(r["code"])
        r["score"] = final_score(r, market_state)["score"]
    top.sort(key=lambda x: x["score"], reverse=True)
    result = {
        "market_state": market_state,
        "updated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(quick),
        "top20": top[:final_top],
        "full_rank": quick[["code", "name", "quick_score", "L", "S", "ch60d"]].head(200).to_dict("records"),
    }
    return result


def save(result: dict, name: str = "latest.json"):
    os.makedirs(PICKS_DIR, exist_ok=True)
    path = os.path.join(PICKS_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="watch", choices=["offense", "watch", "defense"])
    ap.add_argument("--enrich-top", type=int, default=50)
    ap.add_argument("--demo", action="store_true", help="仅跑 spot 初筛，不做 enrich（快速验证）")
    a = ap.parse_args()
    # 交易日过滤（节假日 skip）
    try:
        cal = ak.tool_trade_date_hist_sina()
        today = pd.Timestamp.now().strftime("%Y-%m-%d")
        dates = set(pd.to_datetime(cal["trade_date"]).dt.strftime("%Y-%m-%d"))
        if today not in dates:
            print(f"{today} 非交易日，跳过。")
            sys.exit(0)
    except Exception as e:
        print(f"交易日历获取失败（{e}），保守继续。")
    try:
        spot = fetch_spot()
        quick = quick_screen(spot, a.market)
        print(f"全市场初筛完成：{len(quick)} 只，初筛 TOP10：")
        print(quick.head(10)[["code", "name", "quick_score", "L", "S", "ch60d"]].to_string(index=False))
        if not a.demo:
            print(f"\n对前 {a.enrich_top} 只深度取数中…")
            res = score_market(a.market, enrich_top=a.enrich_top)
            p = save(res)
            print(f"\n灯塔分 TOP10（已存 {p}）：")
            for r in res["top20"][:10]:
                print(f"  {r['score']:>5}  {r['code']} {r['name']}  L={r['L']} S={r['S']}")
    except Exception as e:
        # akshare 取数失败（如 CI 海外 IP 被限、接口变动）→ 保留现有数据，不阻塞部署
        print(f"⚠️ 取数失败（{e}），保留现有 picks 数据，不阻塞部署。")
        sys.exit(0)
