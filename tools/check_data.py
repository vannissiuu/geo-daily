#!/usr/bin/env python3
"""对 data/daily、data/weekly 做程序化检查（rules/04 第 6 节 C01–C22、rules/05 第 5 节 W01–W09）。

用法（仓库根）：python3 tools/check_data.py [-v]
  -v  打印全部告警/错误明细（默认每项最多 5 条样例）
legacy 文件按 04 6.3 / 8.4 豁免：豁免项只告警（并计入 C21），不报错。
退出码：有“错误”则 1，否则 0。

legacy 文件里的 null 处理（迁移原型阶段的约定）：
  published 为 null 属 04 8.4 的 C03 豁免；insight / region / source_type / soft_class 为 null 表示
  “尚未补齐”（task 约定只补了 10-05~10-09 示意条目），同样只告警；取值非空但不合法则照常报错。
  C15 在 legacy 文件里只告警（xAI 条目 platform 已清空，等待人工重判）。
"""
import argparse
import unicodedata
import glob
import json
import os
import re
import sys
from collections import defaultdict, OrderedDict
from datetime import date, timedelta
from urllib.parse import urlsplit

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATEGORIES = ["行业政策", "行业方法论", "新技术", "市场动态", "舆情", "平台动态"]
DIMENSIONS = ["信源引用逻辑", "收录周期", "生态绑定", "爬虫可发现性"]
SOURCE_TYPES = ["官方", "中立媒体", "企业发布稿", "一手研究"]
SOFT = ["无", "B", "C"]
CFG = json.load(open(os.path.join(REPO, "config", "sources.json"), encoding="utf-8"))

NUM_PREFIX = re.compile(r"^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d{1,2}\s*[.)）、]|[（(][一二三四五六七八九十]{1,3}[）)]|[一二三四五六七八九十]{1,3}、)")
TAG_PREFIX = re.compile(r"^\s*[\[【]")
MD_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
CAT_PREFIX = re.compile("^\\s*(" + "|".join(CATEGORIES) + ")")


def ljust_w(text, width):
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(0, width - w)


class Results:
    def __init__(self):
        self.order = []
        self.names = {}
        self.c = defaultdict(lambda: {"pass": 0, "warn": 0, "error": 0, "skip": 0})
        self.msgs = defaultdict(list)

    def reg(self, code, name):
        self.order.append(code)
        self.names[code] = name

    def ok(self, code):
        self.c[code]["pass"] += 1

    def skip(self, code):
        self.c[code]["skip"] += 1

    def warn(self, code, msg, legacy=False):
        self.c[code]["warn"] += 1
        self.msgs[code].append(("WARN", msg))
        if legacy and code != "C21":
            self.c["C21"]["warn"] += 1

    def err(self, code, msg):
        self.c[code]["error"] += 1
        self.msgs[code].append(("ERROR", msg))

    def fail(self, code, msg, legacy=False):
        """违规：legacy 文件 → 告警(C21)，否则 → 错误。"""
        if legacy:
            self.warn(code, "[legacy] " + msg, legacy=True)
        else:
            self.err(code, msg)


R = Results()
for code, name in [
    ("C01", "JSON 可解析 / 必填顶层字段 / 文件名=date"), ("C02", "status 与条数一致"),
    ("C03", "条目必填字段非空"), ("C04", "category 合法"), ("C05", "id 格式/日期/唯一/连续"),
    ("C06", "同日标题不重复"), ("C07", "summary ≤150 字"), ("C08", "published 合法且在窗口内"),
    ("C09", "每条 links ≥1"), ("C10", "links 格式 / 无 lk_jump_to_browser"), ("C11", "禁采域名/路径"),
    ("C12", "聚合页作信源"), ("C13", "同一 URL 被多条消息共用"), ("C14", "highlights 规范"),
    ("C15", "平台动态 platform 与标题"), ("C16", "B 类企业发布稿标注"), ("C17", "region/source_type/soft_class 取值"),
    ("C18", "run.selected / domestic_ratio 一致"), ("C19", "国内占比偏低"), ("C20", "条数>6 / 周末 / candidates<selected"),
    ("C21", "legacy 豁免命中（合计，已计入各项告警）"), ("C22", "国内条目链接无国内域名"),
    ("W01", "周结 JSON/字段/周一周日/文件名"), ("W02", "overview 总数与占比"), ("W03", "trends 条数与 refs"),
    ("W04", "platform_changes 维度与 refs"), ("W05", "平台变更 refs 多数为平台动态"), ("W06", "implications 2–4 条"),
    ("W07", "文本无编号/分类前缀"), ("W08", "同周只有一个文件"), ("W09", "区间内缺失工作日"),
    ("G01", "日期唯一且文件名有序"), ("G02", "6 类条数统计无错位"),
]:
    R.reg(code, name)


