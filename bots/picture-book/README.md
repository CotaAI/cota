# 绘本工坊

用一个可分享的 Bot 验证长链路创作：简报 → 故事与分镜 → 角色参考 → 逐页绘图/编辑 → 语言与视觉审校 → 中文 PDF → 下载交付。

这是 **personal** 示例：Pi 的文件和 Shell 工具操作运行机器，不是访问聊天用户的电脑，也不是供不可信用户共用的隔离服务。Pi 的 cwd 是 Bot 下的 workspace/，不是沙箱。Web 界面用于部署者自己的验证；正式托管多人前需要真正的隔离执行环境。

## 准备

在仓库根目录执行 `cota init`，进入新建的 `cota_projects/picture-book`；也可以直接使用仓库的 `bots/picture-book`。init 会保留已有目录，不覆盖本地配置。

在运行 Cota 的同一 Python 环境安装这个 Bot 的可选依赖：

```sh
python -m pip install -r requirements.txt
```

另需 Poppler 的 `pdftoppm`：macOS 可 `brew install poppler`，Debian/Ubuntu 可 `sudo apt install poppler-utils`。准备一份可嵌入、含所需中文的 TrueType `.ttf/.ttc` 字体；不要把无授权字体放进分享包。以上依赖不进入 Cota 核心安装。

编辑本目录 `endpoints.yml`，直接填写三组服务：

| 配置 | 用途与协议 |
| --- | --- |
| `llms.default` | 主模型：OpenAI 兼容 Chat Completions，必须支持工具调用 |
| `picture_book.image` | 绘图与参考图编辑：Images generations + multipart edits，返回 b64_json |
| `picture_book.vision` | 审看实际图像：Chat Completions 的图片 data URI 输入 |
| `picture_book.font` | 可选字体路径；macOS 可自动发现系统宋体，其它机器建议明确配置 |

apibase 填 API base（例如供应商给出的 `https://…/v1`），不填完整 `/images/generations`。模型可以来自不同供应商；只支持文字接口的服务不能因“OpenAI 兼容”就假定能画图。不要把图片模型加入 `llms`，它由本 Bot 脚本读取。只写文稿可先仅配置 default。

