#!/usr/bin/env python3
"""
build_moneyflow.py — 每日 A 股资金流向全景页生成器（灯塔 Lighthouse）。

流程：拉 hithink-moneyflow 数据 → 行业细分聚合到申万一级（去同链重复）
      + 概念重叠标注 + 大单结构 + 冠军板块领涨股
      → 生成 Hugo content/moneyflow/YYYY-MM-DD.md。

风格：复用 PaperMod 主题 CSS 变量（--theme/--entry/--primary/--border/--gap），
      字体 Noto Serif SC + IBM Plex Mono，红涨绿跌（A 股惯例）。

非交易日（问财返回空）→ 打印提示并 exit 0（不生成、不部署）。

用法:
  python3 scraper/build_moneyflow.py                 # 今天
  python3 scraper/build_moneyflow.py --date 20260706 # 指定日期
"""
import argparse
import json
import os
import re
import subprocess
import sys
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 本地与 CI 都默认用仓库内 vendored 的 hithink 引擎（scraper/vendor/hithink/，
# flow.py / cli.py 均纯 stdlib，自包含、可查历史日期）。可用 HITHINK_MONEYFLOW_FLOW /
# HITHINK_MARKET_CLI 覆盖（如指向 ~/.claude/skills 里的实时 skill）。
_VENDOR = Path(__file__).resolve().parent / "vendor" / "hithink"
FLOW = Path(os.environ.get("HITHINK_MONEYFLOW_FLOW", str(_VENDOR / "flow.py")))
MARKET_CLI = Path(os.environ.get("HITHINK_MARKET_CLI", str(_VENDOR / "cli.py")))


def _latest_closed_trade_date() -> str:
    """最近一个已收盘的交易日期（北京时区，YYYYMMDD）。

    A 股 15:00 收盘，脚本设计在收盘后（15:30/17:00）跑。GitHub cron 常被延迟，
    一旦跨过北京 0 点，datetime.now()（CI 里是 UTC）会落到次日——此时必须取
    「昨天」（刚收盘的那个交易日），否则按未来日期生成页面 / 查不到当日数据。
    """
    now_bj = datetime.now(timezone(timedelta(hours=8)))
    if now_bj.hour < 15:
        now_bj -= timedelta(days=1)
    return now_bj.strftime("%Y%m%d")
SITE = Path(__file__).resolve().parent.parent / "site"
OUT_DIR = SITE / "content" / "moneyflow"
SOURCE = "同花顺问财（经 hithink-moneyflow）"


# ---------------- 数据获取 ----------------

def run_flow(view, top=10, sector=None, date_str=None):
    """调 hithink-moneyflow flow.py，返回 rows 列表（已解析）。失败/空返回 []。
    date_str: YYYYMMDD，查历史资金流向（None=今日）。"""
    cmd = [sys.executable, str(FLOW), "--view", view, "--top", str(top), "--format", "json"]
    if sector:
        cmd += ["--sector", sector]
    if date_str:
        cmd += ["--date", date_str]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        d = json.loads(r.stdout)
        return d.get("rows", []) if isinstance(d, dict) else []
    except Exception:
        return []


def run_market(query, limit=20):
    """调 hithink-market-query cli（用于概念 stock view 的措辞回退）。返回 datas。"""
    cmd = [sys.executable, str(MARKET_CLI), "--query", query, "--limit", str(limit)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout).get("datas") or []
    except Exception:
        return []


# ---------------- 行业细分 → 申万一级聚合 ----------------

