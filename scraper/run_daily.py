# -*- coding: utf-8 -*-
"""
每日流水线入口
抓取 → 关键词提取 → 信号分析 → Hugo 内容生成
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 确保可以 import 同目录模块
sys.path.insert(0, str(Path(__file__).parent))

from fetch_xwlb import fetch_daily
from extract_keywords import analyze_daily, analyze_multi_period
from signal_tracker import run_signal_analysis
from llm_brief import generate_brief
from build_content import build_all


def latest_broadcast_date() -> str:
    """最近一期已播出的《新闻联播》日期（北京时区，YYYYMMDD）。

    联播约 19:00 播出。GitHub 定时任务常被延迟数小时，一旦跨过北京 0 点，
    「今天」的联播尚未播出——此时必须回退到「昨天」，否则会去抓未来日期
    的页面（404）从而被误判为「无数据」。北京时间 19:00 前一律取昨天。
    """
    now_bj = datetime.now(timezone(timedelta(hours=8)))
    if now_bj.hour < 19:
        now_bj -= timedelta(days=1)
    return now_bj.strftime('%Y%m%d')


def run_pipeline(date_str: str = None):
    """运行完整流水线"""
    if not date_str:
        date_str = latest_broadcast_date()

    print(f'{"="*50}')
    print(f'🚀 每日流水线启动: {date_str}')
    print(f'{"="*50}\n')

    # Step 1: 抓取
    print('📥 Step 1: 抓取新闻')
    print('-' * 30)
    daily_data = fetch_daily(date_str)
    if not daily_data.get('articles'):
        print('❌ 无新闻数据，流水线终止（exit 1，让 CI 真报红而非伪 success）')
        sys.exit(1)
    print()

    # Step 2: 关键词提取
    print('🏷️ Step 2: 关键词提取 + 分析')
    print('-' * 30)
    analyze_daily(date_str)
    print()

    # Step 3: 多周期统计
    print('📊 Step 3: 多周期统计')
    print('-' * 30)
    analyze_multi_period(date_str)
    print()

    # Step 4: 信号分析
    print('🔍 Step 4: 信号追踪 + 异动预警')
    print('-' * 30)
    run_signal_analysis(date_str)
    print()

    # Step 5: AI 投资解读（智谱 GLM；无 key 自动跳过）
    print('🤖 Step 5: AI 投资解读')
    print('-' * 30)
    generate_brief(date_str)
    print()

    # Step 6: 生成 Hugo 内容
    print('📝 Step 6: 生成 Hugo 内容')
    print('-' * 30)
    build_all(date_str)
    print()

    print(f'{"="*50}')
    print(f'✅ 流水线完成: {date_str}')
    print(f'{"="*50}')


if __name__ == '__main__':
    date_str = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.startswith('--date='):
            date_str = arg.split('=')[1]
        elif arg == '--today':
            date_str = latest_broadcast_date()

    run_pipeline(date_str)
