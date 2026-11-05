# QtWebEngine 逐帧内存泄漏（PySide6 6.10.x）

排查记录，供后来者省一遍夜。

## 现象

桌宠开着不动，一晚上 32GB 内存被吃满。任务管理器里
`QtWebEngineProcess.exe`（`--type=renderer`）持续上涨。

## 测量

进程空闲，不操作：

| 时间 | 渲染进程 |
| --- | --- |
| 11:11:46 | 812 MB |
| 11:12:01 | 871 MB |
| 11:12:16 | 934 MB |
| 11:12:46 | 1055 MB |

约 **+59 MB / 15 秒**，即 3.6 MB/s，线性、不收敛。

## 三步定位

1. **换成一个极简页面**——只有一个 `div` 在改 `opacity` 和 `rotate`，
   没有 SVG、没有滤镜：**照样 3.6 MB/s**。所以不是项目的滤镜或动画写法。
2. **冻结 `requestAnimationFrame`**：内存立刻停在 126 MB 不动，跑 35 秒纹丝不动。
   说明是「每合成一帧漏一点」，不是缓存预热。
3. **换 Qt 版本**：同一页面、同样动画，PySide6 **6.8.3** 冲到 130 MB 后回落到
   115–120 MB 并稳定，跑 75 秒一条直线。

顺带排除：`--disable-gpu-compositing`、`--enable-gpu-rasterization`、
`--ignore-gpu-blocklist` 都试过，泄漏速率不变。

## 结论

PySide6 **6.10.3** 的 QtWebEngine 渲染进程在页面有动画时逐帧泄漏，
约 60 KB/帧。解决方式：锁 6.8.3。

```
pip install PySide6==6.8.3
```

`requirements.txt` 里已经钉死，别手滑升级。