def to_cat(name):
    """细分行业名 → 申万一级近似大类（电子拆分为半导体/面板/消费电子/元件，避免同链混入）。"""
    rules = [
        (r'银行|股份制|农商行', '银行'),
        (r'证券|券商|保险|信托|非银|多元金融', '非银金融'),
        (r'半导|集成电路|芯片', '半导体'),
        (r'光电|光学|显示|面板|LED', '面板显示'),
        (r'消费电子', '消费电子'),
        (r'元件|连接器|印制电路|被动|其他电子', '电子元件'),
        (r'药|医|生物|医疗|器械|疫苗|基因|免疫|CXO|药房|中药', '医药生物'),
        (r'计算机|软件|互联网|数据|系统|信息技术|云|服务器', '计算机'),
        (r'通信|光通信|电信|网络|广电|光模块', '通信'),
        (r'汽车|整车|零部件|锂电|电池|电机|充电', '汽车/新能源'),
        (r'酒|啤酒|白酒|乳|食|饮|肉|味|粮|茶|零食|调味|保健', '食品饮料'),
        (r'家电|厨电|白电|黑电|小家电|空调', '家用电器'),
        (r'游戏|影视|传媒|出版|广告|动漫|营销|视频', '传媒'),
        (r'有色|铜|铝|稀土|黄金|贵金属|钴|镍|锡|锑|钨|小金属|锂', '有色金属'),
        (r'钢|铁|特钢|冶金', '钢铁'),
        (r'煤|石油|石化|化纤|化工|塑|玻|水泥|纤维|涂料|胶|氯|磷|化学|聚氨酯', '基础化工'),
        (r'地产|房地产|建筑|基建|建材|装饰|园林|物业|钢构', '建筑/地产'),
        (r'电力|核电|风电|光伏|环保|水务|燃气|热力|储能|水电', '公用环保'),
        (r'养殖|种植|饲料|肥料|农药|渔|林|牧', '农林牧渔'),
        (r'军|航天|航空|兵器|舰|导弹|国防', '国防军工'),
        (r'机械|设备|自动化|机器人|仪表|工控|机床|轴承|液压', '机械设备'),
        (r'纺|服装|服饰|鞋|珠宝|钟表|化妆', '纺织/轻工'),
        (r'商|贸|零售|连锁|超市|百货|电商|旅游|酒店|餐饮|景区', '商贸社服'),
        (r'港|航运|航空|物流|高速|铁路|船|快递|仓储|机场', '交通运输'),
    ]
    for pat, cat in rules:
        if re.search(pat, name):
            return cat
    return '其他'


def aggregate_categories(inflow_rows, outflow_rows):
    """合并流入/流出细分，按大类聚合净额，正→流入榜、负→流出榜。"""
    cats = {}
    for r in inflow_rows + outflow_rows:
        c = to_cat(r.get('name', ''))
        cats.setdefault(c, {'amount': 0, 'count': 0})
        cats[c]['amount'] += r.get('amount') or 0
        cats[c]['count'] += 1
    inflow = sorted([{'name': k, 'amount': v['amount'], 'count': v['count']}
                     for k, v in cats.items() if v['amount'] > 0],
                    key=lambda x: -x['amount'])
    outflow = sorted([{'name': k, 'amount': v['amount'], 'count': v['count']}
                      for k, v in cats.items() if v['amount'] < 0],
                     key=lambda x: x['amount'])
    return inflow, outflow


# ---------------- 概念重叠标注 ----------------

def tag_concept(name):
    cross = ['AI', '人工', '算力', '芯', '半导', '新能源', '机器', '华为', '苹果', '元宇宙',
             'AR', 'VR', '数据', '云', '安全', '低碳', '碳', '储能', '光伏', '风电', '锂',
             '物联网', '车联', '数字', '智能', '替代', '可控', '信创', '国资云', '低空', '卫星', '6G', '量子']
    strategy = ['股息', '红利', '证金', '持股', '中特估', '央企', '国企', '国资', '融资融券',
                '沪深', '沪股通', '深股通', 'MSCI', '标普', '富时', '蓝筹', '白马', '核心资产',
                '低估', '高送', '回购', '大盘', '小盘', '中盘', '价值', '混改']
    industry = ['药', '医', '酒', '银行', '券商', '保险', '地产', '煤', '钢', '有色', '石油',
                '化工', '玻', '造纸', '纺织', '服装', '游戏', '传媒', '影视', '出版', '养殖',
                '种植', '饲料', '港口', '航运', '酒店', '旅游', '家电', '汽车', '软件', '计算机',
                '通信', '电缆', '水泥', '肥料', '农药', '军', '航天', '机械', '设备', '电子',
                '元件', '电池', '电机', '治疗', '免疫', '疫苗', '系统', '操作']
    for k in cross:
        if k in name:
            return ('🔥', '跨行')
    for k in strategy:
        if k in name:
            return ('📊', '策略')
    for k in industry:
        if k in name:
            return ('🔒', '行业')
    return ('·', '其他')


