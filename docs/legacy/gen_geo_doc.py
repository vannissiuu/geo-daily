#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GEO 每日动态 — 飞书回溯文档确定性生成器（格式锁定版）
=====================================================
设计铁律：
  1. 只从单一数据源 GEO每日动态_数据.md 全量重渲染，绝不解析/合并线上文档。
  2. Part1 每日动态 / Part2 分类索引 / Part3 周度总结 三个视图【各仅出现一次】。
  3. 三处阅读指引 callout（C_READ / C_CAT / C_WEEK）为固定模板，逐字硬编码，不解析、不漂移。
  4. Part3 周度总结正文来自 GEO_周度总结_当前.md（周一运行由数据重算后回写此文件）。

运行：python gen_geo_doc.py  -> 生成 _geo_doc_full.md
"""
import re
import os

WS = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(WS, "GEO每日动态_数据.md")
WEEKLY = os.path.join(WS, "GEO_周度总结_当前.md")
OUT = os.path.join(WS, "_geo_doc_full.md")

# 固定分类顺序（不可改）
CATS = ["行业政策", "行业方法论", "新技术", "市场动态", "舆情", "平台动态"]

# 无动态哨兵分类（2026-08-26 用户确立）：
# 无新增净动态的工作日，也须在数据源写一条「### 当天 | 无动态 | 本日无新增...」，
# 让云文档在该日期下渲染「本日无新增」标记、文档最大日期推进到当天（标题改名到当天），
# 从而区分「已执行但无动态」与「漏跑」。哨兵不进 Part2 分类索引、不计入 6 分类覆盖断言。
SENTINEL_CAT = "无动态"

# ===== 固定模板：三处 callout（逐字锁定，禁止改写）=====
C_READ = '''<callout emoji="💡">
阅读指引：  
Part1：每日动态，每日上午10点自动搜索采集更新，可优先查看今日精华，直接快速获得当日重点；  
Part2：分类索引，按消息类型进行分类，可在左侧目录点击分类标题直达，方便快速找到关注领域。  
Part3：周度总结，于每周一自动生成，汇总上周（上周一至上周日） GEO 行业动态，用于趋势研判 和 提炼对解决方案卖进的启示。
</callout>'''

# C_CAT 分类说明：以独立文件 C_CAT.md 为唯一来源（冻结版），脚本绝不回退默认文案。
# 用户手动精简后的版本写入 C_CAT.md 后即永久锁定；如需调整请直接编辑该文件。
C_CAT_FILE = os.path.join(WS, "C_CAT.md")
C_CAT_DEFAULT = '''<callout emoji="💡">
分类说明：
- 行业政策：监管 / 标准 / 治理 / 权威倡议与执法
- 行业方法论：可复用框架 / 评估度量 / 优化打法 / 研究基准
- 新技术：新能力 / 新架构 / 新基础设施 / 技术范式转移
- 市场动态：融资 / 并购 / 合作 / 上市 / 新玩家入场 / 规模 / 榜单 / 出海 / 渠道。
- 舆情：风险 / 争议 / 信任危机 / 黑产 / 消费者警示 / 红黑榜 / 声誉事件
- 平台动态：被优化对象（豆包 / DeepSeek / Kimi / 千问 / 文心 / 元宝 / Google / ChatGPT / Perplexity / Claude 等大模型平台）自身的算法、信源、引用、收录、爬虫、商业化策略变更。注：主语是「做 GEO 的工具 / 服务商」（如 Pepper、Cloudflare 的 AEO 看板）归「新技术」，不在此类。
</callout>'''

def load_c_cat():
    if os.path.exists(C_CAT_FILE):
        t = open(C_CAT_FILE, encoding="utf-8").read().strip()
        if t:
            # 防御：剥离文件内任何 HTML 注释（如人工写入的 <!-- ... --> 备注），
            # 避免注释作为裸文本泄漏到飞书文档 Part2 区域（2026-08-19 事故根因）。
            t = re.sub(r'<!--.*?-->', '', t, flags=re.S).strip()
            return t
    return C_CAT_DEFAULT

C_CAT = load_c_cat()

# C_SRC 信源筛选原则：以独立文件 C_SRC.md 为唯一来源（冻结版，2026-08-21 用户确立）。
# 固定渲染在文档最顶部（H1 之后、C_READ 阅读指引之前），让读者首先看到信源筛选原则，
# 增强对文档信息的置信度。如需调整请直接编辑 C_SRC.md 后重跑同步。
C_SRC_FILE = os.path.join(WS, "C_SRC.md")
C_SRC_DEFAULT = '''<callout emoji="🛡️">
本文档信源筛选原则：真实可溯可访问 + 优先权威/中立媒体 + 非软文 + 时效5天以内
</callout>'''

def load_c_src():
    if os.path.exists(C_SRC_FILE):
        t = open(C_SRC_FILE, encoding="utf-8").read().strip()
        if t:
            # 防御：剥离文件内任何 HTML 注释，避免裸文本泄漏到飞书文档顶部
            t = re.sub(r'<!--.*?-->', '', t, flags=re.S).strip()
            return t
    return C_SRC_DEFAULT

C_SRC = load_c_src()

C_WEEK = '''<callout emoji="💡">
于每周一自动生成，汇总上周（上周一至上周日） GEO 行业动态，用于趋势研判 和 提炼对解决方案卖进的启示。
</callout>'''


def parse_data(text):
    """解析数据源：每条 ### DATE | CAT | TITLE + 摘要 + - [text](url) 链接；
    以及可选的 ### DATE | 精华 块（每日精华，由运行时 AI 归纳写入）。"""
    entries = []
    highlights = {}          # date -> [bullet, ...]
    cur = None
    cur_hl_date = None       # 当前是否处于某日的「精华」块内
    for line in text.splitlines():
        m = re.match(r'^###\s+(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$', line)
        if m:
            if cur:
                entries.append(cur)
            cur = {"date": m.group(1), "cat": m.group(2).strip(),
                   "title": m.group(3).strip(), "summary": "", "links": []}
            cur_hl_date = None
            continue
        # 每日精华块：### DATE | 精华
        mh = re.match(r'^###\s+(\d{4}-\d{2}-\d{2})\s*\|\s*精华\s*$', line)
        if mh:
            if cur:
                entries.append(cur)
            cur_hl_date = mh.group(1)
            highlights.setdefault(cur_hl_date, [])
            cur = None
            continue
        if cur_hl_date is not None:
            s = line.strip()
            # 精华块内的分点：纯文本（不含 [text](url) 链接行）
            if s.startswith("- ") and not s.startswith("- ["):
                highlights[cur_hl_date].append(s[2:].strip())
            continue
        if cur is not None:
            sm = re.match(r'^摘要[:：]\s*(.*)$', line)
            if sm:
                cur["summary"] = sm.group(1).strip()
            elif line.strip().startswith("- [") or line.strip().startswith("-["):
                for lm in re.finditer(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', line):
                    cur["links"].append((lm.group(1).strip(), lm.group(2).strip()))
    if cur:
        entries.append(cur)
    return entries, highlights


# ---------- 平台识别（用于「平台动态」条目标签）----------
PLATFORM_KW = [
    ("ChatGPT", "ChatGPT"), ("OpenAI", "OpenAI"),
    ("Claude", "Claude"), ("Anthropic", "Claude"),
    ("Gemini", "Gemini"),
    ("Perplexity", "Perplexity"),
    ("Google", "Google"), ("谷歌", "Google"),
    ("豆包", "豆包"), ("字节", "豆包"),
    ("DeepSeek", "DeepSeek"), ("深度求索", "DeepSeek"),
    ("Kimi", "Kimi"), ("月之暗面", "Kimi"),
    ("文心", "文心"), ("文心一言", "文心"), ("百度", "百度"),
    ("千问", "千问"), ("通义", "千问"),
    ("元宝", "元宝"),
    ("xAI", "xAI"), ("Grok", "xAI"),
    ("Cloudflare", "Cloudflare"),
]


def platform_of(title):
    t = title.lower()
    for kw, plat in PLATFORM_KW:
        if kw.lower() in t:
            return plat
    return None


def part1_tag(e):
    """Part1 条目标签：平台动态带【平台动态-<平台>】，其余用 [分类]。"""
    if e["cat"] == "平台动态":
        plat = platform_of(e["title"]) or "平台"
        return f"【平台动态-{plat}】"
    return f"[{e['cat']}]"


# 今日精华防回归：分点不得带分类标签（标签只属于带序号条目）
CATS_TAG = ["行业政策", "行业方法论", "新技术", "市场动态", "舆情", "平台动态"]
HL_TAG_RE = re.compile(r'^\[(' + '|'.join(CATS_TAG) + r')\]\s*')
HL_TAG2_RE = re.compile(r'^【平台动态[^】]*】\s*')
# 防御性去除分点中误加的序号装饰（①②③ / 数字. / 、等），避免破坏格式统一
HL_PREFIX_RE = re.compile(r'^[①②③④⑤⑥⑦⑧⑨⑩\s\.\、\．\·]+')


def strip_hl_tag(s):
    """防御性去除精华分点中误带的分类标签与序号装饰。"""
    s = HL_TAG2_RE.sub("", HL_TAG_RE.sub("", s))
    return HL_PREFIX_RE.sub("", s).strip()


# ================= 信源筛选机检（方案 C · 2026-09-23 用户确立，脚本层固化）=================
# 设计目的：把「信源铁律」从"写在 prompt 里靠 AI 每次自觉"升级为"脚本每日强制校验"，
# 防止规则漂移复发（此前教训：约束过严 → 国内信源占比 72.5%→29%、Google 占比 0%→38.7%）。
#
# 采用【基线豁免 + 新增违规硬阻断】的防退化模型（沿用增量同步防退化设计思想）：
#   - 历史已存在的违规 → 记入基线文件，仅 WARN 提示（可追溯但不阻断，避免一上来就卡死全量渲染）
#   - 基线之外的新违规 → SystemExit 硬阻断，宁可日报不发，也不让劣化信源流入飞书文档
#   - 人工修复后可用 `python gen_geo_doc.py --rebase` 重建基线（须确认每条确已修复）
#
# 规则清单（含禁采域名 / 聚合站）以冻结文件 SOURCE_RULES.md 为唯一事实源，改文件即生效。
SOURCE_RULES_FILE = os.path.join(WS, "SOURCE_RULES.md")
AUDIT_BASELINE = os.path.join(WS, "_source_audit_baseline.json")

_FALLBACK_BLACK = ["searchengineland.com", "getsearchengine.com", "new.qq.com/rain/a/", "weibo.com"]
_FALLBACK_AGG = ["lawrencehitches.com/ai-search-tracker"]


def _load_rule_block(marker, fallback):
    """从冻结文件 SOURCE_RULES.md 的机检配置区读取域名清单（形如 <!-- MARKER ... -->）。"""
    try:
        t = open(SOURCE_RULES_FILE, encoding="utf-8").read()
    except OSError:
        return list(fallback)
    m = re.search(r"<!--\s*" + marker + r"(.*?)-->", t, re.S)
    if not m:
        return list(fallback)
    out = []
    for line in m.group(1).split("\n"):
        line = line.strip()
        if not line or line.startswith(("以下", "（", "(")):
            continue
        if re.match(r"^[a-z0-9\.\-/]+$", line):
            out.append(line)
    return out or list(fallback)


BLACKLIST = _load_rule_block("BLACKLIST", _FALLBACK_BLACK)
AGGREGATORS = _load_rule_block("AGGREGATOR", _FALLBACK_AGG)

# 国内信源域名特征（用于信源结构漂移监控）
CN_HINT = (
    "163.com", "toutiao", "qq.com", "sina", "sohu", "baidu", "zhihu", "36kr", "jiemian",
    "huxiu", "ithome", "ifeng", "people", "xinhua", "51ima", "chinaz", "csdn", "tmtpost",
    "donews", "yicai", "stcn", "eastmoney", "10jqka", "iimedia", "199it", "cnbeta",
    "pconline", "zol", "aixinzhijie", "chinanews", "gov.cn", "ac.cn", "org.cn",
    "cet.com.cn", "cloud.tencent", "aliyun", "infoq", "qbitai", "jiqizhixin", "leiphone",
    "iyiou", "caixin", "nbd", "thepaper", "infzm", "geekpark", "deeptech", "iresearch",
    "analysys", "ithome", "cnii", "cctv",
)
# 国内信源条目占比告警阈值（低于此值说明中文检索池被过度淘汰，方案 C 纠偏前 9 月仅 29%）
CN_RATIO_ALERT = 0.40


def _host(u):
    m = re.match(r"https?://([^/]+)", u or "")
    return m.group(1).replace("www.", "") if m else ""


def is_cn_source(u):
    h = _host(u)
    return h.endswith(".cn") or h.endswith(".com.cn") or any(k in h for k in CN_HINT)


def audit_sources(entries, rebase=False):
    """信源机检：返回 (violations, stats)。violations 为违规指纹->描述的dict。"""
    violations = {}

    # 1) 禁采域名 / 路径（用户浏览器打不开，或历史频繁 404、文不对题）
    for e in entries:
        for _t, u in e["links"]:
            for b in BLACKLIST:
                if b in u:
                    violations[f"blacklist|{e['date']}|{u}"] = (
                        f"禁采域名命中 [{b}]：{e['date']} {e['title'][:30]} — {u}"
                    )

    # 2) 独立信源铁律：同一 URL（忽略查询参数）被 ≥2 条不同消息共用
    url2titles = {}
    for e in entries:
        for _t, u in e["links"]:
            url2titles.setdefault(u.split("?")[0], set()).add((e["date"], e["title"]))
    for u, ts in url2titles.items():
        if len(ts) > 1:
            names = " / ".join(t[:26] for _d, t in sorted(ts))
            violations[f"shared|{u}"] = f"独立信源违规：同一链接被 {len(ts)} 条消息共用 — {u}（{names}）"

    # 3) 外部链接必须带 lk_jump_to_browser=true（飞书内跳转浏览器）
    for e in entries:
        for _t, u in e["links"]:
            if u.startswith("http") and "lk_jump_to_browser" not in u:
                violations[f"noparam|{e['date']}|{u}"] = f"链接缺 lk_jump_to_browser：{e['date']} — {u}"

    # 4) 实体条目必须至少有一条可溯源链接（哨兵「无动态」豁免）
    for e in entries:
        if not e["links"] and e["cat"] != SENTINEL_CAT:
            violations[f"nolink|{e['date']}|{e['title']}"] = (
                f"无信源链接（不可溯源，按铁律应删除该条）：{e['date']} {e['cat']} {e['title'][:40]}"
            )

    # 5) 聚合页 / 追踪站不得作为日报信源（只可用于检索发现阶段）
    for e in entries:
        for _t, u in e["links"]:
            for a in AGGREGATORS:
                if a in u:
                    violations[f"aggregator|{e['date']}|{u}"] = (
                        f"聚合站被用作信源：{e['date']} {e['title'][:30]} — {u}"
                    )

    # 统计（信源结构漂移监控）
    real = [e for e in entries if e["cat"] != SENTINEL_CAT and e["links"]]
    cn_entries = sum(1 for e in real if any(is_cn_source(u) for _t, u in e["links"]))
    stats = {
        "real": len(real),
        "cn": cn_entries,
        "cn_ratio": (cn_entries / len(real)) if real else 0.0,
    }
    return violations, stats


def run_source_audit(entries, rebase=False):
    """执行机检：基线内违规 WARN，新违规硬阻断；--rebase 时重建基线。"""
    import json

    violations, stats = audit_sources(entries, rebase)

    if rebase:
        with open(AUDIT_BASELINE, "w", encoding="utf-8") as f:
            json.dump(sorted(violations.keys()), f, ensure_ascii=False, indent=2)
        print(f"[信源机检] 基线已重建：{AUDIT_BASELINE}（{len(violations)} 条历史豁免）")
        return

    base = set()
    if os.path.exists(AUDIT_BASELINE):
        try:
            base = set(json.load(open(AUDIT_BASELINE, encoding="utf-8")))
        except Exception:
            base = set()

    legacy = [k for k in violations if k in base]
    fresh = [k for k in violations if k not in base]

    for k in legacy:
        print(f"  [WARN·历史豁免] {violations[k]}")

    if fresh:
        msg = "\n".join(f"  - {violations[k]}" for k in sorted(fresh))
        raise SystemExit(
            f"[信源机检] 检测到 {len(fresh)} 条【新增】信源违规，已中止渲染，未改动任何文档：\n{msg}\n"
            f"  处置：回数据源修复上述条目（换独立可访问信源 / 补 lk_jump_to_browser / 删除不可溯源条目）。\n"
            f"  若确认均为历史遗留且暂不修复，可先 `python gen_geo_doc.py --rebase` 重建基线后再跑。"
        )

    print(
        f"[信源机检] 通过 | 实体条目 {stats['real']} | 含国内信源 {stats['cn']} "
        f"({stats['cn_ratio']*100:.1f}%) | 历史豁免 {len(legacy)} 条"
    )
    if stats["real"] >= 10 and stats["cn_ratio"] < CN_RATIO_ALERT:
        print(
            f"  [ALERT·信源结构漂移] 含国内信源条目占比仅 {stats['cn_ratio']*100:.1f}% "
            f"(阈值 {CN_RATIO_ALERT*100:.0f}%)。中文检索池疑似被过度淘汰——\n"
            f"     请对照 SOURCE_RULES.md 方案 C 复核：软文是否已按 A/B/C 分级？B 类是否已执行换源义务？"
        )


def main():
    import sys
    rebase = "--rebase" in sys.argv
    text = open(DATA, encoding="utf-8").read()
    entries, highlights = parse_data(text)

    # 去重（同 date+title 保留首条）
    seen, uniq = set(), []
    for e in entries:
        k = (e["date"], e["title"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    entries = uniq

    # ---------- 摘要长度格式锁（2026-08-28 补钉 · 防内容膨胀退化）----------
    # 数据源「摘要」按设计应为「一句话核心内容」（用户 2026-08-28 确立：过往简练，
    # 8/27-8/28 曾因缺失此断言而膨胀至 410 字、静默进入飞书文档与 HTML）。
    # 硬上限 150 字，超限即中止、不渲染、不改文档，强制运行时 AI 回数据源把超长
    # 摘要压回一句话，避免膨胀悄悄污染下游所有产物。
    MAX_SUMMARY = 150
    for e in entries:
        if len(e["summary"]) > MAX_SUMMARY:
            raise SystemExit(
                f"[格式锁] 摘要超长被拦截：{e['date']} | {e['cat']} | {e['title']}\n"
                f"  当前 {len(e['summary'])} 字 > 上限 {MAX_SUMMARY} 字。\n"
                f"  请回数据源 GEO每日动态_数据.md 把该条「摘要」压成一句话（≤{MAX_SUMMARY}字）后再跑。"
            )

    # ---------- 信源机检（方案 C · 2026-09-23 固化）----------
    # 在渲染前执行：新增违规即中止，确保劣化信源不会进入飞书文档与 HTML 日报。
    run_source_audit(entries, rebase=rebase)

    by_date = {}
    for e in entries:
        by_date.setdefault(e["date"], []).append(e)
    dates = sorted(by_date.keys(), reverse=True)

    # ---------- Part1 每日动态（按月份分组：月份为左侧目录层级，每日动态降级不出目录）----------
    # 设计（2026-08-05 用户侧边栏升级）：Part1 下一级=每月（### 标题，保留在侧边栏），
    # 单日动态降级为加粗文本（非标题），不再挤占左侧目录，解决目录过长问题。
    p1 = []
    months = {}
    for d in dates:
        months.setdefault(d[:7], []).append(d)
    for ym in sorted(months.keys(), reverse=True):
        y, m = ym.split("-")
        p1.append(f"### {y}年{int(m)}月\n\n")
        for d in months[ym]:
            real = [e for e in by_date[d] if e["cat"] != SENTINEL_CAT]
            p1.append(f"**{d}**\n\n")
            if real:
                p1.append("**今日精华**\n\n")
                hl = highlights.get(d, [])
                if hl:
                    for b in hl:
                        p1.append(f"- {strip_hl_tag(b)}\n")
                else:
                    for e in real:
                        p1.append(f"- {e['title']}\n")
                p1.append("\n")
                for i, e in enumerate(real, 1):
                    links = " ｜ ".join(f"[{t}]({u})" for t, u in e["links"]) or "（无链接）"
                    p1.append(f"{i}. **{part1_tag(e)} {e['title']}**  \n")
                    p1.append(f"内容：{e['summary']}  \n")
                    p1.append(f"链接：{links}\n")
                p1.append("\n")
            else:
                # 无动态日：明确标记「本日无新增」，证明自动化已执行而非漏跑
                p1.append("**今日精华**\n\n")
                p1.append("- 本日无新增 GEO 行业动态（自动化已执行全量检索，窗口内无可收录净新条目）\n\n")
                p1.append("（本日无符合收录标准的动态条目）\n\n")

    # ---------- Part2 分类索引 ----------
    p2 = []
    for cat in CATS:
        items = [e for e in entries if e["cat"] == cat]
        items.sort(key=lambda x: x["date"], reverse=True)
        if not items:
            continue
        p2.append(f"### {cat}\n\n")
        for e in items:
            block = f"- {e['date']} ［{e['title']}］  \n"
            for t, u in e["links"]:
                block += f"[{t}]({u})  \n"
            p2.append(block + "\n")

    # ---------- Part3 周度总结 ----------
    weekly_body = ""
    if os.path.exists(WEEKLY):
        weekly_body = open(WEEKLY, encoding="utf-8").read().strip()

    # ---------- 组装（固定骨架，三视图各一次）----------
    doc = []
    doc.append("# GEO每日行业动态【持续更新】\n\n")
    doc.append(C_SRC + "\n\n")   # 信源筛选原则：文档最顶部（H1 之后、阅读指引之前），2026-08-21 起固定
    doc.append(C_READ + "\n\n")
    doc.append("## Part1 每日动态\n\n")
    doc.extend(p1)
    doc.append("## Part2 分类索引\n\n")
    doc.append(C_CAT + "\n\n")
    doc.extend(p2)
    doc.append("## Part3 周度总结\n\n")
    doc.append(C_WEEK + "\n\n")
    if weekly_body:
        doc.append(weekly_body + "\n")
    else:
        doc.append("_（暂无周度总结；每周一自动生成）_\n")

    out = "".join(doc)
    open(OUT, "w", encoding="utf-8").write(out)

    # 自检：三视图各仅一次
    assert out.count("## Part1 每日动态") == 1, "Part1 出现多次！"
    assert out.count("## Part2 分类索引") == 1, "Part2 出现多次！"
    assert out.count("## Part3 周度总结") == 1, "Part3 出现多次！"
    # 信源筛选原则（C_SRC）：必须出现在文档最顶部（H1 之后、C_READ 之前），且为 <callout> 包裹（2026-08-21 用户确立）
    top_sec = out[:out.index("## Part1 每日动态")]
    assert "信源筛选原则" in top_sec, "信源筛选原则 callout 缺失！"
    assert re.search(r'# GEO每日行业动态【持续更新】\s*\n+<callout', top_sec), "信源筛选原则未紧跟 H1 且未以 <callout> 包裹！"
    assert top_sec.index("信源筛选原则") < top_sec.index("阅读指引"), "信源筛选原则须在阅读指引（C_READ）之前！"
    assert "<!--" not in top_sec, "文档顶部泄漏了 HTML 注释！C_SRC 加载未剥离注释。"
    present_cats = [c for c in CATS if any(e["cat"] == c for e in entries)]
    for c in present_cats:
        assert f"### {c}" in out, f"缺分类 {c}"
    # 月份分组后：日期为加粗文本（非标题），校验 Part1 内含最新日期且日期严格倒序
    part1_sec = out[out.index("## Part1 每日动态"):out.index("## Part2 分类索引")]
    assert dates[0] in part1_sec, "最新日期未在 Part1"
    found_dates = re.findall(r'\*\*(\d{4}-\d{2}-\d{2})\*\*', part1_sec)
    assert found_dates == dates, f"Part1 日期顺序错误：{found_dates[:3]} vs {dates[:3]}"
    # 今日精华防回归：分点不得带分类标签（只带序号条目才有）
    assert not re.search(r'^- \[(' + '|'.join(CATS) + r')\]', part1_sec, re.M), "今日精华段出现分类标签 [分类]！"
    assert not re.search(r'^- 【平台动态', part1_sec, re.M), "今日精华段出现平台动态标签！"
    # Part2 区域（分类说明 callout + 分类条目）不得含裸 HTML 注释（2026-08-19 事故根因）
    part2_sec = out[out.index("## Part2 分类索引"):out.index("## Part3 周度总结")]
    assert "<!--" not in part2_sec, "Part2 区域泄漏了 HTML 注释！C_CAT 加载未剥离注释。"
    # 分类说明必须以 <callout> 包裹（紧跟 Part2 标题之后），不得是裸文本
    assert re.search(r'## Part2 分类索引\s*\n+<callout', part2_sec), "Part2 分类说明未以 <callout> 包裹！"

    print(f"OK 渲染完成 | 条目={len(entries)} 日期数={len(dates)} "
          f"Part2分类={len(present_cats)}/{len(CATS)} | 输出={OUT}")


if __name__ == "__main__":
    main()
