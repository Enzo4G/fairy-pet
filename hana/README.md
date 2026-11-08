# Fairy 桌宠（HanaAgent 版）

同一个桌宠，另一条后端：不是接 dsh，而是作为 [HanaAgent](https://openhanako.com) 的
App 存在，通过 Hana 的本地服务（`~/.hanako/server-info.json` 里的端口 + App 路由）
读写会话、切换模型、发消息。

## 和根目录的 dsh 版有什么不同

| | dsh 版（根目录） | HanaAgent 版（本目录） |
| --- | --- | --- |
| 后端 | `127.0.0.1:<port>/api/*`，自己签 cookie | Hana 本地服务 + App 路由 |
| 前提 | 运行中的 dsh 客户端 | 运行中的 HanaAgent |
| 单实例互斥名 | `Global\FairyPetDshSingleInstance` | `Global\FairyPetSingleInstance` |
| 配置目录 | `FairyPet\`（与本文件同级） | 同左，两份互不干扰，可同时运行 |
| 输入区 | dsh 风格（工作区 / 模式 / 权限 / 模型） | Hana 风格（会话下拉 / 模型 / 思考强度） |
| 新建对话 | 小窗里可以直接开新对话 | **没有这个按钮**，新对话请在 Hana 客户端里开 |

### 为什么 Hana 版没有「新建对话」

Hana 的会话列表由**客户端**自己维护，外部进程建出来的会话不会实时出现在侧栏
（实测：数据层 18 条，客户端侧栏还是那 3 条，切到前台也不刷新），而 SDK 里
没有任何让外部进程把会话「塞进」列表、或让客户端切过去的接口。

所以在小窗里做这个按钮只会产生一堆看不见的空会话。打开小窗的右上角只留了
会话下拉和关闭；要开新对话去 Hana 里点「新对话」，然后在桌宠的下拉里选中它即可。

形象、配色、动效、托盘、拖拽、缩放、置顶、余额栏完全一致；动画的调参与
联动逻辑（速度跟 CPU/显卡/手动、眼皮跟 CPU/显卡/内存、执行任务时随机软眨眼）
两边是同一套代码。

## 运行

**推荐：直接用打包好的。** 从 [Releases](../../releases) 下载
`Fairy-Hana-v2.0.5-win64.zip`，解压后双击 `FairyHana.exe`。不需要装 Python。

从源码跑（环境与 dsh 版共用，装一次即可）：

```bat
..\setup.bat
..\.petenv\Scripts\pythonw.exe pet.py
```

自己重新打包：

```bat
build_exe.bat
```

产物在 `dist\FairyHana\`，会自动调 `..\tools\prune_dist.ps1` 精简并改名渲染进程。

关闭时注意：**同一时间只跑一个**。两个版本互斥名不同，可以同时开，但两张脸会
叠在一起。

## 它不是 Hana App 本体

Hana App 那层壳（`manifest.json` + `index.js`，负责在 Hana 里拉进程、给权限）
依赖 HanaAgent 自带的 App SDK，**没有随本仓库分发**。想做成真正的 App，
用 Hana 的 `hana-app-creator` 技能照着 `index.js` 的结构自己搭一份；
本目录只提供 App 会拉起的那支 `pet.py`。

> App 体里的自动拉起已经默认关掉（由 `pet.autostart` 开关控制，存 `"1"` 才回到旧行为），
> 不然它会跟这个 exe 同时拉起两只脸。现在开机自启由桌宠自己管，见右键菜单。