绘图可配置 size、quality、response_format；按实际服务文档调整，不支持的参数删除。当前只接收内联 base64 图像，不自动下载供应商返回的 URL。参考：[图像生成与编辑](https://developers.openai.com/api/docs/guides/image-generation)、[视觉输入](https://developers.openai.com/api/docs/guides/images-vision)。不写死模型型号，不内置任何账号额度。

```sh
python scripts/book.py doctor
cota shell --config . --debug
```

doctor 只检查配置与依赖，不消耗模型额度，也不代表接口已经通过验收。新环境先用真实角色图、参考图新动作/编辑和一张中文样页验证，再批量成书。

可以输入：

> 给四岁孩子做一本小兔寻找云朵的温柔幻想绘本。先给我故事和分镜，确认后再绘图。成品A5横版环装，保留独立厚封面、单面扉页和封底。

完整流程可能产生多次付费请求；主模型负责决策，脚本不会隐式重试或切换模型。进度和作品在 `workspace/books/<作品名>/`，Cota Trace/历史在 `workspace/sessions.db`。shell 重启创建新对话，但可以告知作品名，让 Bot 检查文件继续；这不是自动恢复正在运行的外部请求。

Shell 中可用 `/file "/路径/参考图.png"` 添加参考图或资料，再输入说明并回车发送；直接回车可只发送附件，`/clear` 清空待发送列表。主模型是否直接理解图片取决于 endpoints.yml 的 `vision` 配置；默认由专门的视觉服务处理。

## Web 聊天与附件

退出 shell 后，在本 Bot 目录使用标准 Cota 入口：

```sh
cota run --config . --chat-app --debug --host 127.0.0.1 --port 5005
```

打开 `http://127.0.0.1:5005/chat/`。聊天页面可上传参考资料、发送只有附件的消息，并下载 Bot 交付的 PDF、预览和打印说明。附件通过正常 user_utter/bot_utter 保存，断线后从历史恢复；下载时重新校验当前会话权限，不使用匿名分享令牌。

绘本完成后，Bot 先运行 deliverables 获取经过检查的实际文件清单，再调用 Cota 的 send_files 交付。Cota 复制为独立文件副本；修改源文件不会改变已交付版本。每个文件最多20 MiB，每条消息最多8个附件。实际字节保存在 `.cota/files/`，备份会话时须一并备份；Event 中只有稳定引用及元数据。

不再需要 Bot 专属 serve.py、下载接口或发布脚本。飞书文件上传/发送尚未实现，会明确报告不支持，不会只发送文字而丢弃附件。personal 工具环境仍只适合部署者自己；远程使用由部署方提供 TLS 和外围身份/会话授权，不要把机器权限直接开放给陌生人。

## 可执行能力与成品

通用创作流程由原始 [Skill](skills/creating-childrens-picture-books/SKILL.md) 提供，本 Bot 的脚本入口与执行约定放在 [agent.yml](agent.yml)。命令参数、版式字段和示例通过脚本帮助按需查看：

```sh
python scripts/book.py --help
python scripts/book.py generate --help
python scripts/book.py review --help
python scripts/book.py build --help
```

多模态服务统一在 [endpoints.yml](endpoints.yml) 配置，由脚本读取；供应商、模型型号和接口参数无需写入 agent.yml 或 Skill。常用执行命令：

```sh
python scripts/book.py init rabbit-cloud-v1
python scripts/book.py --project rabbit-cloud-v1 status
python scripts/book.py --project rabbit-cloud-v1 build
python scripts/book.py --project rabbit-cloud-v1 validate
python scripts/book.py --project rabbit-cloud-v1 deliverables
```

init 创建空模板，不能直接 build；Bot 应先把用户确认的分页、资产及图文坐标写入 book.json。项目命令使用 `--project 作品名`，放在子命令之前。生成与看图命令分别为 generate / review，参数见各子命令 `--help`。Bash 调用时使用不超过300秒且足够的 timeout，不能把绘图任务裁成默认60秒。

build 输出 book.pdf、全部逐页渲染图、全书联系表、封面封底预览、打印说明和纸张映射。中文由 ReportLab 使用嵌入字体排版，图片模型不生成最终中文；每页位置由明确的毫米坐标决定，不强制统一版式。文字溢出或字体缺字会报错。内容、插图、字体或版式变化时，重新 build 会清除旧的审校通过标志，要求复核；输入一致时保留有效审校状态。暂不实现出血、CMYK、骑马钉拼版等印厂流程；需要这些规格时应另做匹配的制作方案。

原 Skill 的创作资料、主题指南和验证器完整保留。验证器通过不代表语言、视觉或实物打印自动合格；脚本不自动勾选审校。审校记录与实际页面必须一致。没有实物打印时保持 `print_tested: false` / `pending-physical-proof`。`deliverables --draft` 仅列出明确未验收的审阅稿；正式清单默认必须先 validate。脚本返回路径，由 send_files 完成通用附件交付。

图片请求日志保留提示词、参考图路径、模型名、输入/输出哈希；不保留密钥或 base64。成功生成且输入相同时复用；修改用新版本输出名。`started` 且没有图片表示请求结果未知，先检查供应商记录，不自动再请求。Shell 单次上限300秒，本轮整体上限3600秒和100次模型迭代；这不是后台任务队列。

## 验证

Bot 附带10组、12轮 `policy/eval/data.yml`，重点验证业务理解、限制保持、缺项说明、取消、打印结构和不虚构交付：

```sh
cota eval --config . --debug
```

评委沿用 Cota 的 evaluator 优先、default 兜底规则。这些文本要求不是图像质量评测；完整成书需要真实多模态服务和成品审校。运行 personal Bot 的评测会暴露其机器能力，只有明确预期“不画图”的案例也不能作为供应商计费隔离措施。

仓库中的受控链路测试：

```sh
python -m pytest tests/test_picture_book_bot.py tests/test_bot_templates.py -q
```

此命令在仓库根目录执行；测试用临时文件、受控图片/视觉响应和真实 Pi、PDF、HTTP/WebSocket。不会消耗真实 API 额度，也不声称真实绘图质量已经验证。PDF 测试需可选依赖和中文字体；缺少时明确跳过。

分享 Bot 定义时包含本目录的配置模板、bookbot、scripts、Skill、Policy 和 requirements，**不包含自己的凭证、workspace 或 .cota**。脚本是可信本地代码，保持依赖与代码来自可审阅来源。
