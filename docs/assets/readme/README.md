# README 原理动画

`cota-workflow.gif` 与 `cota-workflow.png` 是为 Cota 原创的说明图。动画解释定义、运行、验证和交付；静态图用于不便播放动画时阅读。它们不是屏幕录制，也不表示一次真实查询或评测结果。改进环节始终表示人工修改案例后再验证。

## 重新生成

在有中文字体的创作环境中安装 Pillow（不属于 Bot 的运行依赖），然后在仓库根目录执行：

```bash
python -m pip install 'Pillow>=10'
python scripts/render_readme_demo.py
```

脚本默认查找 macOS Hiragino Sans GB、Linux Noto Sans CJK 或 Windows 微软雅黑，以及系统等宽字体。也可显式提供已安装字体：

```bash
python scripts/render_readme_demo.py --font /path/to/Chinese-font.ttf --mono-font /path/to/Monospace.ttf
```

不随仓库分发字体。生成器使用固定画布、共享 96 色调色板和差分帧；主要文字每阶段停留数秒，避免高速闪烁。首次画面为完整概览，静态 PNG 保留同样的流程说明。布局、文案和时间统一在生成脚本维护。

README 使用 main 分支的绝对 raw 图片地址，兼顾 GitHub 和读取项目说明的包索引页面；图片与 README 在同一提交中更新。支持 picture 媒体条件的渲染器会在用户偏好减少动态效果时选择静态 PNG，其它环境仍可通过“查看静态图”链接阅读。