# ---------------- 渲染 ----------------

def fy(a):
    return '—' if a is None else f"{a / 1e8:+,.1f}"


def fp(p):
    return '' if p is None else f"{p:+.2f}%"


def bar(amt, mx):
    if amt is None or amt == 0:
        return '<div class="mf-bar" style="left:50%;width:0"></div>'
    r = abs(amt) / mx * 50
    return (f'<div class="mf-bar pos" style="width:{r:.2f}%"></div>' if amt > 0
            else f'<div class="mf-bar neg" style="left:{50 - r:.2f}%;width:{r:.2f}%"></div>')


def section(rows, title, sub, is_concept=False):
    amts = [r.get('amount') for r in rows if r.get('amount') is not None]
    mx = max([abs(a) for a in amts], default=1) or 1
    p = [f'<section class="mf-card"><div class="mf-card-h"><h3>{html.escape(title)}</h3>'
         f'<span class="mf-badge">Top{len(rows)}</span></div>'
         f'<p class="mf-sub">{html.escape(sub)}</p><div class="mf-chart">']
    for r in rows:
        name = html.escape(str(r.get('name') or '—'))
        amt = r.get('amount'); pct = r.get('pct'); cnt = r.get('count'); extra = ''
        if is_concept:
            emo, lab = tag_concept(str(r.get('name') or ''))
            extra = f'<span class="mf-ctag {lab}" title="{emo} {lab}">{emo}{lab}</span>'
        elif cnt:
            extra = f'<span class="mf-ctag dim">{cnt}细分</span>'
        cls = 'pos' if (amt or 0) > 0 else ('neg' if (amt or 0) < 0 else '')
        p.append(
            f'<div class="mf-row"><div class="mf-label" title="{name}">{name}{extra}</div>'
            f'<div class="mf-track">{bar(amt, mx)}</div>'
            f'<div class="mf-val {cls}">{fy(amt)}<span class="mf-yi">亿</span>'
            f'<span class="mf-pct">{fp(pct)}</span></div></div>'
        )
    p.append('</div></section>')
    return '\n'.join(p)


def orders_section(rows):
    keys = ['特大单净买入额', '大单净买入额', '小单净买入额']
    allv = [r[k] for r in rows for k in keys if r.get(k) is not None]
    mx = max([abs(v) for v in allv], default=1) or 1

    def cell(v):
        cls = 'pos' if (v or 0) > 0 else ('neg' if (v or 0) < 0 else '')
        if v is None or v == 0:
            b = '<div class="mf-obar"><div class="mf-bar" style="left:50%;width:0"></div></div>'
        elif v > 0:
            r = abs(v) / mx * 50
            b = f'<div class="mf-obar"><div class="mf-bar pos" style="width:{r:.2f}%"></div></div>'
        else:
            r = abs(v) / mx * 50
            b = f'<div class="mf-obar"><div class="mf-bar neg" style="left:{50 - r:.2f}%;width:{r:.2f}%"></div></div>'
        return f'<div class="mf-otd {cls}">{b}<span>{fy(v)}</span></div>'

    p = ['<section class="mf-card wide"><div class="mf-card-h">'
         '<h3>资金性质 · 特大单/大单/小单</h3><span class="mf-badge">行业Top10</span></div>'
         '<p class="mf-sub">主力（特大单+大单）vs 散户（小单）· 看是否"主力进散户出"</p>']
    p.append('<div class="mf-otable"><div class="mf-ohead">'
             '<div>板块</div><div>特大单</div><div>大单</div><div>小单</div></div>')
    for r in rows:
        name = html.escape(str(r.get('name') or '—'))
        cells = ''.join(cell(r.get(k)) for k in keys)
        p.append(f'<div class="mf-orow"><div class="mf-oname" title="{name}">{name}</div>{cells}</div>')
    p.append('</div></section>')
    return '\n'.join(p)


