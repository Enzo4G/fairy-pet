# Fairy 桌宠（dsh 版）

<p align="center">
  <img src="docs/preview.png" width="140" alt="Fairy">
</p>

<p align="center">
  一个会盯着你鼠标看、会呼吸、会随机器负载变快变慢的桌面眼睛。<br/>
  接 <b>DeepSeek Harness (dsh)</b> 的本地接口，聊天、换模型、切工作区都在托盘里完成。
</p>

<p align="center">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11-4d8fd6">
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-4d8fd6">
  <img alt="license" src="https://img.shields.io/badge/license-个人非商业-blue">
</p>

> **素材来源**：形象设定与动画逻辑参考并致谢
> [Chengzhibense/Fairy-DSH](https://github.com/Chengzhibense/Fairy-DSH)（Apache-2.0）。
> 本项目仅供个人使用，**禁止商业用途**，详见 [LICENSE](LICENSE)。

---

## 它是什么

一个常驻桌面的小窗口：一颗蓝色的同心圆眼睛。它不抢焦点，全屏做事时会自己让开；
点一下开口说话，把 dsh 里正在跑的对话接着聊下去。

它不启动 dsh，也不替 dsh 做决定——只是给一个总是开着的客户端配了一张脸。

## 特性

- **会看你**：眼球跟随鼠标，移开视线后回正，不是死盯。
- **会呼吸**：眼球会脉动
- **跟负载联动**：动画速度可跟 CPU 或显卡占用率，也可手动锁在 0.4×–3.0×。
- **会累**：眼皮闭合程度可跟 CPU / 显卡 / 内存，占用越高眼睛眯得越厉害；也可整个关掉。
- **不打扰**：置顶三档（始终 / 让位 / 从不）；全屏游戏或视频时自动隐去。
- **托盘即控制台**：拖拽缩放、附件拖入、会话切换、模型与思考强度、余额与用量。

## 快速开始

### 方式一：下载 exe（推荐给普通用户）

到 [Releases](../../releases) 下载 `FairyPet-dsh-win64.zip`，解压后双击 `FairyPet.exe`。
无需安装 Python；配置会写在与 exe 同级的 `FairyPet\` 目录里。

> 首次启动会向系统申请网络访问（本机 127.0.0.1），用于和 dsh 通信。

### 方式二：从源码运行
需要 **Windows 10/11** 与 **Python 3.9+**（[下载](https://www.python.org/downloads/)，
安装时勾选 *Add python.exe to PATH*）。

```bat
:: 1. 一键准备环境（首次约 500MB，之后秒过）
setup.bat

:: 2. 启动
run.bat
```

`setup.bat` 会创建 `.petenv\` 虚拟环境并安装锁定的依赖，可重复执行，已装好就跳过。
也可以手动来：

```bat
python -m venv .petenv
.\.petenv\Scripts\python.exe -m pip install -r requirements.txt
.\.petenv\Scripts\pythonw.exe pet.py
```

### 前置条件

桌宠需要一个**正在运行的 dsh 客户端**。它会在本机端口上自动找到 dsh，
并用 `~\.dsh\.credentials.yaml` 里的本机会话密钥完成鉴权——不需要你登录、填 token，
也不会改动 dsh 的任何文件。找不到 dsh 时它会安静地显示「没找到运行中的 dsh」。

## 还有一个 HanaAgent 版

仓库里的 [`hana/`](hana/) 是同一个桌宠的另一条后端：作为 HanaAgent 的 App 存在，
走 Hana 的本地服务而不是 dsh。形象、动效、调参完全一致，只是输入区换成了 Hana 的
会话栏。两边配置目录互不干扰，可以同时跑。

## 右键菜单

```
关于
────────────────
看向鼠标
置顶 ▸              始终 / 让位 / 从不
动画速度 ▸          CPU / 显卡 / 手动
眯眼 ▸              CPU / 显卡 / 内存 / 关闭
速度 1.00×（跟 CPU） ────────●────
大小 160px          ──────●───────
────────────────
DeepSeek 账户…
隐藏      打开 dsh 客户端
退出
```

## 配置与数据

| 路径 | 内容 |
| --- | --- |
| `FairyPet\config.json` | 尺寸、置顶、速度与眯眼的联动方式、主题 |
| `FairyPet\state.json` | 窗口位置 |
| `FairyPet\deepseek.json` | DeepSeek 控制台令牌（仅本机，登录后才有） |
| `FairyPet\web\` | 登录会话的 cookie 与缓存 |

整个目录就是全部安装：换电脑拷走文件夹即可，不需要注册表、不需要 `%APPDATA%`。

## 自己打包 exe

```bat
setup.bat
build_exe.bat
```

产物在 `dist\FairyPet\`，打包脚本会接着调 `tools\prune_dist.ps1` 删掉用不到的
Qt 组件（翻译、QML 模块、3D / Charts / Pdf 等），400MB → 291MB。
整个目录一起分发（`FairyPet.exe` 依赖同级的 `_internal\`，这是 Qt WebEngine
的常规形态，单文件模式启动会慢十几秒且容易被杀软误伤）。

> 改精简清单时注意：`Qt6WebChannel.dll` 是 WebEngineCore 的硬依赖，
> `Qt6OpenGL.dll` 是 Qt6Quick 的硬依赖，删了程序会直接起不来（无窗口、无报错）。

## 已知问题

- **PySide6 不要升到 6.10.x**：该版本 QtWebEngine 渲染进程在页面有动画时以约
  **3.6 MB/s** 泄漏内存，挂一夜能吃掉几十 GB。6.8.3 实测稳定在 120MB 左右不动。
  排查记录：[docs/memory-leak.md](docs/memory-leak.md)。
- 权限按钮目前只读：改权限要走 dsh 的流式端点 `session/control`，尚未接入。
- 只测过 dsh 桌面端（Windows）。Web 版 dsh 的端口与鉴权未验证。

## 鸣谢

- [Chengzhibense/Fairy-DSH](https://github.com/Chengzhibense/Fairy-DSH) —— 形象设定与动画逻辑的来源。
- [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) —— 整个程序的地基。

## 许可

本项目代码**仅供个人非商业使用**，禁止商业用途；第三方素材适用其原有许可
（Apache-2.0）。详见 [LICENSE](LICENSE) 与 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## 免责声明

本程序为个人桌面宠物实验，与 DeepSeek、HanaAgent 官方**无关**，也未获其背书。
它只通过本机接口与客户端通信，不收集、不上传任何数据；账号令牌仅保存在本机
`FairyPet\` 目录。使用本程序产生的任何后果由使用者自行承担。
