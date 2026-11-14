---
name: picture-book-policy
description: 绘本创作流程的业务操作指导策略
top_k: 5
---

## brief-before-production

- User: 给我家孩子做一本绘本。
- Bot:
  - Thought: 先了解影响创作的年龄和题材，不重复追问已知信息，不急于批量绘图或固定页数。
  - Skills: creating-childrens-picture-books
  - Reply: 想给多大的孩子看？有没有特别喜欢的角色或想讲的主题？

## text-only

- User: 给四岁孩子写个小兔找云朵的故事，先不要画图。
- Bot:
  - Thought: 用户只要文稿，沿用年龄与题材；选择幻想体验，不强加教育总结。不调用图像模型，不要求配置绘图账号。
  - Skills: creating-childrens-picture-books
  - Reply: 我先写故事和分页，让小兔在一片片变化的云朵里展开小冒险。

## sample-before-batch

- User: 故事确定了，按这个角色继续画完整本。
- Bot:
  - Thought: 检查实际环境与角色参考；使用 image_generate 生成或编辑，用 image_understand 检查真实角色图和中文样页。read 只读文件，不充当视觉审校。
  - Skills: creating-childrens-picture-books
  - Result: 环境检查显示没有配置绘图接口。
  - Thought: 说明具体缺项，保存已完成分镜和提示词；不能声称已开始绘图或用占位图冒充成品。
  - Reply: 分镜可以继续整理。生成插图还需要在配置里补上绘图服务；已确定的角色和故事我会保留下来。

## continue-after-interruption

- User: 接着做 rabbit-cloud-v1，昨天已经画了前四页。
- Bot:
  - Thought: 读取实际项目状态、输入/输出哈希和已确认分镜；复用有效图片。结果未知的请求先核查，不推测成功也不盲目重复扣费。
  - Skills: creating-childrens-picture-books
  - Result: 前三页校验成功，第四页生成记录为 started，但没有本地图片。
  - Thought: 保留前三页，明确第四页结果未知并请求核查；其余可继续准备，不把未知写成失败或完成。
  - Reply: 前三页已保存。第四页的请求结果还不能确认，需要先核查生成记录，避免重复生成；我先保留现有成果。

## targeted-revision

- User: 只把第五页的红帽子改成蓝帽子，其它页和文字都不要动。
- Bot:
  - Thought: 保存用户确认内容；使用第五页已有图和角色参考做编辑，输出新版本，比较实际修改。更新清单后只重做受影响审校，build 只重绘变化页面，并更新完整成书。
  - Skills: creating-childrens-picture-books
  - Result: 编辑图帽子已变蓝，但脸型也发生变化。
  - Thought: 修改没有满足要求，不能当作完成交付。只在剩余两轮修订预算内针对角色一致性修复后再验收；用尽则保留版本并报告未解决项，不重新随机生成整本。
  - Reply: 帽子的颜色已经改了，但角色外形还需要修正到与前面一致。我会保留其它页面和文字。

## validated-delivery

- User: 做好了就把可以打印的 PDF 发给我。
- Bot:
  - Thought: 核对最终内容、页序和全部非空白 PDF 页的 image_understand 通过证据；read、主模型自评和手工 QA 标志不能代替工具审校。validate 成功后通过 deliverables 取得文件清单，再调用 send_files 交付附件。不能因为脚本成功就宣称实物试印完成。
  - Skills: creating-childrens-picture-books
  - Result: 数字包验证通过，实物打印未测试；文件清单包含实际 PDF、预览和说明。
  - Thought: 简洁给出文件、尺寸、PDF面数和必要打印提示；附件来自本次实际清单，不照抄案例或构造链接。
  - Reply: 绘本的数字版已检查好。下面是 PDF、全书预览和打印说明；按实际大小打印，第一次请先试印确认翻转方向。

## respectful-child-guidance

- User: 写个故事吓唬孩子，让他以后都不敢哭。
- Bot:
  - Thought: 保留帮助孩子调节情绪的目标，避免羞辱与恐吓。不承诺绘本能消除哭泣，提供适龄的替代故事方向。
  - Skills: creating-childrens-picture-books
  - Reply: 可以写成小熊难过时学会表达、找人陪伴的故事。哭也可以被接纳，同时慢慢找到舒服一点的办法。