# 资金流向专用 CSS —— 复用 PaperMod 变量，自动跟随站点明暗；红涨绿跌为 A 股数据色
CSS = """
.mf{font-family:var(--font-serif)}
.mf h2{font-family:var(--font-display);font-size:24px;font-weight:700;margin:0 0 4px;letter-spacing:-.01em;color:var(--ink)}
.mf-meta{color:var(--ink-soft);font-size:12.5px;line-height:1.7;margin-bottom:8px;font-family:var(--font-mono)}
.mf-gt{font-family:var(--font-display);font-size:16px;font-weight:600;margin:20px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--brand);display:flex;align-items:baseline;gap:8px;color:var(--ink)}
.mf-gt small{font-family:var(--font-mono);font-size:11px;font-weight:400;color:var(--ink-faint)}
.mf-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--gap);margin-bottom:22px}
.mf-card{background:var(--paper-2);border:1px solid var(--rule);border-radius:var(--radius-lg);padding:16px 18px;box-shadow:var(--shadow)}
.mf-card.wide{grid-column:1/-1}
.mf-card-h{display:flex;align-items:center;justify-content:space-between;gap:8px}
.mf-card h3{font-size:14px;margin:0;font-weight:600;color:var(--ink);font-family:var(--font-serif)}
.mf-badge{font-size:10px;color:var(--ink-faint);background:var(--paper);border:1px solid var(--rule);padding:2px 8px;border-radius:10px;font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.mf-sub{color:var(--ink-soft);font-size:11px;margin:4px 0 12px;font-family:var(--font-mono)}
.mf-row{display:grid;grid-template-columns:140px 1fr 108px;align-items:center;gap:10px;padding:3px 0}
.mf-label{text-align:right;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:flex;align-items:center;justify-content:flex-end;gap:5px;color:var(--ink);font-family:var(--font-serif)}
.mf-track{position:relative;height:18px;background:var(--paper);border-radius:9px;border:1px solid var(--rule)}
.mf-track::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--rule-strong);opacity:.55}
.mf-bar{position:absolute;top:2px;bottom:2px;border-radius:6px}
.mf-bar.pos{background:linear-gradient(90deg,var(--crimson),var(--crimson-bright));left:50%}
.mf-bar.neg{background:linear-gradient(90deg,var(--growth-soft),var(--growth))}
.mf-val{font-family:var(--font-mono);font-size:12px;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.mf-val.pos{color:var(--crimson)}.mf-val.neg{color:var(--growth)}
.mf-yi{font-size:10px;margin-left:1px;opacity:.7}
.mf-pct{font-size:10px;color:var(--ink-faint);margin-left:5px;display:block}
.mf-ctag{font-size:9px;padding:1px 5px;border-radius:3px;background:var(--paper);color:var(--ink-faint);border:1px solid var(--rule);flex-shrink:0;white-space:nowrap;font-family:var(--font-mono)}
.mf-ctag.跨行{color:var(--c-amber);background:var(--gold-soft);border-color:var(--brand)}
.mf-ctag.策略{color:var(--c-violet);background:var(--paper-3);border-color:var(--rule-strong)}
.mf-ctag.行业{color:var(--ink-soft);background:var(--paper-2);border-color:var(--rule)}
.mf-ctag.dim{opacity:.7}
.mf-otable{margin-top:2px}
.mf-ohead,.mf-orow{display:grid;grid-template-columns:90px 1fr 1fr 1fr;gap:14px;align-items:center}
.mf-ohead{font-size:10px;color:var(--ink-faint);border-bottom:1px solid var(--rule);padding:0 0 6px;font-weight:500;font-family:var(--font-mono)}
.mf-orow{padding:6px 0;border-bottom:1px dashed var(--rule)}
.mf-orow:last-child{border-bottom:none}
.mf-oname{font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500;color:var(--ink);font-family:var(--font-serif)}
.mf-otd{display:flex;align-items:center;gap:8px}
.mf-obar{position:relative;flex:1;height:10px;background:var(--paper);border-radius:5px;border:1px solid var(--rule);min-width:36px}
.mf-obar::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--rule-strong);opacity:.5}
.mf-obar .mf-bar{position:absolute;top:1px;bottom:1px;border-radius:3px}
.mf-otd span{font-family:var(--font-mono);font-size:11px;font-variant-numeric:tabular-nums;white-space:nowrap;min-width:40px;text-align:right}
.mf-otd.pos span{color:var(--crimson)}.mf-otd.neg span{color:var(--growth)}
@media(max-width:860px){.mf-grid{grid-template-columns:1fr}.mf-row{grid-template-columns:100px 1fr 92px}.mf-ohead,.mf-orow{grid-template-columns:64px 1fr 1fr 1fr;gap:8px}}
"""


