# GEO 行业动态日报

每个工作日自动整理一份 GEO（生成式引擎优化）行业动态：当日精华、按分类归档的索引，以及每周一的周度总结。

**公开网址：<https://vannissiuu.github.io/geo-daily/>**

网页有三个视图：每日动态、分类索引、周度总结。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `rules/` | 采集与撰写规则（01 信源与巡检、02 筛选、03 分类、04 输出格式、05 周度总结）。AI 每次运行都先读这里 |
| `config/sources.json` | 机器可读的信源清单和配置 |
| `data/daily/` | 每日动态数据，一天一个文件，如 `2026-10-12.json` |
| `data/weekly/` | 周度总结，每周一生成 |
| `data/runs/` | 每次运行的记录（做了什么、查了哪些源、遇到什么问题） |
| `data/migration_report.json` | 历史数据迁入时的报告 |
| `tools/` | 脚本：`check_data.py`（检查数据）、`build_bundle.py`（生成网站数据包）、`wrap_page.py`（把网页片段包成完整页面）、`migrate_legacy.py`（一次性历史迁移） |
| `site/` | 网站源码。`index.html` 是页面，`data/bundle.json` 是生成的数据包，`BUNDLE_SCHEMA.md` 说明其格式 |
| `docs/legacy/` | 旧系统（WorkBuddy）的历史资料，仅供参考 |
| `.github/workflows/` | 自动检查与发布流程 |
| `CHANGELOG.md` | 规则与结构的变更记录 |

## 每日运行流程

1. **采集**：云端定时任务每个工作日北京时间 10:00 启动，读取 `rules/` 和 `config/`，联网采集并筛选。
2. **写数据**：生成 `data/daily/当天日期.json` 和 `data/runs/当天日期.json`；周一另写 `data/weekly/` 下的周度总结。
3. **本地检查**：先运行检查脚本，不通过就修正，直到通过。
4. **提交**：检查通过后 commit 并 push 到 `main`。
5. **Actions 再检查**：GitHub Actions 重新跑一遍检查，失败则整个流程中止，网站保持上一版不变。
6. **发布**：检查通过后自动构建并发布到 GitHub Pages，几分钟后网站更新。

定时任务的完整执行手册见 `prompts/daily_run.md`（启动指令只需指向它）；其中用到的前置脚本是 `tools/prepare_run.py`，负责算出当天的时效窗口、去重清单和周结判定。

本地检查与构建命令：

```bash
python3 tools/check_data.py
python3 tools/build_bundle.py
```

## 如何修改规则

1. 修改 `rules/` 下对应的规则文件，或修改 `config/sources.json`（增删信源等）。
2. 在 `CHANGELOG.md` 里追加一条记录：改了什么、为什么改。
3. 提交并 push 到 `main`。下一次定时任务会按新规则运行。

## 如何手动重新发布

打开仓库的 **Actions** 页面，左侧选「检查并发布网站」，点右侧 **Run workflow** 再点绿色按钮即可。适用于网站没更新、或想不改数据直接重发的情况。

## 数据格式在哪里看

- 每日 / 周度数据的字段与规则：`rules/04_输出格式.md`、`rules/05_周度总结.md`
- 网站数据包（`bundle.json`）的结构：`site/BUNDLE_SCHEMA.md`

## 历史迁移说明

2026-07-20 至 2026-10-09 的内容，于 2026-10-12 从 WorkBuddy（飞书输出）迁入本仓库。迁入的数据带有标记：

- **legacy**：旧系统产生的记录。当时的规则与现在不同，不按新规则逐条校验，仅保证能正常展示。
- **backfilled**：迁入时补填的内容（例如旧数据缺少的字段，由程序或人工推断补上），不是当天原始采集的结果。

具体处理细节见 `data/migration_report.json`；旧系统的原始资料（已脱敏）在 `docs/legacy/`。
