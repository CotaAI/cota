# 安装COTA
Ubuntu / macOS / Windows

可以选择通过pip安装（推荐）或通过源代码安装。

- **pip安装**：适合大多数用户，简单快捷
- **源代码安装**：适合开发者或需要最新开发版本的用户

> **提醒**
>
> 请确保准备好虚拟环境，以下操作建议在虚拟环境中进行


## 通过pip安装（推荐）

Pip是Python的包管理工具，可以方便地安装和管理Python包。这是最简单快捷的安装方式，推荐大多数用户使用。以下是通过pip安装COTA的步骤：

1. **确保你已经安装了Python和pip**：
    - 你可以通过运行以下命令来检查是否安装了Python和pip：
      ```bash
      python3 --version
      pip3 --version
      ```
    - 如果没有安装，请先安装Python和pip。
    - 同时确保pip更新到最新的版本
      ```bash
      pip3 install -U pip
      ```

2. **使用pip安装COTA**：
    - 打开终端或命令提示符，运行以下命令：
      ```bash
      pip3 install cota
      ```
    - 安装过程中会自动下载并安装所需的依赖包。

3. **验证安装**：
    - 安装完成后，你可以通过运行以下命令来验证COTA是否安装成功：
      ```bash
      cota --version
      ```
    - 如果显示版本号，说明安装成功！

4. **开始使用**：
    - 创建你的第一个智能体项目：
      ```bash
      cota init
      ```
    - 进入项目目录并配置：
      ```bash
      cd cota_projects/simplebot
      # 编辑 endpoints.yml 配置你的LLM API密钥
      ```
    - 启动对话测试：
      ```bash
      cota shell --debug
      ```

## 通过源代码安装

如果你需要最新的开发版本、想要参与开发或自定义安装，可以通过源代码安装COTA。以下是通过源代码安装COTA的步骤：

1. **安装Poetry**：
    - Poetry是一个依赖管理和打包工具，可以帮助你更方便地管理Python项目。首先，你需要安装Poetry。
    
      方式1：通过pip安装Poetry（推荐）：
      ```bash
      pip3 install poetry
      ```
      方式2：同样也可直接安装
      ```bash
      curl -sSL https://install.python-poetry.org | python3 -
      ```
    - 安装完成后，你可以通过运行以下命令来验证Poetry是否安装成功：
      ```bash
      poetry --version
      ```

2. **克隆COTA的源代码仓库**：
    - 打开终端或命令提示符，运行以下命令来克隆COTA的源代码仓库：
      ```bash
      git clone https://github.com/CotaAI/cota.git
      ```

3. **进入源代码目录**：
    - 进入克隆下来的COTA源代码目录：
      ```bash
      cd cota
      ```

4. **使用Poetry安装依赖**：
    - 使用Poetry来安装COTA所需的依赖包。运行以下命令：
      ```bash
      poetry install
      ```

5. **激活虚拟环境**：
    - 激活Poetry创建的虚拟环境：
      ```bash
      poetry shell
      ```

6. **验证安装**：
    - 安装完成后，你可以通过运行以下命令来验证COTA是否安装成功：
      ```bash
      cota --version
      ```

7. **开始使用**：
    - 创建你的第一个智能体项目：
      ```bash
      cota init
      ```