# ------------------------------------------------------------------ 工具
def valid_date(s):
    try:
        return date.fromisoformat(s) if isinstance(s, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None
    except ValueError:
        return None


def host_path(url):
    u = urlsplit(url)
    return (u.hostname or "").lower(), (u.path or "")


def url_norm(url):
    h, p = host_path(url)
    h = re.sub(r"^www\.", "", h)
    return h + p.rstrip("/").lower()


def host_matches(host, dom):
    return host == dom or host.endswith("." + dom)


BLACK = CFG["blacklist"]
AGG = CFG["aggregators"]
DOM_WL = CFG["whitelist_domestic_domains"]
PLATFORM_VALUES = CFG["platform_values"]
ALIASES = CFG["platform_aliases"]


def blacklisted(url):
    h, p = host_path(url)
    hp = h + p
    for b in BLACK:
        if "/" in b:
            if b in hp or b in re.sub(r"^www\.", "", hp):
                return b
        elif host_matches(h, b):
            return b
    return None


def aggregator(url):
    h, p = host_path(url)
    hp = re.sub(r"^www\.", "", h + p)
    for a in AGG:
        if a in hp:
            return a
    return None


def is_domestic(url):
    h, p = host_path(url)
    if h == "new.qq.com" and p.startswith("/rain/a/"):
        return False
    return h.endswith(".cn") or any(host_matches(h, d) for d in DOM_WL)


def platform_names():
    return [p for p in PLATFORM_VALUES if p != "多平台"] + list(ALIASES.keys())


def title_has_platform(title, platform):
    low = title.lower()
    if platform == "多平台":
        return any(n.lower() in low for n in platform_names())
    names = [platform] + [a for a, v in ALIASES.items() if v == platform]
    return any(n.lower() in low for n in names)


def empty(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


# ------------------------------------------------------------------ 日报
def check_daily(files):
    days = OrderedDict()
    for p in files:
        name = os.path.basename(p)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as ex:
            R.err("C01", f"{name}: JSON 无法解析 {ex}")
            continue
        miss = [k for k in ("date", "status", "highlights", "entries", "run") if k not in d]
        if miss:
            R.err("C01", f"{name}: 缺少顶层字段 {miss}")
            continue
        if d["date"] != name[:-5] or not valid_date(d["date"]):
            R.err("C01", f"{name}: date={d['date']} 与文件名不一致或非法")
            continue
        if not isinstance(d["entries"], list) or not isinstance(d["highlights"], list) or not isinstance(d["run"], dict):
            R.err("C01", f"{name}: entries/highlights/run 类型错误")
            continue
        R.ok("C01")
        days[d["date"]] = d

    # G01
    dates = list(days)
    if dates == sorted(dates) and len(set(dates)) == len(dates):
        R.ok("G01")
    else:
        R.err("G01", "data/daily 文件名日期重复或无序")

    url_users = defaultdict(set)   # url_norm -> {(entry id, legacy)}
    cat_total = defaultdict(int)

    for ds, d in days.items():
        leg = bool(d.get("legacy"))
        entries = d["entries"]
        n = len(entries)
        dt = date.fromisoformat(ds)

        # C02
        st = d["status"]
        exp_ok = (st == "none" and n == 0) or (st == "few" and 1 <= n <= 2) or (st == "normal" and n >= 3)
        if st not in ("none", "few", "normal"):
            R.err("C02", f"{ds}: status={st} 非法")
        elif not exp_ok:
            R.err("C02", f"{ds}: status={st} 与条数 {n} 不符")
        else:
            R.ok("C02")

        # C14 highlights
        hl = d["highlights"]
        probs = []
        if n == 0:
            if hl:
                probs.append("none 日 highlights 应为空")
        else:
            if not (1 <= len(hl) <= 3 and len(hl) <= n):
                probs.append(f"highlights {len(hl)} 条，应 1–3 且 ≤ 条目数 {n}")
        for h in hl:
            if not isinstance(h, str) or not h.strip():
                probs.append("highlights 含空项")
            elif NUM_PREFIX.match(h) or TAG_PREFIX.match(h):
                probs.append(f"精华以编号/标签开头：{h[:20]}")
            elif MD_LINK.search(h):
                probs.append(f"精华含 Markdown 链接：{h[:20]}")
        if probs:
            for pr in probs:
                R.fail("C14", f"{ds}: {pr}", leg)
        else:
            R.ok("C14")

        # C18 / C19 / C20 (日级)
        run = d["run"]
        rp = []
        if run.get("selected") != n:
            rp.append(f"run.selected={run.get('selected')} != {n}")
        regs = [e.get("region") for e in entries]
        dr = run.get("domestic_ratio")
        if dr is not None and n and all(r in ("国内", "海外") for r in regs):
            calc = sum(1 for r in regs if r == "国内") / n
            if abs(calc - dr) > 0.01:
                rp.append(f"domestic_ratio={dr} 与重算 {calc:.3f} 不符")
        if n == 0 and dr not in (0, 0.0, None):
            rp.append("none 日 domestic_ratio 应为 0")
        if rp:
            for x in rp:
                R.err("C18", f"{ds}: {x}")
        else:
            R.ok("C18")
        for key in ("domestic_ratio", "domestic_ratio_30d"):
            v = run.get(key)
            if v is None or (key == "domestic_ratio" and n == 0):
                R.skip("C19")
            elif v < 0.4:
                R.warn("C19", f"{ds}: ALERT·国内占比偏低 {key}={v}")
            else:
                R.ok("C19")
        c20 = []
        if n > 6:
            c20.append(f"当日条数 {n} > 6")
        if dt.weekday() >= 5:
            c20.append("date 为周末")
        cand = run.get("candidates")
        if cand is not None and cand < run.get("selected", 0):
            c20.append("candidates < selected")
        if c20:
            for x in c20:
                R.warn("C20", f"{ds}: {x}")
        else:
            R.ok("C20")

        # 条目级
        seen_titles = set()
        ids = []
        for i, e in enumerate(entries, 1):
            eid = e.get("id", f"{ds}#{i}")
            tag = f"{eid}"
            cat = e.get("category")
            if cat in CATEGORIES:
                cat_total[cat] += 1

            # C03
            req = ["id", "category", "region", "title", "summary", "insight", "published", "links", "source_type", "soft_class"]
            if cat == "平台动态":
                req.append("platform")
            hard, soft = [], []
            for k in req:
                if empty(e.get(k)):
                    if leg and k in ("published", "insight", "region", "source_type", "soft_class"):
                        soft.append(k)
                    elif leg and k == "platform":
                        soft.append(k)  # 同 C15：xAI 待人工重判
                    else:
                        hard.append(k)
            if hard:
                R.err("C03", f"{tag}: 必填字段为空 {hard}")
            elif soft:
                R.warn("C03", f"[legacy] {tag}: 历史待补齐 {soft}", legacy=True)
            else:
                R.ok("C03")

            # C04
            if cat in CATEGORIES:
                R.ok("C04")
            else:
                R.err("C04", f"{tag}: category={cat!r} 非法")

            # C05 (逐日一次性在循环外汇总)
            ids.append(eid)

            # C06
            t = e.get("title", "")
            if t in seen_titles:
                R.err("C06", f"{tag}: 同日标题重复 {t[:30]}")
            else:
                R.ok("C06")
            seen_titles.add(t)

            # C07
            sm = e.get("summary", "")
            if not isinstance(sm, str) or len(sm) > 150:
                R.err("C07", f"{tag}: summary 长度 {len(sm) if isinstance(sm, str) else '?'} > 150")
            else:
                R.ok("C07")

            # C08
            pub = e.get("published")
            if pub is None:
                if leg:
                    R.skip("C08")
                else:
                    R.err("C08", f"{tag}: published 为空")
            else:
                pd = valid_date(pub)
                if not pd:
                    R.fail("C08", f"{tag}: published={pub!r} 非法", leg)
                elif not (dt - timedelta(days=7) <= pd <= dt):
                    R.fail("C08", f"{tag}: published={pub} 不在 [date-7, date]", leg)
                else:
                    R.ok("C08")

            # C09 / C10
            links = e.get("links")
            if not isinstance(links, list) or not links:
                R.err("C09", f"{tag}: links 为空")
                links = []
            else:
                R.ok("C09")
            bad10 = []
            for l in links:
                u = l.get("url", "") if isinstance(l, dict) else ""
                if not (isinstance(u, str) and re.match(r"https?://", u)):
                    bad10.append(f"url 非 http(s)：{str(u)[:40]}")
                elif "lk_jump_to_browser" in u or re.search(r"\?&|[?&]$", u):
                    bad10.append(f"url 含被清洗参数或残留 ?/&：{u[:60]}")
                if not (isinstance(l, dict) and str(l.get("text", "")).strip()):
                    bad10.append("link.text 为空")
            if bad10:
                for x in bad10:
                    R.err("C10", f"{tag}: {x}")
            elif links:
                R.ok("C10")

            # C11 / C12 / C22
            h11 = [(l["url"], blacklisted(l["url"])) for l in links if isinstance(l, dict) and blacklisted(l.get("url", ""))]
            if h11:
                for u, b in h11:
                    R.fail("C11", f"{tag}: 命中禁采 {b}  {u[:70]}", leg)
            else:
                R.ok("C11")
            h12 = [(l["url"], aggregator(l["url"])) for l in links if isinstance(l, dict) and aggregator(l.get("url", ""))]
            if h12:
                for u, b in h12:
                    R.fail("C12", f"{tag}: 命中聚合页 {b}  {u[:70]}", leg)
            else:
                R.ok("C12")
            if e.get("region") == "国内" and links:
                if any(is_domestic(l["url"]) for l in links if isinstance(l, dict) and l.get("url")):
                    R.ok("C22")
                else:
                    R.warn("C22", f"{tag}: region=国内但链接无国内域名")
            else:
                R.skip("C22")

            for l in links:
                if isinstance(l, dict) and l.get("url"):
                    url_users[url_norm(l["url"])].add((eid, leg))

            # C15
            if cat == "平台动态":
                pf = e.get("platform")
                if not pf or pf not in PLATFORM_VALUES:
                    R.fail("C15", f"{tag}: platform={pf!r} 为空或不在标准取值", leg)
                elif not title_has_platform(t, pf):
                    R.fail("C15", f"{tag}: 标题不含平台 {pf} 或其别名", leg)
                else:
                    R.ok("C15")
            else:
                R.skip("C15")

            # C16
            if e.get("soft_class") == "B" and e.get("source_type") == "企业发布稿":
                if "（信源为企业发布稿）" in t or "（信源为企业发布稿）" in sm:
                    R.ok("C16")
                else:
                    R.fail("C16", f"{tag}: B 类企业发布稿缺“（信源为企业发布稿）”", leg)
            else:
                R.skip("C16")

            # C17
            bad17, null17 = [], []
            for k, allowed in (("region", ["国内", "海外"]), ("source_type", SOURCE_TYPES), ("soft_class", SOFT)):
                v = e.get(k)
                if v is None:
                    null17.append(k)
                elif v not in allowed:
                    bad17.append(f"{k}={v!r}")
            if bad17:
                R.err("C17", f"{tag}: 取值非法 {bad17}")
            elif null17 and not leg:
                R.err("C17", f"{tag}: {null17} 为空")
            elif null17:
                R.skip("C17")  # legacy 空值已在 C03 告警
            else:
                R.ok("C17")

        # C05（按日）
        bad5 = []
        for i, eid in enumerate(ids, 1):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{2}", str(eid)) or str(eid)[:10] != ds:
                bad5.append(f"{eid} 格式或日期部分错误")
            elif int(str(eid)[-2:]) != i:
                bad5.append(f"{eid} 序号应为 {i:02d}")
        if len(set(ids)) != len(ids):
            bad5.append("id 重复")
        if bad5:
            for x in bad5:
                R.err("C05", f"{ds}: {x}")
        else:
            R.ok("C05")

    # C13 / 全局
    for u, users in url_users.items():
        eids = {x[0] for x in users}
        if len(eids) < 2:
            R.ok("C13")
            continue
        all_leg = all(x[1] for x in users)
        R.fail("C13", f"URL 被 {len(eids)} 条共用：{u[:70]} ← {sorted(eids)}", all_leg)

    # G02
    src_cats = defaultdict(int)
    for d in days.values():
        for e in d["entries"]:
            src_cats[e.get("category")] += 1
    mism = [c for c in CATEGORIES if src_cats.get(c, 0) != cat_total.get(c, 0)]
    (R.err("G02", f"分类统计错位：{mism}") if mism else R.ok("G02"))
    return days, cat_total


# ------------------------------------------------------------------ 周结
def check_weekly(files, days):
    weeks = OrderedDict()
    ranges = []
    for p in files:
        name = os.path.basename(p)
        try:
            w = json.load(open(p, encoding="utf-8"))
        except Exception as ex:
            R.err("W01", f"{name}: JSON 无法解析 {ex}")
            continue
        miss = [k for k in ("week_start", "week_end", "overview", "trends", "platform_changes", "implications") if k not in w]
        if miss:
            R.err("W01", f"{name}: 缺字段 {miss}")
            continue
        s, e = valid_date(w["week_start"]), valid_date(w["week_end"])
        if not s or not e or s.weekday() != 0 or e != s + timedelta(days=6):
            R.err("W01", f"{name}: week_start 须为周一且 week_end=+6 天")
            continue
        if name != f"{w['week_start']}_{w['week_end']}.json":
            R.err("W01", f"{name}: 文件名与区间不一致")
            continue
        R.ok("W01")
        weeks[name] = w
        ranges.append((s, e, name))

    # W08
    ranges.sort()
    ok8 = True
    for a, b in zip(ranges, ranges[1:]):
        if b[0] <= a[1]:
            R.err("W08", f"{a[2]} 与 {b[2]} 区间重叠")
            ok8 = False
    if ok8:
        for _ in ranges:
            R.ok("W08")

    for name, w in weeks.items():
        leg = bool(w.get("legacy"))
        s, e = date.fromisoformat(w["week_start"]), date.fromisoformat(w["week_end"])
        wk = w["week_start"]
        in_week = {en["id"]: en for ds, d in days.items() if s <= date.fromisoformat(ds) <= e for en in d["entries"]}
        actual_total = len(in_week)
        ov = w["overview"]
        bc = ov.get("by_category", {})

        # W02
        if sorted(bc.keys()) != sorted(CATEGORIES):
            R.err("W02", f"{wk}: by_category 须列全 6 类")
        else:
            probs = []
            cnt_sum = sum(bc[c]["count"] for c in CATEGORIES)
            if cnt_sum != ov.get("total"):
                probs.append(f"6 类 count 之和 {cnt_sum} != total {ov.get('total')}")
            if ov.get("total") != actual_total:
                probs.append(f"total={ov.get('total')} 与日报区间条数 {actual_total} 不同")
            for c in CATEGORIES:
                t = ov.get("total") or 0
                exp = bc[c]["count"] / t if t else 0
                if abs(exp - bc[c]["pct"]) > 0.01:
                    probs.append(f"{c} pct={bc[c]['pct']} 与 count/total={exp:.3f} 不符")
            if probs:
                for x in probs:
                    R.fail("W02", f"{wk}: {x}", leg)
            else:
                R.ok("W02")

        # W03
        probs = []
        tr = w["trends"]
        if ov.get("total") != 0 and not (3 <= len(tr) <= 5):
            probs.append(f"trends {len(tr)} 条，应 3–5")
        for t in tr:
            if empty(t.get("text")):
                probs.append("trend.text 为空")
            refs = t.get("refs", [])
            if not (1 <= len(refs) <= 3):
                probs.append(f"趋势 refs {len(refs)} 个，应 1–3：{t.get('text', '')[:16]}")
            for r in refs:
                if r not in in_week:
                    probs.append(f"趋势 ref {r} 不在该周日报条目中")
        if probs:
            for x in probs:
                R.fail("W03", f"{wk}: {x}", leg)
        else:
            R.ok("W03")

        # W04 / W05
        pcs = w["platform_changes"]
        has_plat = any(en["category"] == "平台动态" for en in in_week.values())
        probs = []
        dims = [c.get("dimension") for c in pcs]
        if any(d not in DIMENSIONS for d in dims):
            probs.append(f"维度非法 {dims}")
        if len(set(dims)) != len(dims):
            probs.append("维度重复")
        for c in pcs:
            refs = c.get("refs", [])
            if len(refs) > 2:
                probs.append(f"{c.get('dimension')} refs {len(refs)} 个，应 ≤2")
            for r in refs:
                if r not in in_week:
                    probs.append(f"{c.get('dimension')} ref {r} 不在该周内")
        if has_plat:
            if sorted(dims) != sorted(DIMENSIONS):
                probs.append("该周有平台动态条目，4 个维度应齐全")
        elif pcs:
            probs.append("该周无平台动态条目，platform_changes 应为空")
        if probs:
            for x in probs:
                R.fail("W04", f"{wk}: {x}", leg)
        else:
            R.ok("W04")
        refs_all = [r for c in pcs for r in c.get("refs", []) if r in in_week]
        if refs_all:
            plat = sum(1 for r in refs_all if in_week[r]["category"] == "平台动态")
            if plat * 2 >= len(refs_all):
                R.ok("W05")
            else:
                R.warn("W05", f"{wk}: platform_changes.refs 中平台动态仅 {plat}/{len(refs_all)}")
        else:
            R.skip("W05")

        # W06
        imp = w["implications"]
        if ov.get("total") == 0 and not imp:
            R.ok("W06")
        elif 2 <= len(imp) <= 4 and all(isinstance(x, str) and x.strip() for x in imp):
            R.ok("W06")
        else:
            R.fail("W06", f"{wk}: implications {len(imp)} 条，应 2–4 条非空字符串", leg)

        # W07
        probs = []
        for t in tr:
            tx = t.get("text", "")
            if NUM_PREFIX.match(tx):
                probs.append(f"趋势以编号开头：{tx[:16]}")
            if CAT_PREFIX.match(tx):
                probs.append(f"趋势带分类前缀：{tx[:16]}")
        for tx in imp:
            if isinstance(tx, str) and NUM_PREFIX.match(tx):
                probs.append(f"启示以编号开头：{tx[:16]}")
        if probs:
            for x in probs:
                R.fail("W07", f"{wk}: {x}", leg)
        else:
            R.ok("W07")

        # W09
        missing = []
        d0 = s
        while d0 <= e:
            if d0.weekday() < 5 and d0.isoformat() not in days:
                missing.append(d0.isoformat())
            d0 += timedelta(days=1)
        if missing:
            R.warn("W09", f"{wk}: 缺少工作日日报 {missing}")
        else:
            R.ok("W09")
    return weeks


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    dfiles = sorted(glob.glob(os.path.join(REPO, "data", "daily", "*.json")))
    wfiles = sorted(glob.glob(os.path.join(REPO, "data", "weekly", "*.json")))
    if not dfiles:
        print("ERROR: data/daily 为空")
        return 1
    days, cat_total = check_daily(dfiles)
    check_weekly(wfiles, days)

    print(f"检查对象：日报 {len(dfiles)} 个文件（{sum(len(d['entries']) for d in days.values())} 条），周结 {len(wfiles)} 个文件")
    print("6 类条数：" + "  ".join(f"{c} {cat_total.get(c, 0)}" for c in CATEGORIES))
    print()
    print(ljust_w("编号", 6) + ljust_w("检查项", 44) + "通过".rjust(6) + "告警".rjust(6) + "错误".rjust(6) + "跳过".rjust(6))
    tot = {"pass": 0, "warn": 0, "error": 0}
    for code in R.order:
        c = R.c[code]
        if code == "C21":
            print(ljust_w(code, 6) + ljust_w(R.names[code], 44) + "-".rjust(8) + str(c["warn"]).rjust(6))
            continue
        print(ljust_w(code, 6) + ljust_w(R.names[code], 44) + f"{c['pass']:>8}{c['warn']:>6}{c['error']:>6}{c['skip']:>6}")
        for k in tot:
            tot[k] += c[k]
    print(f"\n合计：通过 {tot['pass']}，告警 {tot['warn']}，错误 {tot['error']}")

    limit = None if args.verbose else 5
    for code in R.order:
        ms = R.msgs.get(code, [])
        if not ms:
            continue
        print(f"\n[{code}] {R.names[code]}  ({len(ms)} 条)")
        for lvl, m in (ms if limit is None else ms[:limit]):
            print(f"  {lvl}: {m}")
        if limit is not None and len(ms) > limit:
            print(f"  … 另有 {len(ms) - limit} 条，用 -v 查看全部")
    errs = tot["error"]
    print("\n结果：" + ("存在错误，检查未通过" if errs else "无错误（legacy 告警允许）"))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
