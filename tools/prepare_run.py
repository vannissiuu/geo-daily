#!/usr/bin/env python3
"""每日运行前置脚本：把"今天该采什么窗口、哪些要去重、要不要出周结"一次算清。

用法（仓库根）：python3 tools/prepare_run.py [--date YYYY-MM-DD]
  默认日期 = 北京时间（Asia/Shanghai）的今天。
输出：JSON 打印到 stdout，同时写 /tmp/geo_run_context.json。仅依赖标准库，只读仓库，不改任何数据。

口径依据：rules/02 第 7 节（缺口自适应窗口）、rules/05 第 1–2 节（周结与自愈）、rules/04 5.2（国内占比）。
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = "/tmp/geo_run_context.json"
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DEDUP_DAYS = 45
HIGHLIGHT_FILES = 5
RATIO_DAYS = 30


def beijing_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Shanghai")).date()
    except Exception:
        return datetime.now(timezone(timedelta(hours=8))).date()


def parse_date(s):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s or ""):
        raise ValueError("日期格式应为 YYYY-MM-DD: %r" % (s,))
    return date.fromisoformat(s)


def load_daily():
    """返回 [(date, data)] 按日期升序；坏文件跳过并记入 problems。"""
    items, problems = [], []
    for p in sorted(glob.glob(os.path.join(REPO, "data", "daily", "*.json"))):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.json", os.path.basename(p))
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
            with open(p, encoding="utf-8") as f:
                items.append((d, json.load(f)))
        except Exception as ex:  # noqa: BLE001
            problems.append("%s: %s" % (os.path.basename(p), ex))
    items.sort(key=lambda x: x[0])
    return items, problems


def week_info(start, end):
    name = "%s_%s.json" % (start.isoformat(), end.isoformat())
    rel = "data/weekly/" + name
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "file": rel,
        "exists": os.path.exists(os.path.join(REPO, rel)),
    }


def main():
    ap = argparse.ArgumentParser(description="每日运行前置：窗口 / 去重 / 周结判定")
    ap.add_argument("--date", help="运行日 D（YYYY-MM-DD），默认北京时间今天")
    args = ap.parse_args()
    try:
        D = parse_date(args.date) if args.date else beijing_today()
    except ValueError as ex:
        print(str(ex), file=sys.stderr)
        return 2

    daily, problems = load_daily()
    all_dates = [d for d, _ in daily]
    prior = [d for d in all_dates if d < D]
    L = prior[-1] if prior else None

    # 窗口：默认 [D-5, D]；漏了工作日则 S = min(D-5, L+1)，且不早于 D-7（rules/02 第 7 节）
    S = D - timedelta(days=5)
    if L is not None:
        S = min(S, L + timedelta(days=1))
    S = max(S, D - timedelta(days=7))

    # 去重清单：最近 45 天全部条目
    dedup_from = D - timedelta(days=DEDUP_DAYS)
    dedup = []
    for d, data in daily:
        if d < dedup_from or d > D:
            continue
        for i, e in enumerate(data.get("entries") or [], 1):
            urls = [l.get("url") for l in (e.get("links") or []) if isinstance(l, dict) and l.get("url")]
            dedup.append({
                "id": e.get("id") or "%s-%02d" % (d.isoformat(), i),
                "date": d.isoformat(),
                "category": e.get("category"),
                "title": e.get("title"),
                "urls": urls,
            })

    # 最近 5 个日报文件（早于 D）的精华
    highlights = []
    for d, data in reversed([x for x in daily if x[0] < D][-HIGHLIGHT_FILES:]):
        highlights.append({"date": d.isoformat(), "highlights": data.get("highlights") or []})

    # 近 30 个自然日国内占比
    r_from = D - timedelta(days=RATIO_DAYS - 1)
    total = dom = 0
    for d, data in daily:
        if r_from <= d <= D:
            for e in data.get("entries") or []:
                total += 1
                if e.get("region") == "国内":
                    dom += 1
    ratio30 = round(dom / total, 4) if total else None

    # 周结（仅周一）：due = 上周；heal = 再上一周，缺文件才需补，最多 1 份（rules/05 第 2 节）
    weekly = None
    if D.weekday() == 0:
        due = week_info(D - timedelta(days=7), D - timedelta(days=1))
        heal = week_info(D - timedelta(days=14), D - timedelta(days=8))
        for w in (due, heal):
            w["daily_dates"] = [d.isoformat() for d in all_dates
                                if date.fromisoformat(w["start"]) <= d <= date.fromisoformat(w["end"])]
            w["needed"] = not w["exists"]
        weekly = {
            "due": due,
            "heal": heal,
            "heal_needed": heal["needed"],
            "note": "先补 heal（若 heal_needed），再生成 due；最多补 1 份，更早缺失的周不回溯（rules/05 第 2 节）。",
        }

    ctx = {
        "date": D.isoformat(),
        "weekday": WEEKDAYS[D.weekday()],
        "is_workday": D.weekday() < 5,
        "last_daily_date": L.isoformat() if L else None,
        "window_start": S.isoformat(),
        "window_end": D.isoformat(),
        "already_exists": os.path.exists(os.path.join(REPO, "data", "daily", D.isoformat() + ".json")),
        "dedup": dedup,
        "recent_highlights": highlights,
        "weekly": weekly,
        "domestic_ratio_30d": ratio30,
        "domestic_ratio_30d_basis": {"entries": total, "domestic": dom, "from": r_from.isoformat(), "to": D.isoformat()},
        "problems": problems,
    }

    text = json.dumps(ctx, ensure_ascii=False, indent=2)
    try:
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as ex:
        print("警告：无法写 %s: %s" % (OUT_PATH, ex), file=sys.stderr)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
