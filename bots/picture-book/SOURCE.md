# Skill 来源

`skills/creating-childrens-picture-books/` 来自用户提供的完整本地 Skill：
`creating-childrens-picture-books`，复制日期 2026-11-09。

保留创作指南、主题参考、项目模板和验证器；未复制缓存、作品、密钥或本机环境记录。
原始路径只是来源说明，运行不依赖该路径。

SKILL.md 保持原始通用内容，不引用 Cota 专属文件。agent.yml 描述模型能力分工和业务要求；已有 references/runtime-setup.md 补充可选的 Cota 绘本 Bot 配套入口，具体脚本参数及版式格式由 scripts/book.py 的 --help 提供。真实目录与 Python 解释器由运行环境提供。多模态服务配置在 endpoints.yml，不写入通用 Skill。
同步补齐两个原有验证器测试夹具的 language_review / language_reviewed 字段，使其匹配随 Skill 提供的现行验证契约。
`bookbot/`、`scripts/book.py` 是独立制作代码，核心 Cota 不依赖它们；交付复用 Cota 的通用附件能力，不再携带专属 Web 服务。
