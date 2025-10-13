# 安装Cota
Ubuntu / macOS / Windows

可以选择通过pip安装（推荐）或通过源代码安装。只有在作为开发者，有修改Cota源代码需求时，才推荐使用源代码安装的方式。

> **提醒**
>
> 请确保准备好虚拟环境，以下操作建议在虚拟环境中进行


## 通过pip安装(暂不支持)

Pip是Python的包管理工具，可以方便地安装和管理Python包。以下是通过pip安装Cota的步骤：

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

2. **使用pip安装Cota**：
    - 打开终端或命令提示符，运行以下命令：
      ```bash
      pip3 install cota
      ```

3. **验证安装**：
    - 安装完成后，你可以通过运行以下命令来验证Cota是否安装成功：
      ```bash
      cota --version
      ```

## 通过源代码安装

如果你需要最新的开发版本或者想要自定义安装，可以通过源代码安装Cota。以下是通过源代码安装Cota的步骤：

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

2. **克隆Cota的源代码仓库**：
    - 打开终端或命令提示符，运行以下命令来克隆Cota的源代码仓库：
      ```bash
      git clone https://github.com/CotaAI/cota.git
      ```

3. **进入源代码目录**：
    - 进入克隆下来的Cota源代码目录：
      ```bash
      cd cota
      ```

4. **使用Poetry安装依赖**：
    - 使用Poetry来安装Cota所需的依赖包。运行以下命令：
      ```bash
      poetry install
      ```

5. **验证安装**：
    - 安装完成后，你可以通过运行以下命令来验证Cota是否安装成功：
      ```bash
      cota --version
      ```
