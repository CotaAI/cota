# 发布流程

发布包含源码版本管理、安装包验证和 PyPI 分发。维护者在测试通过后更新主分支与版本标签，再发布经过验证的安装包。

版本在 `pyproject.toml`、`uv.lock` 和 `cota/__init__.py` 的源码回退值中保持一致。每个正式版本在本目录提供对应的 `<version>.md` 发布说明。

提交前执行：

```sh
python scripts/check.py --coverage
```

在对应平台构建并验证安装包：

```sh
uv pip install build twine
python scripts/bundle_runtime.py --output .build/pi-runtime-release
COTA_RUNTIME_DIR="$PWD/.build/pi-runtime-release" python -m build
python -m twine check dist/*
```

在全新虚拟环境安装 wheel，再从仓库外执行 `scripts/smoke_installed.py`。核对源码包与 wheel 中只包含 weather 模板，不包含本地模型密钥、数据库、缓存或测试专用的 Bot。`.build/`、`dist/` 和运行时依赖均忽略，不提交生成物。

`tests.yml` 在主分支更新时执行源码回归；`runtime-wheels.yml` 验证四个平台的构建与安装。发布前应收集各平台验证通过的 wheel 和同一版本的源码包。

将验证后的提交快进合入 `main`，创建与项目版本一致的 `v<version>` 标签并推送。已公开的版本和标签不覆盖；后续修复使用新的补丁版本。

## 发布到 PyPI

使用维护者的 PyPI 发布凭据，将同一版本的已验证安装包放入独立目录后上传：

```sh
python -m twine check dist/*
python -m twine upload dist/*
```

`dist/` 应只包含此次版本的 wheel 和源码包。发布凭据通过本地配置或发布环境提供，不写入项目文件。上传后在全新虚拟环境中安装对应版本，核验 `cota --version`、`cota init` 和 Bot 执行。
