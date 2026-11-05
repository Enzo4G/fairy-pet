# 第三方素材与依赖说明

本项目的形象设定、页面结构与动画驱动逻辑参考并改写了下列开源项目。
按 Apache License 2.0 的要求，此文件记录来源、版权与改动。

## Chengzhibense/Fairy-DSH

- 来源：https://github.com/Chengzhibense/Fairy-DSH
- 许可：Apache License 2.0
- 版权：Copyright Chengzhibense 及该项目贡献者
- 本项目涉及的衍生文件：
  - `assets/web/fairy.html`
  - `assets/web/mascot.css`
  - `assets/web/overrides.css`
  - `assets/web/pet-driver.js`
  - `assets/icon.png`、`assets/npc_fairy.webp`（形象参考）
- 改动说明：
  - 动画参数重整（脉动周期、涟漪与故障节奏独立成曲线）
  - 新增随系统负载联动的速度与眼皮控制、随机微眨眼
  - 页面与宿主程序之间的指令通道（`window.pet`）按本项目的接口重写
  - 移除原项目中本项目未使用的部分

Apache License 2.0 全文见 <https://www.apache.org/licenses/LICENSE-2.0>。

## 运行时依赖

| 组件 | 版本 | 许可 |
| --- | --- | --- |
| PySide6 (Qt for Python) | 6.8.3（锁定，见下） | LGPL-3.0 / Qt 商业许可 |
| Qt 6 WebEngine | 随 PySide6 | LGPL-3.0 |
| Python | 3.9+ | PSF License |

> PySide6 必须锁 6.8.3。6.10.x 的 QtWebEngine 渲染进程在页面有动画时
> 会以约 3.6 MB/s 泄漏内存，挂一夜能吃掉几十 GB，故不作升级。

## 与本项目通信的软件

本程序通过本机接口与 **DeepSeek Harness (dsh)** 客户端通信，
不包含、不分发该客户端的任何代码或资源。DeepSeek 与 dsh 的相关权利
归其各自权利人所有。
