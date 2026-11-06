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
- **贴边隐藏**：把鼠标拖到屏幕边缘松手（四条边都行，判定看鼠标位置，不看宠物离边缘多远），
  身体滑出去只留本体的 1/10；鼠标停上去露 1/3；按住可以把它拖出来，原地松手才弹回去。
- **丢不了**：改分辨率、拔掉副屏、拖出边界，只要还剩不到 1/3 在屏幕里就会被拉回来，
  不会出现「知道它在跑但找不到脸」的尴尬。
- **开机自启**：右键菜单里一勾即开。写的是 `HKCU` 的 Run 项，不建计划任务、不往启动文件夹放东西；
  任务管理器的「启动」页能直接看到并禁用。搬家后路径对不上时菜单会自动显示为未开启。
- **托盘即控制台**：拖拽缩放、附件拖入、会话切换、模型与思考强度、余额与用量。

## 快速开始

### 方式一：下载 exe（推荐给普通用户）

到 [Releases](../../releases) 下载 `Fairy-v2.0.0-win64.zip`，解压后双击 `Fairy.exe`。
无需安装 Python；配置会写在与 exe 同级的 `FairyPet\` 目录里。

> 首次启动会向系统申请网络访问（本机 127.0.0.1），用于和 dsh 通信。
>
> HanaAgent 版单独一个包：`Fairy-Hana-v2.0.0-win64.zip`，解压后双击 `FairyHana.exe`，
> 前提是本机的 HanaAgent 里装着 fairy-pet 这个 App。

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
贴边隐藏
开机自启
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
| `FairyPet\config.json` | 尺寸、置顶、贴边隐藏、速度与眯眼的联动方式、主题 |
| `FairyPet\state.json` | 窗口位置（贴边时记的是藏起来之前的位置） |
| `FairyPet\deepseek.json` | DeepSeek 控制台令牌（仅本机，登录后才有） |
| `FairyPet\web\` | 登录会话的 cookie 与缓存 |

整个目录就是全部安装：换电脑拷走文件夹即可，不需要注册表、不需要 `%APPDATA%`。

## 自己打包 exe

```bat
setup.bat
build_exe.bat
```

产物在 `dist\Fairy\`，打包脚本会接着调 `tools\prune_dist.ps1` 删掉用不到的
Qt 组件（翻译、QML 模块、3D / Charts / Pdf 等），400MB → 291MB。
整个目录一起分发（`Fairy.exe` 依赖同级的 `_internal\`，这是 Qt WebEngine
的常规形态，单文件模式启动会慢十几秒且容易被杀软误伤）。

> 改精简清单时注意：`Qt6WebChannel.dll` 是 WebEngineCore 的硬依赖，
> `Qt6OpenGL.dll` 是 Qt6Quick 的硬依赖，删了程序会直接起不来（无窗口、无报错）。
>
> 渲染进程改名靠 `FairyHelper.exe` + `QTWEBENGINEPROCESS_PATH`，但原名的
> `QtWebEngineProcess.exe` 副本**不能删**（1MB）：只留改名后的文件时，Qt 找不到
> 默认路径下的 helper 就干脆不启动渲染进程——窗口全黑、stderr 一句不嘽。

## 在任务管理器里长什么样

exe 叫 `Fairy.exe`，版本资源里 FileDescription / ProductName 都是 `Fairy`，
所以任务管理器里它的描述也是 Fairy，而不是一堆 `FairyPet`。

Qt WebEngine 会拉起一个渲染子进程，原本读作 `QtWebEngineProcess.exe`。打包时
把它复制成 `FairyHelper.exe` 并用 `QTWEBENGINEPROCESS_PATH` 指过去，于是它会
显示为 Fairy 名下的 `FairyHelper`。两个都启动后大概这个样子：

```
Fairy            306 MB
└─ FairyHelper   117 MB
```

主进程 300MB、渲染进程 120MB 左右是正常水位（Chromium 内核）。

## 已知问题

- **PySide6 不要升到 6.10.x**：该版本 QtWebEngine 渲染进程在页面有动画时以约
  **3.6 MB/s** 泄漏内存，挂一夜能吃掉几十 GB。6.8.3 实测稳定在 120MB 左右不动。
  排查记录：[docs/memory-leak.md](docs/memory-leak.md)。
- 权限按钮可切：跟客户端一样发 `/permission <preset>`（仅可查看 / 工作区内修改 / 完全权限）。
  「模式」只能在对话第一条消息之前选，已经开始的会话 dsh 会拒绝——小窗把原因写在提示行。
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
