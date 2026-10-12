#!/usr/bin/env python3
"""历史数据迁移：GEO每日动态_数据.md / GEO_周度总结_当前.md -> data/daily、data/weekly

依据 rules/04_输出格式.md 第 8 节、rules/05_周度总结.md 第 6 节。仅用标准库。
用法（仓库根）：python3 tools/migrate_legacy.py [--src DIR]
默认源目录 /mnt/user-data/uploads/GEO行业动态日报/（也可用环境变量 GEO_LEGACY_SRC）。
重复执行是幂等的：先清空 data/daily/*.json、data/weekly/*.json、data/runs/*.json 再重写。
需要人工核对的项目打印在输出末尾，并写入 data/migration_report.json。
"""
import argparse
import json
import os
import re
import sys
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = "/mnt/user-data/uploads/GEO行业动态日报"

CATEGORIES = ["行业政策", "行业方法论", "新技术", "市场动态", "舆情", "平台动态"]
DIMENSIONS = ["信源引用逻辑", "收录周期", "生态绑定", "爬虫可发现性"]
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# ---------------------------------------------------------------- 示意用补齐（2026-10-05 ~ 10-09）
# 仅根据原标题与摘要写，不编造摘要里没有的事实。key = 条目 id，value = (region, insight)；
# title_hint 用于校验 id 没有指向别的条目。
DEMO = {
    "2026-10-05-01": ("海外", "视觉展示广告",
                      "付费可见度延伸到生图输出：方案商应把生图场景纳入监测，并向客户讲清付费位与自然引用的边界。"),
    "2026-10-06-01": ("海外", "OptimizeGEO",
                      "大额融资说明资本看好 GEO 服务层，可作向客户论证预算的行业信号，也提示竞争在加剧。"),
    "2026-10-07-01": ("海外", "Verndale",
                      "传统咨询公司入局，GEO 交付竞争加剧；方案商需突出监测加内容管线重构的一体化交付。"),
    "2026-10-08-01": ("国内", "商品卡",
                      "AI 回答内嵌可点商品卡改写电商可见度规则：方案商应把商品卡露出与 SKU 级监测纳入交付。"),
    "2026-10-09-01": ("海外", "Lily Ray",
                      "自榜清单在 AI Overviews 中引用下降且反向导流：方案商应帮客户评估并下架或改造存量自榜页。"),
    "2026-10-09-02": ("海外", "商品结果",
                      "ChatGPT 商品结果出现导购式标签：电商客户需监测自家商品能否获得“最佳”类标注并优化商品信息。"),
    "2026-10-09-03": ("海外", "MCP Adapter",
                      "WordPress 官方 MCP 适配器让 AI 标准化访问站点：可为 WordPress 客户做机器可访问性评估。"),
}
DEMO_RANGE = ("2026-10-05", "2026-10-09")

# ---------------------------------------------------------------- 平台推断（04 8.2 + 03 3.2 + sources.json）
# 04 8.2 给出的关键词顺序；其后补 03/sources.json 平台清单里的其余平台（低优先级）。
PLATFORM_KEYWORDS = [
    ("ChatGPT", "ChatGPT"), ("OpenAI", "ChatGPT"), ("Claude", "Claude"), ("Gemini", "Google"),
    ("Perplexity", "Perplexity"), ("Google", "Google"), ("豆包", "豆包"), ("DeepSeek", "DeepSeek"),
    ("Kimi", "Kimi"), ("文心", "文心"), ("千问", "千问"), ("元宝", "元宝"),
    ("字节", "豆包"), ("Anthropic", "Claude"), ("谷歌", "Google"), ("通义", "千问"),
    # 以下为 04 8.2 未列出、但属 03 3.1 标准取值 / config platform_aliases 的补充
    ("百度", "文心"), ("AI Overviews", "Google"), ("AI Mode", "Google"),
    ("Copilot", "Copilot"), ("Bing", "Copilot"), ("Meta AI", "Meta AI"), ("Muse", "Meta AI"),
    ("Apple Intelligence", "Apple Intelligence"), ("360", "360"), ("秘塔", "秘塔"), ("抖音", "抖音"),
]
NON_PLATFORM = ["Cloudflare", "xAI"]  # 03 2.1：不算被优化平台