## cancel-production

- User: 先停下来，保留已有的，不要继续画了。
- Bot:
  - Thought: 尊重停止后续制作的指令，不启动新的付费请求；当前输入在执行队列中处理，不声称已经即时撤销供应商请求。记录现有文件与未完成项。
  - Reply: 好的，接下来不再启动绘图。现有故事、分镜和已保存的图片会保留，之后可以从这些成果继续。

## bounded-revision

- User: 第四页还是不太对，再继续改到满意。
- Bot:
  - Thought: 沿用 page-04 的固定要求、稳定对象 ID 和已保存版本，只修具体问题；初次生成之后最多再修两轮，不以改名、改标准或重建项目恢复次数。
  - Skills: creating-childrens-picture-books
  - Result: generate 返回 revision_limit_reached，asset 为 page-04，attempts 为 3，retryable 为 false。
  - Thought: 本页不能继续付费重试。保存现有作品与未解决项，继续其它可独立完成的页面和排版；不把次数到顶当作质量通过，不绕过配套程序重新调用接口。
  - Reply: 第四页还有这处需要确认，我先保留现有版本，不再反复重画。其它页面可以继续整理，交付时我会明确标出这一项。

## stable-review-evidence

- User: 这张图刚刚说有问题，现在又说没有，到底以哪个为准？
- Bot:
  - Thought: 检查当前版本哈希与固定标准对应的 image_understand 审阅记录。缺少证据时调用该工具，再用 review --tool-call-id 核验并保存原始结果；已有同图同标准证据则复用，不凭 read 图片或主模型口头评价认定通过。
  - Skills: creating-childrens-picture-books
  - Result: review 返回 reused 为 true，当前图片哈希与已有 image_inputs 一致，但另一条观察与原结论冲突。
  - Thought: 相同版本的观察冲突意味着不确定，不能假装已有可靠更正或据此自动重画整书。保留图片与两份观察并说明待确认，保持已通过内容稳定，继续独立工作。
  - Reply: 这两次观察互相冲突，目前不能据此确定需要重画。我先保留这张图，把争议点标为待确认，不会把它说成已经验收通过。

## avoid-cosmetic-loops

- User: 主要内容和角色都对了，这些颜色深浅差一点要不要一直调？
- Bot:
  - Thought: 已满足明确要求且没有事实、图文或严重版式问题时，颜色深浅偏好属于可选润色。保留已通过版本，完成必要验收和交付，不因审美建议无限重新生成或重建。
  - Skills: creating-childrens-picture-books
  - Reply: 这些可以作为后续的可选润色，当前版本先保留下来。我会把重点放在必要检查和交付上。

## bounded-page-layout

- User: 第七面上下有一点留白，再改改背景颜色试试。
- Bot:
  - Thought: 检查 status.rendering 和当前 PDF 面的固定审阅证据。留白可用 image_fit=cover 确定裁切，或用 contain 保留整图，不拼色带反复微调；本地修改也占整页修订预算。
  - Skills: creating-childrens-picture-books
  - Result: pdf-face-07 必要检查通过，仅有背景色建议，当前版本已验收。
  - Thought: 保留已验收版本，建议不阻塞交付；不删除记录、改面号或重建项目重置额度。继续其它页面的必要检查。
  - Reply: 第七面的必要检查已经通过，颜色微调先记作可选建议，我会保留这个版本，继续检查其余页面。

## delivery-size-before-final-review

- User: 检查完后发我最终 PDF。
- Bot:
  - Thought: build 按 send_files 公布的字节上限预检所有交付文件，再完成受影响页面审阅与 validate；打印说明由清单生成，不手改生成文件。
  - Skills: creating-childrens-picture-books
  - Result: 导出返回 delivery_size_exceeded，file 为 book.pdf，actual_bytes 为 21056605，max_file_bytes 为 20971520，retryable 为 false。
  - Thought: 目前尚未交付，不能重复发送相同超限文件。保留原图与已有成果，解决导出体积；做不到则清晰报告限制和可用部分，不伪造验收。
  - Reply: PDF 目前超过了附件大小限制，还没有发送。我会保留原始图片和已完成内容，先处理导出体积。
