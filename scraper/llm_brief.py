# -*- coding: utf-8 -*-
"""
LLM 投资解读生成器（智谱 GLM）
读取当日 analytics → 调 GLM 生成结构化投资简报 → 缓存 JSON。

环境变量（缺失则优雅跳过，不阻断流水线）：
  LLM_API_KEY / ZHIPUAI_API_KEY / ANTHROPIC_AUTH_TOKEN  —— 任一即可
  LLM_BASE_URL  默认 https://open.bigmodel.cn/api/paas/v4/
  LLM_MODEL     默认 glm-4-flash
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DATA_DIR = Path(__file__).parent.parent / "data"
ANALYTICS_DIR = DATA_DIR / "analytics"
BRIEF_DIR = ANALYTICS_DIR / "briefs"

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_MODEL = "glm-4-flash"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_key() -> str:
    for name in ("LLM_API_KEY", "ZHIPUAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ZHIPU_API_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return ""


def _build_prompt(date_str: str, analytics: dict) -> str:
    """把当日经济信号压成紧凑文本喂给模型（不含全文，省 token）。"""
    date_fmt = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:8])}日"
    econ = [a for a in analytics.get("articles", []) if a.get("is_economy")]

    lines = [f"日期：{date_fmt}", f"当日《新闻联播》共 {analytics.get('total_articles',0)} 条，其中经济相关 {len(econ)} 条。", "经济相关新闻要点："]
    for a in econ[:14]:
        title = a.get("title", "").replace("[视频]", "").strip()
        kws = "、".join((a.get("economy_keywords", []) or [])[:6])
        sectors = "、".join((a.get("hit_sectors", []) or [])[:5])
        intensity = a.get("intensity_level", "")
        policy = a.get("policy_level", "")
        nums = "、".join(n.get("value", "") for n in (a.get("key_numbers", []) or [])[:4])
        parts = [f"- 《{title}》"]
        meta = []
        if sectors:
            meta.append(f"板块:{sectors}")
        if kws:
            meta.append(f"关键词:{kws}")
        if intensity:
            meta.append(f"强度:{intensity}")
        if policy:
            meta.append(f"政策:{policy}")
        if nums:
            meta.append(f"数据:{nums}")
        if meta:
            parts.append("（" + "；".join(meta) + "）")
        lines.append("".join(parts))

    # 板块热度
    secs = sorted(analytics.get("daily_sectors", {}).items(), key=lambda x: x[1].get("count", 0), reverse=True)
    if secs:
        lines.append("当日板块热度：" + "、".join(f"{n}({d.get('count',0)})" for n, d in secs[:12]))

    digest = "\n".join(lines)

    schema_hint = json.dumps({
        "sentiment": "积极 / 中性 / 谨慎 三选一",
        "sentiment_reason": "一句话理由",
        "thesis": "120-180字的投资要点综述：概括当日政策与板块信号对A股的整体含义",
        "highlights": [{"sector": "板块名", "angle": "一句投资逻辑", "catalyst": "催化因素", "stocks": "相关龙头股", "watch": "关注点或风险"}],
        "risks": ["1-3条风险提示"],
        "data_read": "对关键经济数据（如有M2/社融/利率/出口等）的解读，无数据则写'本日无重磅宏观数据'"
    }, ensure_ascii=False)

    return f"""你是一位资深A股投资分析师。请基于以下《新闻联播》当日经济信号，站在投资理财角度，产出当日的投资解读。

要求：
- 紧扣A股投资：板块机会、政策催化、资金面、风险规避；具体可操作，不要空话套话，不要风险免责声明。
- 立场客观，区分"明确利好"与"尚需观察"。
- 全部用简体中文。
- 严格输出 JSON，不要 markdown 代码块、不要任何解释文字。

JSON 结构（字段名固定）：
{schema_hint}

{digest}

请输出 JSON："""


def _extract_json(text: str) -> dict:
    """从模型输出里鲁棒地抽取 JSON 对象。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # 取第一个 { 到最后一个 }
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1 or e < s:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(text[s:e + 1])


def _call_llm(prompt: str) -> str:
    """调用 GLM（智谱 OpenAI 兼容接口）。"""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("未安装 openai SDK") from e

    key = _get_key()
    if not key:
        raise RuntimeError("未配置 LLM API key")

    client = OpenAI(
        api_key=key,
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
    )
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是资深A股投资分析师，只输出严格JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        max_tokens=1400,
        timeout=60,
    )
    return resp.choices[0].message.content or ""


def _validate(brief: dict) -> dict:
    """补默认值，保证渲染安全。"""
    brief.setdefault("sentiment", "中性")
    brief.setdefault("sentiment_reason", "")
    brief.setdefault("thesis", "")
    brief.setdefault("highlights", [])
    brief.setdefault("risks", [])
    brief.setdefault("data_read", "")
    brief["highlights"] = brief.get("highlights") or []
    for h in brief["highlights"]:
        if not isinstance(h, dict):
            continue
        h.setdefault("sector", "")
        h.setdefault("angle", "")
        h.setdefault("catalyst", "")
        h.setdefault("stocks", "")
        h.setdefault("watch", "")
    return brief


def generate_brief(date_str: str, force: bool = False) -> dict | None:
    """生成某日投资解读，缓存到 briefs/{date}.json。返回 brief dict 或 None。"""
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEF_DIR / f"{date_str}.json"

    if out_path.exists() and not force:
        return _load_json(out_path)

    if not _get_key():
        print("  ⏭️  未配置 LLM key，跳过投资解读")
        return None

    analytics = _load_json(ANALYTICS_DIR / f"{date_str}.json")
    if not analytics:
        print(f"  ⏭️  无 {date_str} 分析数据，跳过")
        return None

    prompt = _build_prompt(date_str, analytics)
    print(f"  🤖 调用 GLM 生成 {date_str} 投资解读…")

    last_err = None
    for attempt in range(2):
        try:
            raw = _call_llm(prompt)
            brief = _validate(_extract_json(raw))
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({"date": date_str, "model": os.environ.get("LLM_MODEL", DEFAULT_MODEL), "brief": brief},
                          f, ensure_ascii=False, indent=2)
            print(f"  ✅ 投资解读已生成: briefs/{date_str}.json (情绪={brief['sentiment']})")
            return brief
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  ⚠️  第 {attempt + 1} 次生成失败: {str(e)[:120]}")
            if attempt == 0:
                prompt += "\n\n重要：请只输出合法JSON，不要任何额外文字或代码块标记。"

    print(f"  ❌ 投资解读生成失败，跳过: {last_err}")
    return None


def generate_all(date_str: str = None, force: bool = False):
    """为某个日期生成解读（run_daily 调用）。"""
    import datetime as _dt
    if not date_str:
        date_str = _dt.datetime.now().strftime("%Y%m%d")
    print(f"🤖 投资解读生成: {date_str}")
    generate_brief(date_str, force=force)


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    generate_all(d, force="--force" in sys.argv)
