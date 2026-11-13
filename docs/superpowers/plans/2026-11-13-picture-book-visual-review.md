# 绘本视觉审校入口修复

目标：正式视觉审校使用 Pi 注册的 image_understand；主模型只组织、解释与决策。

边界：不修改 Pi read，不新增 Event，不处理缓存、压缩或构建恢复。删除绘本 default.vision；框架的显式多模态选项保留。

- [x] 图像工具记录实际发送字节的 SHA-256，并在结果中返回调用引用；离线测试覆盖请求中改写源文件时哈希仍对应原始输入。
- [x] 绘本 review 增加 --tool-call-id，从本 Bot SQLite Store 只读核验成功的 image_understand 调用、原始标准、模型和图像哈希，沿用 assess 与 canonical review 格式；不发起第二次视觉请求。
- [x] 正式 validate/deliverables 核验每个非空白 PDF 面的当前原生视觉证据；read、Bot 文本、失败结果、图片变更或不完整判定不能通过。draft 保留明确未验收交付。
- [x] 仓库模板统一原生图像 endpoint、Agent/Policy、配套帮助和 README。Skill 保持通用，只声明审阅应来源于实际视觉调用及版本化证据。
- [x] 安全合并到私有 Bot，保留密钥、作品、历史；重新训练 Policy，使用本地假服务验证路由和无图片主模型请求，不调用付费服务。

验证：绘本 Python 测试 138 项通过；Node 测试 175 项通过、2 项平台跳过；Ruff 与 diff 检查通过。私有 Bot 配置、本地假服务冒烟、doctor 与 Policy 产物检查通过，未调用付费服务。
