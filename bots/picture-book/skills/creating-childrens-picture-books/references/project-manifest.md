# 项目清单 `book.json`

`book.json` 用来固定用户已确认的决定，并支持交付验证。复制 `assets/project-template/book.json` 后填写。

首次使用或切换环境时按 [环境准备与图像工具接入](runtime-setup.md) 保存能力检查结果，可增加 `runtime_record: "环境检查.md"`。该字段记录环境证据，不提供模型路由或凭证配置功能；不在清单里存储密钥。

必填字段：

| 字段 | 含义 |
|---|---|
| `title` | 书名 |
| `audience_age` | 目标年龄描述 |
| `book_type` | 参照场景库选择主类型，允许自定义；`themes` 添加辅助标签，不再限于行为/科普 |
| `language` | 通常为 `zh-CN` |
| `page_count` | 含结构性空白、正常阅读顺序的PDF总面数 |
| `format.width_mm/height_mm` | 成品物理尺寸 |
| `format.paper` | `A5`、`A4`、`custom` 等 |
| `format.orientation` | `portrait` 或 `landscape` |
| `format.requires_trimming` | 是否需要裁切 |
| `binding` | `loose-leaf`、`ring`、`saddle-stitch`、`perfect-bound` 等 |
| `printing.home` | 是否交付家庭打印版 |
| `printing.professional` | 是否交付送印版 |
| `pages` | 每页页码、角色、标题、文字、图片资产和版式 |
| `deliverables` | 各PDF、预览和打印说明的相对路径 |

页面角色使用：`cover`、`inside-cover`、`title`、`copyright`、`story`、`activity`、`ending`、`inside-back-cover`、`back-cover`、`blank`。封面应为第一面，封底应为最后一面；若项目明确以独立封套交付，可在说明字段记录例外。

`layout` 应描述真实版式，如 `full-bleed-with-negative-space`、`integrated-single-page`、`two-scene-sequence`、`context-to-detail`、`quiet-page`，不要把所有页都写成同一个模板。

路径均相对于项目目录。`reading_pdf` 与 `home_print_pdf` 可以指向同一文件，但必须明确该文件确实同时满足两种用途。

## 阅读目标与审校记录

建议增加 `reading_experience`（快乐、安抚、想象、探索等），`themes`，`reality_mode`（现实、幻想或混合）。无字书允许 `text` 为空；不要让模板强制每页正文或教育结论。

`editorial_review` 记录审校文件路径；该文件每条包含：页码、原句或画面、事实/比喻/幻想/价值建议分类、风险、来源链接与查阅日期、适用年龄/条件、修订及状态。无现实知识的页面可记“不适用”并写理由。

科学事实的来源不能替价值观背书；儿童试读、专业审校、实物打印分别记录实际完成情况。没有执行的检查如实记“待验证”，不得勾选为已完成。可交付数字审阅版并注明印刷待验证，不应为通过脚本伪造验证。

`language_review` 指向语言审校记录，可与 `editorial_review` 共用 `内容审校.md`，但须有独立的语言审校部分。`qa.language_reviewed` 默认 `false`；完成 [语言审校](language-review.md) 的两轮检查并核对最终PDF后才设为 `true`。新项目及修订后交付的旧项目都须满足；历史交付不自动标记通过。后续修改文字时重置并复核。

## 主题指导记录

新项目增加 `theme_guides`（实际采用的技能内指南路径数组）与 `theme_principles`（项目内主题创作约定文件路径，亦可指向包含该节的故事与分镜）。前者是技能参考，不是项目资源路径；后者必须随项目交付。历史项目可在修订时补齐，无需为了旧字段迁移重做全书。

主题创作约定记录：主体验与辅助目标、3—5条适用原则、故事和画面中的落实方法、禁止的误导、专题核验项。完成审校时逐项记“通过／修订后通过／待验证／不适用及原因”，不把指南清单原样抄给儿童阅读。

## 默认打印结构字段

新项目设置 `printing.profile: "separate-covers-title"`、`printing.title_single_sided: true`、`printing.sheets`；记录 `content_page_count` 与 `blank_page_count`，不要和 `page_count` 混用。`printing.duplex` 写 `"mixed"`，由各任务决定单双面。

默认完整PDF：1封面、2空白inside-cover、3独立title、4空白blank、5起正文、倒数第2面空白inside-back-cover、最后back-cover。内文若奇数面，末尾再补blank。所有留白记录 `blank: true`、`blank_reason`，不带文字或图片资产。

默认设置 `printing.delivery_mode: "single-pdf"`，`printing.jobs` 可为空；仍须保留完整页序、空白、总纸张数及 `sheet_map`。需要备选分文件时，`printing.jobs` 为四个有序任务，每项含 `file`、`source_pages`（完整PDF的1起始页码数组）、`mode`（simplex/duplex）、`sheets`。01、02、04三个单面任务指封面、扉页、封底，内文任务双面；实际数组顺序是封面、扉页、内文、封底。各任务可附纸张规格，分文件为另一成品尺寸时同时记录 `width_mm`、`height_mm`。

`print_status: "pending-physical-proof"` 与 `qa.print_tested: false` 表示数字检查完成但实物试印待做；验证器报告警告，不应伪造已通过。结构/文件/页序错误仍必须修正。`sheet_map` 建议列每张物理纸的正反PDF页码与用途。
