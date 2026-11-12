#!/usr/bin/env python3
"""把 data/daily、data/weekly、data/monthly 与 C_CAT / C_SRC 原文打包成 site/data/bundle.json（格式见 site/BUNDLE_SCHEMA.md）。

用法（仓库根）：python3 tools/build_bundle.py
C_CAT / C_SRC 默认读 /mnt/user-data/uploads/GEO行业动态日报/（环境变量 GEO_LEGACY_SRC 可改）；
源文件不存在时回退为沿用已有 site/data/bundle.json 里的 meta.c_cat / meta.c_src，两者都没有则报错。
"""
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("GEO_LEGACY_SRC", "/mnt/user-data/uploads/GEO行业动态日报")
OUT = os.path.join(REPO, "site", "data", "bundle.json")
CATEGORIES = ["行业政策", "行业方法论", "新技术", "市场动态", "舆情", "平台动态"]
PLATFORM_TOPICS = json.load(open(os.path.join(REPO, "config", "sources.json"), encoding="utf-8")).get("platform_topics", [])
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
TAG_RE = re.compile(r"</?callout[^>]*>")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def strip_callout(text):
    return TAG_RE.sub("", text)


def read_fixed_text(name, old_meta, key):
    p = os.path.join(SRC, name)
    if os.path.exists(p):
        raw = strip_callout(open(p, encoding="utf-8").read())
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        return lines if key == "c_cat" else " ".join(lines)
    if old_meta.get(key):
        print(f"WARN: {p} 不存在，沿用旧 bundle 中的 meta.{key}")
        return old_meta[key]
    sys.exit(f"ERROR: 找不到 {name}，且旧 bundle 无 meta.{key}")


def build_entry(e):
    return {
        "id": e["id"],
        "category": e["category"],
        "secondary_category": e.get("secondary_category") or "",
        "platform": e.get("platform") or "",
        "platform_topic": e.get("platform_topic") or "",
        "region": e.get("region"),
        "title": e["title"],
        "summary": e["summary"],
        "insight": e.get("insight"),
        "published": e.get("published"),
        "links": [{"text": l["text"], "url": l["url"]} for l in e["links"]],
        "source_type": e.get("source_type"),
        "soft_class": e.get("soft_class"),
        "backfilled": bool(e.get("backfilled", False)),
    }


