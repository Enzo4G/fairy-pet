# 精简 PyInstaller 产物：删掉这个桌宠用不到的 Qt 组件。
#
# 用法（在仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File tools\prune_dist.ps1
#
# 保留原则：QtWebEngineCore 依赖的东西一律不动。实测它的导入表里有
# Qt6Quick / Qt6Qml / Qt6Network / Qt6Positioning / Qt6Gui / Qt6Core，
# 所以这几个及 QuickTemplates2、QuickControls2 都留着。

param(
    [string]$Root = (Join-Path (Split-Path -Parent $PSScriptRoot) "dist\FairyPet")
)

$ErrorActionPreference = "Stop"
$lib = Join-Path $Root "_internal\PySide6"

if (-not (Test-Path $lib)) {
    Write-Host "  找不到 $lib，先跑 build_exe.bat"
    exit 1
}

$before = (Get-ChildItem $Root -Recurse -File | Measure-Object Length -Sum).Sum

# 1. 翻译文件：界面文案都是程序自己的，系统级翻译用不上
$dir = Join-Path $lib "translations"
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }

# 2. QML 模块：本程序是 QWidgets 套 QWebEngineView，不加载任何 QML 文档
$dir = Join-Path $lib "qml"
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }

# 3. DevTools 资源包（只在开远程调试时用）
$file = Join-Path $lib "resources\qtwebengine_devtools_resources.pak"
if (Test-Path $file) { Remove-Item $file -Force }

# 4. 完全没用到的 Qt 模块
# 不要删 Qt6WebChannel.dll（WebEngineCore 依赖它）
# 不要删 Qt6OpenGL.dll（Qt6Quick 依赖它）
$modules = @(
    "Qt6Pdf.dll", "QtPdf.pyd",
    "Qt6Quick3D.dll", "Qt6Quick3DRuntimeRender.dll", "Qt6Quick3DUtils.dll", "QtQuick3D.pyd",
    "Qt63DCore.dll", "Qt63DRender.dll", "Qt63DAnimation.dll", "Qt63DExtras.dll", "Qt3DCore.pyd",
    "Qt6Graphs.dll", "Qt6Charts.dll", "Qt6DataVisualization.dll",
    "Qt6Location.dll", "Qt6PositioningQuick.dll", "Qt6Sql.dll", "Qt6Test.dll",
    "Qt6Designer.dll", "Qt6UiTools.dll", "Qt6Help.dll", "Qt6Multimedia.dll", "Qt6MultimediaWidgets.dll",
    "Qt6TextToSpeech.dll", "Qt6SerialPort.dll"
    "QtOpenGL.pyd", "QtOpenGLWidgets.pyd", "QtPdfWidgets.pyd", "QtCharts.pyd", "QtDataVisualization.pyd",
    "QtMultimedia.pyd", "QtMultimediaWidgets.pyd", "QtQuick3D.pyd", "QtSql.pyd", "QtTest.pyd",
    "QtDesigner.pyd", "QtUiTools.pyd", "QtHelp.pyd", "QtWebSockets.pyd"
)
$removed = 0
foreach ($name in $modules) {
    $path = Join-Path $lib $name
    if (Test-Path $path) { Remove-Item $path -Force; $removed++ }
}

$after = (Get-ChildItem $Root -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("  精简：{0:N0} MB -> {1:N0} MB（省 {2:N0} MB，删掉 {3} 个模块）" -f ($before / 1MB), ($after / 1MB), (($before - $after) / 1MB), $removed)