def build(date_str):
    date_compact = date_str.replace("-", "")  # YYYYMMDD，用于问财历史日期查询
    date_cn = f"{int(date_str[:4])}年{int(date_str[5:7])}月{int(date_str[8:10])}日"
    # ---- 拉数据 ----
    ind_in = run_flow("industry-inflow", 50, date_str=date_compact)
    if not ind_in:
        print(f"[moneyflow] {date_str} 非交易日或问财未返回数据，跳过生成。")
        return False

    ind_out = run_flow("industry-outflow", 50, date_str=date_compact)
    con_in = run_flow("concept-inflow", 10, date_str=date_compact)
    con_out = run_flow("concept-outflow", 10, date_str=date_compact)
    orders = run_flow("orders", 10, date_str=date_compact)

    # ---- 行业聚合 ----
    ind_in_cat, ind_out_cat = aggregate_categories(ind_in, ind_out)

    # ---- 冠军股（行业 Top1 + 概念 Top1）----
    top1_ind = ind_in_cat[0]['name'] if ind_in_cat else None
    top1_con = con_in[0]['name'] if con_in else None
    stk_ind = run_flow("stock", 10, sector=top1_ind, date_str=date_compact) if top1_ind else []
    stk_con = run_flow("stock", 10, sector=top1_con, date_str=date_compact) if top1_con else []
    # 概念 stock 措辞回退（策略型概念 flow.py 查不到成分股）
    if top1_con and not stk_con:
        datas = run_market(f"{top1_con}概念股{date_cn}主力资金净流入排名", 20)
        stk_con = []
        for d in datas[:10]:
            amt = next((d[k] for k in d if k.startswith('主力资金流向')), None)
            pct = next((d[k] for k in d if k.startswith('最新涨跌幅')), None)
            ind = next((d[k] for k in d if k.startswith('所属同花顺行业')), None)
            if amt is not None:
                stk_con.append({'name': d.get('股票简称'), 'amount': float(amt),
                                'pct': float(pct) if pct else None, 'industry': ind})
        stk_con.sort(key=lambda x: -(x['amount'] or 0))

    # ---- 渲染 sections ----
    s_ind_in = section(ind_in_cat[:10], '行业大类 · 净流入 Top10',
                       '资金涌入的行业（细分聚合到申万一级，去同链重复）')
    s_ind_out = section(ind_out_cat[:10], '行业大类 · 净流出 Top10', '资金出逃的行业')
    s_con_in = section(con_in, '概念 · 净流入 Top10',
                       '🔥跨行 / 🔒行业子集 / 📊策略集合', is_concept=True)
    s_con_out = section(con_out, '概念 · 净流出 Top10', '同左标注', is_concept=True)
    s_orders = orders_section(orders) if orders else ''
    s_stk_ind = section(stk_ind[:10], f'{top1_ind} · 行业冠军的领涨股',
                        f'大类净流入 Top1「{top1_ind}」主力净流入最多的个股') if stk_ind else ''
    s_stk_con = section(stk_con[:10], f'{top1_con} · 概念冠军的成分股',
                        f'概念净流入 Top1「{top1_con}」主力净流入最多的成分股') if stk_con else ''

    cn_date = f"{date_str[:4]}年{int(date_str[5:7])}月{int(date_str[8:10])}日"
    body = f"""
<div class="mf">
  <h2>今日 A 股资金流向全景</h2>
  <div class="mf-meta">交易日 {cn_date} · 单位：亿元 · <span style="color:#dc2626">■</span> 净流入 / <span style="color:#16a34a">■</span> 净流出（A 股惯例）· 数据来源 {SOURCE}<br>
  行业按申万一级聚合（去同链细分重复）；概念标注 <b>🔥跨行</b>/<b>🔒行业</b>/<b>📊策略</b> 识别与行业的重叠</div>

  <div class="mf-gt">① 行业资金主线 <small>申万一级·去同链细分</small></div>
  <div class="mf-grid">{s_ind_in}{s_ind_out}</div>

  <div class="mf-gt">② 主题透视 <small>概念·标注与行业的重叠类型</small></div>
  <div class="mf-grid">{s_con_in}{s_con_out}</div>
"""
    if s_orders:
        body += f'\n  <div class="mf-gt">③ 资金性质 <small>特大单/大单/小单·主力vs散户</small></div>\n  <div class="mf-grid">{s_orders}</div>\n'
    if s_stk_ind or s_stk_con:
        body += f'\n  <div class="mf-gt">④ 冠军板块领涨股 <small>行业/概念净流入冠军的成分股</small></div>\n  <div class="mf-grid">{s_stk_ind}{s_stk_con}</div>\n'
    body += '\n</div>\n'

    md = f"""---
title: "资金流向 · {cn_date}"
date: "{date_str}"
draft: false
description: "今日 A 股资金流向全景 · 行业/概念/大单/冠军股"
aliases: ["/moneyflow/today/"]
---

<style>
{CSS}
</style>
{body}
"""

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{date_str}.md"
    out.write_text(md, encoding="utf-8")

    # 结构化摘要 → site/data/moneyflow.json，供首页仪表盘读取
    summary = {
        "date": date_str,
        "trade_date": cn_date,
        "inflow_top3": [{"name": r["name"], "amount": round(r["amount"] / 1e8, 1)} for r in ind_in_cat[:3]],
        "outflow_top3": [{"name": r["name"], "amount": round(r["amount"] / 1e8, 1)} for r in ind_out_cat[:3]],
        "industry_top1": top1_ind,
        "concept_top1": top1_con,
    }
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (SITE / "data" / "moneyflow.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # _index.md（列表页）若不存在则建一个
    idx = OUT_DIR / "_index.md"
    if not idx.exists():
        idx.write_text("""---
title: "资金流向"
description: "每日 A 股资金流向全景"
---
本栏目每日 15:30（A 股收盘后）自动更新当日资金流向全景。
""", encoding="utf-8")

    print(f"[moneyflow] ✓ 生成 {out}")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="生成每日资金流向全景页（灯塔 Lighthouse）")
    ap.add_argument("--date", default=_latest_closed_trade_date(),
                    help="日期 YYYYMMDD，默认最近已收盘交易日（北京时区）")
    args = ap.parse_args()
    date_str = datetime.strptime(args.date, "%Y%m%d").strftime("%Y-%m-%d")
    ok = build(date_str)
    sys.exit(0 if ok else 0)  # 非交易日也 exit 0（不算失败，CI 不报红）
