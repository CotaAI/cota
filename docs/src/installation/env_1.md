# 虚拟环境设置

推荐使用虚拟环境来隔离Python项目。如使用`virtualenv`创建隔离的Python环境，来防止了依赖冲突。

## 推荐Python版本

使用Python 3.12及以上版本，以确保兼容性和最新的语言特性。

## Ubuntu

1. 创建虚拟环境：
    ```bash
    python3 -m venv ./venv
    ```

2. 激活虚拟环境：
    ```bash
    source ./venv/bin/activate
    ```

## macOS

1. 创建虚拟环境：
    ```bash
    python3 -m venv ./venv
    ```

2. 激活虚拟环境：
    ```bash
    source ./venv/bin/activate
    ```

## Windows

1. 创建虚拟环境：
    ```cmd
    C:\> python3 -m venv ./venv
    ```

2. 激活虚拟环境：
    ```cmd
    C:\> .\venv\Scripts\activate
    ```

***

激活虚拟环境后，你就可以在这个环境中安装项目所需的Python包，而不会影响系统的其他部分。

> **提醒**
>
> - 确保你使用的Python版本符合项目要求。
> - 激活虚拟环境后，你可以在环境中安装项目所需的Python包，而不会影响系统的其他部分。
> - 当你完成工作后，可以通过运行`deactivate`命令来退出虚拟环境。