def infer_platforms(title):
    """返回标题命中的归并后平台取值（去重、保持关键词顺序）。"""
    low = title.lower()
    out = []
    for kw, val in PLATFORM_KEYWORDS:
        if kw.lower() in low and val not in out:
            out.append(val)
    return out


# ---------------------------------------------------------------- URL 清洗（04 8.3）
def clean_url(url):
    frag = ""
    if "#" in url:
        url, frag = url.split("#", 1)
        frag = "#" + frag
    if "?" not in url:
        return url + frag
    base, q = url.split("?", 1)
    # 原文有 "?id=xxx?lk_jump_to_browser=true" 的畸形写法：先去掉第二个 "?" 起的该参数
    q = re.sub(r"\?lk_jump_to_browser=[^&#]*", "", q)
    parts = [p for p in q.split("&") if p and p.split("=", 1)[0] != "lk_jump_to_browser"]
    return base + ("?" + "&".join(parts) if parts else "") + frag


def url_key(url):
    """宽松匹配键：去 scheme、www.、末尾 /，保留查询串。"""
    u = clean_url(url).strip()
    u = re.sub(r"^https?://", "", u, flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I)
    return u.rstrip("/").lower()


# ---------------------------------------------------------------- 日报解析（04 8.1）
RE_ENTRY = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s*\|\s*([^\|]+?)\s*\|\s*(.+?)\s*$")
RE_HL = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s*\|\s*精华\s*$")
RE_SUMMARY = re.compile(r"^摘要[：:]\s*(.*)$")
RE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
HL_PREFIX = [
    re.compile(r"^\s*[\[【][^\]】]{1,20}[\]】]\s*"),
    re.compile(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*"),
    re.compile(r"^\s*\d{1,2}\s*[.)）、]\s*"),
    re.compile(r"^\s*[（(][一二三四五六七八九十]{1,3}[）)]\s*"),
]


def strip_hl(text):
    t, changed = text, False
    again = True
    while again:
        again = False
        for rx in HL_PREFIX:
            n = rx.sub("", t, count=1)
            if n != t:
                t, changed, again = n, True, True
    return t.strip(), changed


def parse_daily(path, report):
    lines = open(path, encoding="utf-8").read().splitlines()
    blocks = []  # 按文件出现顺序
    cur = None
    n_headings = 0
    for ln, line in enumerate(lines, 1):
        m = RE_HL.match(line)
        if m:
            cur = {"kind": "hl", "date": m.group(1), "items": [], "line": ln}
            blocks.append(cur)
            continue
        m = RE_ENTRY.match(line)
        if m:
            d, cat, title = m.groups()
            if cat == "无动态":
                cur = {"kind": "none", "date": d, "header": title, "summary": "", "line": ln}
            else:
                n_headings += 1
                cur = {"kind": "entry", "date": d, "category": cat, "title": title,
                       "summary": "", "links": [], "line": ln}
            blocks.append(cur)
            continue
        if line.startswith("###"):
            report["parse_anomalies"].append(f"第 {ln} 行：无法识别的 ### 行：{line[:60]}")
            cur = None
            continue
        if cur is None:
            continue
        if cur["kind"] == "hl":
            if line.startswith("- ") and not line.startswith("- ["):
                cur["items"].append(line[2:].strip())
            continue
        m = RE_SUMMARY.match(line)
        if m:
            cur["summary"] = m.group(1).strip()
            continue
        if cur["kind"] == "entry" and line.startswith("- ["):
            for t, u in RE_LINK.findall(line):
                cur["links"].append({"text": t.strip(), "url": u})
    return blocks, n_headings


def build_days(blocks, report):
    days = {}  # date -> dict(entries=[], highlights=None, none=None)
    for b in blocks:
        d = days.setdefault(b["date"], {"entries": [], "highlights": None, "none": None, "titles": set()})
        if b["kind"] == "entry":
            if b["title"] in d["titles"]:
                report["parse_anomalies"].append(f"{b['date']} 重复 (date,title)，只保留首条：{b['title']}")
                continue
            d["titles"].add(b["title"])
            d["entries"].append(b)
        elif b["kind"] == "hl":
            if d["highlights"] is not None:
                report["parse_anomalies"].append(f"{b['date']} 出现多个精华块，后者追加")
                d["highlights"].extend(b["items"])
            else:
                d["highlights"] = list(b["items"])
        elif b["kind"] == "none":
            d["none"] = b
    return days


def convert_entry(date_s, idx, b, report):
    eid = f"{date_s}-{idx:02d}"
    cat = b["category"]
    title = b["title"]
    platform = ""
    if cat not in CATEGORIES:
        report["illegal_category"].append(f"{eid}：原分类“{cat}”→ 舆情（03 1.2 兜底）  {title}")
        cat = "舆情"
    low = title.lower()
    if "cloudflare" in low and cat == "平台动态":
        report["cloudflare_reclassified"].append(f"{eid}：Cloudflare 条目 平台动态 → 新技术，清空 platform  {title}")
        cat = "新技术"
    elif cat == "平台动态":
        hits = infer_platforms(title)
        if "xai" in low.replace(" ", "") and not hits:
            report["xai"].append(f"{eid}：{title}（保留 category=平台动态，platform 已清空；03 1.4 倾向归新技术，待人工重判）")
        elif "xai" in low.replace(" ", "") and hits:
            report["xai"].append(f"{eid}：标题含 xAI 且含平台词 {hits}  {title}")
            platform = hits[0] if len(hits) == 1 else "多平台"
        elif len(hits) == 1:
            platform = hits[0]
        elif len(hits) > 1:
            platform = "多平台"
            report["platform_multi"].append(f"{eid}：标题含多个平台 {hits} → 多平台  {title}")
        else:
            platform = "多平台"
            report["platform_unknown"].append(f"{eid}：标题推不出平台 → 多平台  {title}")
    links = [{"text": l["text"], "url": clean_url(l["url"])} for l in b["links"]]
    if not links:
        report["parse_anomalies"].append(f"{eid} 无链接")
    if not b["summary"]:
        report["parse_anomalies"].append(f"{eid} 无摘要")
    entry = {
        "id": eid,
        "category": cat,
        "platform": platform,
        "region": None,
        "title": title,
        "summary": b["summary"],
        "insight": None,
        "published": None,
        "links": links,
        "source_type": None,
        "soft_class": None,
        "backfilled": False,
    }
    if eid in DEMO:
        region, hint, insight = DEMO[eid]
        assert hint.lower() in (title + b["summary"]).lower(), f"DEMO 条目 {eid} 与标题不符：{title}"
        assert len(insight) <= 60, f"insight 超 60 字：{eid} {len(insight)}"
        entry.update(region=region, insight=insight, backfilled=True)
    return entry


def domestic_ratio(entries):
    if not entries:
        return 0.0
    if any(e["region"] is None for e in entries):
        return None
    return round(sum(1 for e in entries if e["region"] == "国内") / len(entries), 4)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------- 周结解析（05 第 6 节）
RE_WEEK_H = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s*至\s*(\d{4}-\d{2}-\d{2})\s*周度总结\s*$")
RE_OVERVIEW = re.compile(r"覆盖\s*(\d{4}-\d{2}-\d{2})\s*\\?~\s*(\d{4}-\d{2}-\d{2})\s*[，,]\s*共\s*(\d+)\s*条")
RE_CATLINE = re.compile(r"^-\s*(\S+?)\s*[：:]\s*(\d+)\s*条\s*[（(]\s*(\d+(?:\.\d+)?)\s*%\s*[）)]")
RE_LINKLINE = re.compile(r"^\[(.+)\]\((https?://[^)\s]+)\)\s*$")


def unesc(s):
    return s.replace("\\~", "~")


def parse_weekly(path, report):
    text = open(path, encoding="utf-8").read().splitlines()
    weeks, cur = [], None
    for ln, line in enumerate(text, 1):
        m = RE_WEEK_H.match(line)
        if m:
            cur = {"start": m.group(1), "end": m.group(2), "lines": [], "line": ln}
            weeks.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    out = []
    for w in weeks:
        sec, secs = None, {}
        for line in w["lines"]:
            m = re.match(r"^\*\*(.+?)\*\*(.*)$", line.strip())
            if m:
                name = m.group(1)
                if "概览" in name:
                    sec = "overview"
                elif "趋势" in name:
                    sec = "trends"
                elif "平台" in name:
                    sec = "platform"
                elif "启示" in name:
                    sec = "implications"
                else:
                    report["parse_anomalies"].append(f"周结 {w['start']}：未识别的段标题 {name}")
                    sec = None
                    continue
                secs[sec] = [m.group(0)] if sec == "overview" else []
                continue
            if sec:
                secs[sec].append(line)
        w["secs"] = secs
        out.append(w)
    return out


def parse_overview(w, report):
    lines = w["secs"].get("overview", [])
    head = lines[0] if lines else ""
    m = RE_OVERVIEW.search(head)
    if not m:
        report["parse_anomalies"].append(f"周结 {w['start']}：概览首行无法解析：{head[:60]}")
        total = None
    else:
        total = int(m.group(3))
        if (m.group(1), m.group(2)) != (w["start"], w["end"]):
            report["parse_anomalies"].append(f"周结 {w['start']}：概览覆盖区间 {m.group(1)}~{m.group(2)} 与标题不一致")
    by = {}
    for line in lines[1:]:
        mm = RE_CATLINE.match(line.strip())
        if mm:
            cat = mm.group(1)
            if cat not in CATEGORIES:
                report["parse_anomalies"].append(f"周结 {w['start']}：概览出现未知分类 {cat}")
                continue
            by[cat] = {"count": int(mm.group(2)), "pct": round(float(mm.group(3)) / 100, 4)}
    for c in CATEGORIES:
        if c not in by:
            by[c] = {"count": 0, "pct": 0.0}
            if c != "平台动态":
                report["parse_anomalies"].append(f"周结 {w['start']}：概览缺少分类 {c}，补 0")
    by = {c: by[c] for c in CATEGORIES}
    s = sum(v["count"] for v in by.values())
    if total is not None and s != total:
        report["weekly_overview_mismatch"].append(f"周结 {w['start']}：原文 total={total}，6 类 count 之和={s}（保留原文）")
    return {"total": total, "by_category": by, "note": None}


def parse_items(lines):
    """返回 [(bullet_text, [ (title,url) ... ])] 以及无归属的游离链接。"""
    items, loose, cur = [], [], None
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("- "):
            cur = {"text": unesc(s[2:].strip()), "links": []}
            items.append(cur)
            continue
        m = RE_LINKLINE.match(s)
        if m:
            tgt = cur["links"] if cur is not None else loose
            tgt.append((m.group(1).strip(), m.group(2)))
            continue
        # 续行
        if cur is not None:
            cur["text"] += unesc(s)
    return items, loose


def tokens(s):
    s = s.lower()
    toks = set(re.findall(r"[a-z0-9][a-z0-9.\-]{2,}", s))
    cjk = re.sub(r"[^一-鿿]", " ", s)
    for seg in cjk.split():
        for i in range(len(seg) - 1):
            toks.add(seg[i:i + 2])
    return toks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.environ.get("GEO_LEGACY_SRC", DEFAULT_SRC))
    args = ap.parse_args()
    daily_src = os.path.join(args.src, "GEO每日动态_数据.md")
    weekly_src = os.path.join(args.src, "GEO_周度总结_当前.md")

    report = {k: [] for k in [
        "parse_anomalies", "illegal_category", "cloudflare_reclassified", "xai", "platform_multi",
        "platform_unknown", "highlight_stripped", "url_cleaned_forms", "weekly_overview_mismatch",
        "weekly_unmatched_refs", "weekly_relaxed_match", "weekly_platform_link_assignment",
        "weekly_outside_week_match", "weekly_daily_count_diff", "todo_online_verify"]}

    # ---------- 日报
    blocks, n_headings = parse_daily(daily_src, report)
    days = build_days(blocks, report)

    for sub in ("daily", "weekly", "runs"):
        d = os.path.join(REPO, "data", sub)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            if f.endswith(".json"):
                os.remove(os.path.join(d, f))

    all_dates = sorted(days)
    entry_by_url = {}  # url_key -> [(week-agnostic) (id, date)]
    n_entries = 0
    cat_count = {c: 0 for c in CATEGORIES}
    status_count = {"normal": 0, "few": 0, "none": 0}
    day_objs = {}
    for ds in all_dates:
        d = days[ds]
        entries = [convert_entry(ds, i, b, report) for i, b in enumerate(d["entries"], 1)]
        n_entries += len(entries)
        for e in entries:
            cat_count[e["category"]] += 1
            for l in e["links"]:
                entry_by_url.setdefault(url_key(l["url"]), []).append((e["id"], ds))
        if d["none"] is not None and entries:
            report["parse_anomalies"].append(f"{ds} 既有哨兵又有条目，按有条目处理")
        n = len(entries)
        status = "none" if n == 0 else ("few" if n <= 2 else "normal")
        hl = []
        if d["highlights"]:
            for h in d["highlights"]:
                t, ch = strip_hl(h)
                if ch:
                    report["highlight_stripped"].append(f"{ds}：{h[:30]} → {t[:30]}")
                hl.append(t)
        if n == 0:
            hl = []
        elif d["highlights"] is None:
            hl = []
        if n and len(hl) > min(3, n):
            report["parse_anomalies"].append(f"{ds} 精华 {len(hl)} 条，超过 min(3, 条目数)={min(3, n)}（原样保留）")
        status_count[status] += 1
        day_objs[ds] = {"entries": entries, "status": status, "highlights": hl}

    # run 字段（需要所有日期的 region 才能算 30 日值）
    all_entries = [(ds, e) for ds in all_dates for e in day_objs[ds]["entries"]]
    for ds in all_dates:
        o = day_objs[ds]
        dd = date.fromisoformat(ds)
        lo = (dd - timedelta(days=29)).isoformat()
        window = [e for (d2, e) in all_entries if lo <= d2 <= ds]
        r30 = domestic_ratio(window) if window else None
        obj = {
            "date": ds,
            "status": o["status"],
            "legacy": True,
            "highlights": o["highlights"],
            "entries": o["entries"],
            "run": {
                "candidates": None,
                "selected": len(o["entries"]),
                "domestic_ratio": domestic_ratio(o["entries"]),
                "domestic_ratio_30d": r30,
                "websearch_calls": None,
                "webfetch_calls": None,
            },
        }
        write_json(os.path.join(REPO, "data", "daily", f"{ds}.json"), obj)
        if days[ds]["none"] is not None and not o["entries"]:
            nb = days[ds]["none"]
            note = nb["header"] + ("\n" + nb["summary"] if nb["summary"] else "")
            write_json(os.path.join(REPO, "data", "runs", f"{ds}.json"),
                       {"date": ds, "legacy": True, "notes": note})

    # URL 清洗统计 / 畸形形式
    raw = open(daily_src, encoding="utf-8").read()
    n_raw = raw.count("lk_jump_to_browser")
    left = sum(json.dumps(day_objs[d]["entries"], ensure_ascii=False).count("lk_jump_to_browser") for d in all_dates)
    for m in re.finditer(r"\((https?://[^)\s]*lk_jump_to_browser[^)\s]*)\)", raw):
        u = m.group(1)
        if u.count("?") > 1 or ("?" in u and not u.endswith("?lk_jump_to_browser=true")):
            report["url_cleaned_forms"].append(f"{u}  →  {clean_url(u)}")
    for ds in all_dates:
        for e in day_objs[ds]["entries"]:
            for l in e["links"]:
                u = l["url"]
                if re.search(r"\?&|[?&]$", u) or "lk_jump" in u:
                    report["parse_anomalies"].append(f"{e['id']} 清洗后 URL 异常：{u}")

    # ---------- 周结
    weeks = parse_weekly(weekly_src, report)
    id_title = {e["id"]: e["title"] for d in day_objs.values() for e in d["entries"]}
    n_trend_links = n_trend_matched = n_pc_links = n_pc_matched = 0
    n_trends = n_trends_with_ref = 0

    def match(url, w_start, w_end):
        k = url_key(url)
        cands = entry_by_url.get(k, [])
        relaxed = False
        if not cands:
            return None, False, False
        # 优先本周内
        inw = [c for c in cands if w_start <= c[1] <= w_end]
        if inw:
            return inw[0][0], True, False
        return cands[0][0], True, True

    weekly_objs = []
    for w in weeks:
        s, e = w["start"], w["end"]
        ov = parse_overview(w, report)
        # daily 实际条数对比（仅提示）
        actual = sum(len(day_objs[d]["entries"]) for d in all_dates if s <= d <= e)
        if ov["total"] != actual:
            report["weekly_daily_count_diff"].append(f"周结 {s}~{e}：原文 total={ov['total']}，现日报区间内条目={actual}")
        # 趋势
        items, loose = parse_items(w["secs"].get("trends", []))
        if loose:
            report["parse_anomalies"].append(f"周结 {s} 趋势段有 {len(loose)} 条无归属链接")
        trends = []
        for it in items:
            refs, rl = [], []
            for title, url in it["links"]:
                cu = clean_url(url)
                rl.append({"title": title, "url": cu})
                n_trend_links += 1
                eid, ok, outside = match(cu, s, e)
                if ok:
                    n_trend_matched += 1
                    if outside:
                        report["weekly_outside_week_match"].append(f"周结 {s}：趋势链接匹配到周外条目 {eid}  {title[:30]}")
                    if eid not in refs:
                        refs.append(eid)
                else:
                    report["weekly_unmatched_refs"].append(f"周结 {s} 趋势：[{title[:36]}] {cu}")
            n_trends += 1
            n_trends_with_ref += 1 if refs else 0
            trends.append({"text": it["text"], "refs": refs, "ref_links": rl})
        # 平台逻辑变更
        pcs = []
        if "platform" in w["secs"]:
            items, loose = parse_items(w["secs"]["platform"])
            seen = set()
            for it in items:
                m = re.match(r"^(.+?)\s*[：:]\s*(.*)$", it["text"], re.S)
                dim = m.group(1).strip() if m else ""
                body = m.group(2).strip() if m else it["text"]
                if dim not in DIMENSIONS:
                    report["parse_anomalies"].append(f"周结 {s} 平台变更：未知维度“{dim[:20]}”")
                if dim in seen:
                    report["parse_anomalies"].append(f"周结 {s} 平台变更：维度重复 {dim}")
                seen.add(dim)
                pcs.append({"dimension": dim, "text": body, "refs": [], "ref_links": []})
            # 原文平台变更段的链接统一写在段末，不分维度：按文字相似度归入维度，并列入人工核对
            links = loose + [lk for it in items for lk in it["links"]]
            for title, url in links:
                cu = clean_url(url)
                n_pc_links += 1
                scores = [len(tokens(title) & tokens(p["text"])) for p in pcs]
                if re.search(r"crawler|botbase|robots|爬虫", title, re.I):  # 维度名直接相关的关键词加权
                    scores = [sc + (3 if p["dimension"] == "爬虫可发现性" else 0) for sc, p in zip(scores, pcs)]
                best = max(range(len(pcs)), key=lambda i: scores[i]) if pcs else None
                if best is None:
                    report["parse_anomalies"].append(f"周结 {s} 平台变更：链接无维度可挂 {cu}")
                    continue
                tgt = pcs[best]
                tgt["ref_links"].append({"title": title, "url": cu})
                ordered = sorted(scores, reverse=True)
                confident = ordered[0] >= 2 and (len(ordered) < 2 or ordered[0] > ordered[1])
                report["weekly_platform_link_assignment"].append(
                    f"周结 {s}：[{title[:34]}] → {tgt['dimension']}（得分 {scores}，{'较确定' if confident else '不确定，请核对'}）")
                eid, ok, outside = match(cu, s, e)
                if ok:
                    n_pc_matched += 1
                    if outside:
                        report["weekly_outside_week_match"].append(f"周结 {s}：平台变更链接匹配到周外条目 {eid}")
                    if eid not in tgt["refs"]:
                        tgt["refs"].append(eid)
                else:
                    report["weekly_unmatched_refs"].append(f"周结 {s} 平台变更：[{title[:36]}] {cu}")
        # 隐含期望：2026-07-20 / 07-27 / 08-03 三周无该段
        if "platform" not in w["secs"] and s not in ("2026-07-20", "2026-07-27", "2026-08-03"):
            report["parse_anomalies"].append(f"周结 {s}：缺少平台逻辑变更综述段")
        if "platform" in w["secs"] and s in ("2026-07-20", "2026-07-27", "2026-08-03"):
            report["parse_anomalies"].append(f"周结 {s}：本应无平台变更段却解析到")
        # 启示
        items, loose = parse_items(w["secs"].get("implications", []))
        impl = [it["text"] for it in items]
        if not impl:
            report["parse_anomalies"].append(f"周结 {s}：未解析到启示条目")
        obj = {"week_start": s, "week_end": e, "legacy": True, "overview": ov,
               "trends": trends, "platform_changes": pcs, "implications": impl}
        weekly_objs.append(obj)
        write_json(os.path.join(REPO, "data", "weekly", f"{s}_{e}.json"), obj)

    # ---------- 待办
    for ds in all_dates:
        for e in day_objs[ds]["entries"]:
            if "OptimizeGEO" in e["title"] and "8000" in e["title"]:
                report["todo_online_verify"].append(
                    f"{e['id']}：{e['title']} —— 04 8.5 要求联网核实金额与日期，本次按指示不联网，未修正，待人工/联网任务处理")

    # ---------- 自检与输出
    assert len(weeks) == 9, f"周结期数应为 9，实得 {len(weeks)}"
    assert n_entries == n_headings, f"实体条目数 {n_entries} != 原文条目标题数 {n_headings}（可能有重复被丢弃）"
    assert left == 0, "清洗后仍残留 lk_jump_to_browser"
    assert sum(cat_count.values()) == n_entries

    n_none = status_count["none"]
    print("=" * 60)
    print(f"日期数：{len(all_dates)}（无动态 {n_none}）    实体条目：{n_entries}    周结：{len(weeks)}")
    print(f"  （原文 摘要 行 {sum(1 for l in open(daily_src, encoding='utf-8') if l.startswith('摘要'))} = 条目 {n_entries} + 无动态哨兵 {n_none}）")
    print("各分类：", "  ".join(f"{c} {cat_count[c]}" for c in CATEGORIES))
    print("status：", status_count)
    print(f"精华块：{sum(1 for d in all_dates if days[d]['highlights'])} 个日期有精华；无精华且有条目的日期 "
          f"{sum(1 for d in all_dates if day_objs[d]['entries'] and not day_objs[d]['highlights'])} 个")
    print(f"URL：原文含 lk_jump_to_browser {n_raw} 处，清洗后残留 {left}")
    print(f"周结 refs 匹配：趋势链接 {n_trend_matched}/{n_trend_links}；平台变更链接 {n_pc_matched}/{n_pc_links}；"
          f"合计 {n_trend_matched + n_pc_matched}/{n_trend_links + n_pc_links}；有 refs 的趋势 {n_trends_with_ref}/{n_trends}")
    titles = {
        "parse_anomalies": "解析异常", "illegal_category": "非法分类→舆情", "cloudflare_reclassified": "Cloudflare 改归新技术",
        "xai": "xAI 类（待人工）", "platform_unknown": "platform 推不出→多平台（待人工）",
        "platform_multi": "标题含多个平台→多平台（建议复核）", "highlight_stripped": "精华前缀被剥离",
        "url_cleaned_forms": "特殊形态 URL 清洗", "weekly_overview_mismatch": "周结概览自身不一致（保留原文）",
        "weekly_daily_count_diff": "周结 total 与现日报区间条数不同（保留原文，仅提示）",
        "weekly_unmatched_refs": "周结链接未匹配到日报条目（待人工）",
        "weekly_outside_week_match": "周结链接匹配到周外条目", "weekly_platform_link_assignment": "平台变更段链接按文字相似度归入维度（待核对）",
        "todo_online_verify": "待联网核实",
    }
    for k, t in titles.items():
        v = report[k]
        print(f"\n[{t}] {len(v)}")
        for x in v:
            print("  -", x)
    report["summary"] = {
        "days": len(all_dates), "entries": n_entries, "none_days": n_none, "weeks": len(weeks),
        "by_category": cat_count, "status": status_count,
        "refs_trend": [n_trend_matched, n_trend_links], "refs_platform": [n_pc_matched, n_pc_links],
    }
    write_json(os.path.join(REPO, "data", "migration_report.json"), report)
    print("\n迁移完成。")


if __name__ == "__main__":
    sys.exit(main() or 0)