def main():
    errors = []
    days = []
    for p in sorted(glob.glob(os.path.join(REPO, "data", "daily", "*.json"))):
        d = load(p)
        name = os.path.basename(p)[:-5]
        if d.get("date") != name:
            errors.append(f"{p}: date 与文件名不一致")
            continue
        wd = WEEKDAYS[date.fromisoformat(d["date"]).weekday()]
        days.append({
            "date": d["date"],
            "weekday": wd,
            "status": d["status"],
            "legacy": bool(d.get("legacy", False)),
            "highlights": list(d.get("highlights", [])),
            "entries": [build_entry(e) for e in d.get("entries", [])],
        })
    days.sort(key=lambda x: x["date"], reverse=True)

    weeks = []
    for p in sorted(glob.glob(os.path.join(REPO, "data", "weekly", "*.json"))):
        w = load(p)
        ov = w["overview"]
        weeks.append({
            "week_start": w["week_start"],
            "week_end": w["week_end"],
            "legacy": bool(w.get("legacy", False)),
            "overview": {
                "total": ov["total"],
                "by_category": {c: {"count": ov["by_category"][c]["count"], "pct": ov["by_category"][c]["pct"]}
                                for c in CATEGORIES},
                "note": ov.get("note"),
            },
            "trends": [{"text": t["text"], "refs": list(t.get("refs", [])),
                        "ref_links": list(t.get("ref_links", []))} for t in w.get("trends", [])],
            "platform_changes": [{"dimension": c["dimension"], "text": c["text"], "refs": list(c.get("refs", [])),
                                  "ref_links": list(c.get("ref_links", []))} for c in w.get("platform_changes", [])],
            "implications": list(w.get("implications", [])),
        })
    weeks.sort(key=lambda x: x["week_start"], reverse=True)

    ent_by_id = {e["id"]: (d["date"], e) for d in days for e in d["entries"]}
    months = []
    for p in sorted(glob.glob(os.path.join(REPO, "data", "monthly", "*.json"))):
        m = load(p)
        regions = {}
        for r in ("国内", "海外"):
            rg = m["regions"][r]
            secs = {}
            for sec in ("insight", "rules"):
                groups = []
                for g in rg[sec]["groups"]:
                    items = []
                    for it in g.get("items", []):
                        ref = it["ref"]
                        if ref not in ent_by_id:
                            errors.append(f"月度情报 {m['month']} 的 ref 指向不存在的条目 {ref}")
                            continue
                        dd, e = ent_by_id[ref]
                        items.append({
                            "ref": ref, "title": it["title"], "body": it["body"],
                            "date": e.get("published") or dd,
                            "category": e["category"], "platform": e.get("platform") or "",
                            "links": [{"text": l["text"], "url": l["url"]} for l in e["links"]],
                        })
                    items.sort(key=lambda x: x["date"], reverse=True)
                    groups.append({"name": g.get("name") or "", "items": items})
                secs[sec] = {"groups": groups}
            regions[r] = {"desc": rg.get("desc", ""), "insight": secs["insight"], "rules": secs["rules"]}
        metrics = []
        for k in m.get("metrics", []):
            dd, e = ent_by_id.get(k["ref"], (None, None))
            metrics.append({"value": k["value"], "unit": k["unit"], "caption": k["caption"], "ref": k["ref"],
                            "url": e["links"][0]["url"] if e and e.get("links") else None})
        months.append({
            "month": m["month"], "period": m["period"], "generated": m.get("generated"),
            "title": m["title"], "lede": m.get("lede", ""), "metrics": metrics, "regions": regions,
            "summary": [{"title": x["title"], "text": x["text"]} for x in m.get("summary", [])],
            "stats": m.get("stats", {}), "note": m.get("note"),
        })
    months.sort(key=lambda x: x["month"], reverse=True)

    # 基本一致性：refs 必须能在 days 里找到
    ids = {e["id"] for d in days for e in d["entries"]}
    for w in weeks:
        for sec in ("trends", "platform_changes"):
            for it in w[sec]:
                for r in it["refs"]:
                    if r not in ids:
                        errors.append(f"周结 {w['week_start']} 的 refs 指向不存在的条目 {r}")
    if errors:
        sys.exit("ERROR:\n  " + "\n  ".join(errors))
    if not days:
        sys.exit("ERROR: data/daily 为空")

    old_meta = {}
    if os.path.exists(OUT):
        try:
            old_meta = load(OUT).get("meta", {})
        except Exception:
            pass

    tz = timezone(timedelta(hours=8))
    bundle = {
        "generated_at": datetime.now(tz).replace(microsecond=0).isoformat(),
        "meta": {
            "title": "GEO 每日行业动态",
            "categories": CATEGORIES,
            "platform_topics": PLATFORM_TOPICS,
            "c_cat": read_fixed_text("C_CAT.md", old_meta, "c_cat"),
            "c_src": read_fixed_text("C_SRC.md", old_meta, "c_src"),
            "stats": {
                "days": len(days),
                "entries": sum(len(d["entries"]) for d in days),
                "weeks": len(weeks),
                "months": len(months),
                "first_date": days[-1]["date"],
                "last_date": days[0]["date"],
            },
        },
        "days": days,
        "weeks": weeks,
        "months": months,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=1)
        f.write("\n")
    s = bundle["meta"]["stats"]
    print(f"bundle.json 已生成：{s['days']} 天 / {s['entries']} 条 / {s['weeks']} 周 / {s['months']} 期月度情报，"
          f"{s['first_date']} ~ {s['last_date']}，{os.path.getsize(OUT) // 1024} KB")


if __name__ == "__main__":
    main()
