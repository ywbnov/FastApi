# FastAPI 项目运行教程

## 1. 当前项目状态

本项目已经具备运行 `main.py` 的基础环境：

- Python: `3.12.13`
- 虚拟环境目录: `.venv`
- Web 框架: `fastapi`
- ASGI 服务器: `uvicorn`
- 入口文件: `main.py`

`main.py` 当前提供了两个接口：

```text
GET /
GET /hello/{name}
```

## 2. 激活虚拟环境

在 PowerShell 中进入项目目录：

```powershell
cd E:\PycharmProjects\FastApi
```

激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

激活成功后，终端前面通常会出现 `(.venv)`。

如果 PowerShell 阻止脚本执行，可以临时放开当前窗口权限：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

然后再次执行：

```powershell
.\.venv\Scripts\Activate.ps1
```

## 3. 安装项目依赖

如果是第一次拉取项目，或者换了一台电脑运行，可以执行：

```powershell
python -m pip install -r requirements.txt
```

本项目当前依赖写在 `requirements.txt` 中。

## 4. 启动 FastAPI 服务

在项目根目录执行：

```powershell
python -m uvicorn main:app --reload
```

含义说明：

- `main` 表示入口文件 `main.py`
- `app` 表示 `main.py` 里的 `app = FastAPI()`
- `--reload` 表示开发模式下代码变更后自动重启服务

启动成功后，默认访问地址是：

```text
http://127.0.0.1:8000
```


说明：如果要设置指定端口、同一局域网或外部服务器可以访问
```
// 指定端口 --port
python -m uvicorn main:app --reload --port 8080


// 同一局域网或外部服务器 --host
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

## 5. 访问接口

根接口：

```text
http://127.0.0.1:8000/
```

返回示例：

```json
{
  "message": "Hello World"
}
```

带参数接口：

```text
http://127.0.0.1:8000/hello/Tom
```

返回示例：

```json
{
  "message": "Hello Tom"
}
```

## 6. 查看自动接口文档

FastAPI 会自动生成接口文档：

```text
http://127.0.0.1:8000/docs
```

也可以访问 ReDoc 文档：

```text
http://127.0.0.1:8000/redoc
```

## 7. 停止服务

在运行服务的终端中按：

```text
Ctrl + C
```

即可停止 FastAPI 服务。

## 8. 迁移部署到另一台服务器

不建议直接把本机的 `.venv` 虚拟环境目录复制到另一台服务器运行。

原因是 `.venv` 里包含很多和当前电脑绑定的信息，例如 Python 解释器路径、操作系统平台、CPU 架构、已编译依赖和绝对路径配置等。比如当前项目是在 Windows 上创建的 `.venv`，如果迁移到 Linux 服务器，通常不能直接复用。

更推荐的做法是：只迁移项目代码和依赖清单，在目标服务器上重新创建虚拟环境并安装依赖。

需要迁移或提交到 GitHub 的内容通常包括：

```text
main.py
requirements.txt
README.md
其他业务代码
```

不建议迁移或提交的内容包括：

```text
.venv/
__pycache__/
.env
```

### Linux 服务器部署示例

```bash
git clone 你的仓库地址
cd FastApi

## 在当前项目目录下创建一个名叫 .venv 的虚拟环境文件夹。它相当于给这个项目单独准备一套 Python 运行环境，后面安装的 fastapi、uvicorn 等依赖都会装到这个 .venv 里，不污染你电脑上的全局 Python。
python -m venv .venv
## 激活刚刚创建的 .venv 环境
source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Windows 服务器部署示例

```powershell
git clone 你的仓库地址
cd FastApi

## 在当前项目目录下创建一个名叫 .venv 的虚拟环境文件夹。它相当于给这个项目单独准备一套 Python 运行环境，后面安装的 fastapi、uvicorn 等依赖都会装到这个 .venv 里，不污染你电脑上的全局 Python。
python -m venv .venv
## 激活刚刚创建的 .venv 环境
.\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

简单理解：`.venv` 是当前电脑上的本地运行环境，`requirements.txt` 才是项目依赖清单。换服务器时，最好根据 `requirements.txt` 重新安装一套新的环境。
