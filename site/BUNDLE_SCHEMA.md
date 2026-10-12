# 网站数据包格式 `site/data/bundle.json`

由 `tools/build_bundle.py` 从 `data/daily/*.json`、`data/weekly/*.json` 和 C_CAT / C_SRC 原文打包生成；网站 `site/index.html` 用相对路径 `fetch('data/bundle.json')` 读取。

```json
{
  "generated_at": "2026-10-12T11:30:00+08:00",
  "meta": {
    "title": "GEO 每日行业动态",
    "categories": ["行业政策", "行业方法论", "新技术", "市场动态", "舆情", "平台动态"],
    "c_cat": ["分类说明：", "- 行业政策：监管 / 标准 / ……", "……"],
    "c_src": "本文档信源筛选原则：真实可溯可访问 + 优先权威/中立媒体 + 非软文 + 时效5天以内",
    "stats": {"days": 57, "entries": 145, "weeks": 9, "first_date": "2026-07-20", "last_date": "2026-10-09"}
  },
  "days": [
    {
      "date": "2026-10-09",
      "weekday": "周五",
      "status": "normal | few | none",
      "legacy": true,
      "highlights": ["……"],
      "entries": [
        {
          "id": "2026-10-09-01",
          "category": "行业方法论",
          "platform": "",
          "region": "国内 | 海外 | null",
          "title": "……",
          "summary": "……",
          "insight": "…… 或 null",
          "published": "YYYY-MM-DD 或 null",
          "links": [{"text": "……", "url": "https://……"}],
          "source_type": "…… 或 null",
          "soft_class": "无 | B | C | null",
          "backfilled": false
        }
      ]
    }
  ],
  "weeks": [
    {
      "week_start": "2026-09-14",
      "week_end": "2026-09-20",
      "legacy": true,
      "overview": {"total": 12, "by_category": {"行业政策": {"count": 2, "pct": 0.167}}, "note": null},
      "trends": [{"text": "……", "refs": ["2026-09-16-01"], "ref_links": [{"title": "……", "url": "https://……"}]}],
      "platform_changes": [{"dimension": "信源引用逻辑", "text": "……", "refs": [], "ref_links": []}],
      "implications": ["……"]
    }
  ]
}
```

说明：
- `days` 按日期倒序，`weeks` 按 week_start 倒序；同一天 `entries` 按数组顺序展示（已按重要性排好）。
- `status`：`few` 时该日顶部显示"今日 GEO 时效性动态较少"；`none` 时该日只显示"今日无新增 GEO 行业动态（已执行全量检索）"，entries 为空。
- `highlights` 可能为空数组（历史部分日期没有精华）：此时网站回退为显示当日各条标题作为精华要点。
- 历史条目大多 `insight`、`region`、`published`、`source_type`、`soft_class` 为 null：字段为 null 时网站不显示该项，不显示占位符。
- 周结的 `refs` 是条目 id（网站据此找到条目标题和 links[0]）；历史周结可能只有 `ref_links`（直接给标题和链接）。两者都要能渲染，优先 refs。
- `platform` 只有平台动态条目有值；网站在分类标签处显示为「平台动态 · 豆包」。
