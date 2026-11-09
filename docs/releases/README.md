# 发布流程

当前按源码版本发布：将通过验证的代码提交到 GitHub `main`，并创建对应的版本标签。不向 GitHub Release 附加大型安装包，也不自动发布 PyPI。

版本在 `pyproject.toml`、`uv.lock` 和 `cota/__init__.py` 的源码回退值中保持一致。每个正式版本在本目录提供对应的 `<version>.md` 发布说明。

提交前执行：

```sh
python scripts/check.py --coverage
```

按需要在本地构建并验证安装包：

```sh
python -m pip install build twine
python scripts/bundle_runtime.py --output .build/pi-runtime-release
COTA_RUNTIME_DIR="$PWD/.build/pi-runtime-release" python -m build
python -m twine check dist/*
```

在全新虚拟环境安装 wheel，再从仓库外执行 `scripts/smoke_installed.py`。核对源码包与 wheel 中只包含 weather 模板，不包含本地模型密钥、数据库、缓存或测试专用的 Bot。`.build/`、`dist/` 和运行时依赖均忽略，不提交生成物。

`tests.yml` 在主分支更新时执行源码回归；`runtime-wheels.yml` 可在 CI 验证四个平台的安装构建，但不上传安装包。构建成功与公开分发安装包是不同的操作。

将验证后的提交快进合入 `main`，创建与项目版本一致的 `v<version>` 标签并推送。已公开的版本和标签不覆盖；后续修复使用新的补丁版本。
