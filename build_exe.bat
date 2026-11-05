@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".petenv\Scripts\python.exe" (
    echo   还没准备好环境，先跑 setup.bat
    pause
    exit /b 1
)

echo   安装打包工具 PyInstaller ...
".petenv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check pyinstaller
if errorlevel 1 goto :fail

echo   清理旧的产物 ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo   开始打包（Qt WebEngine 体积大，几分钟）...
".petenv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm --clean --windowed --noupx ^
    --name Fairy ^
    --icon "assets\fairy.ico" ^
    --version-file Fairy.version ^
    --add-data "assets;assets" ^
    --hidden-import PySide6.QtWebEngineWidgets ^
    --hidden-import PySide6.QtWebEngineCore ^
    pet.py
if errorlevel 1 goto :fail

if not exist "dist\Fairy\Fairy.exe" goto :fail

echo   精简产物（删掉用不到的 Qt 组件，顺便把渲染进程改名）...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\prune_dist.ps1"
if errorlevel 1 goto :fail

echo.
echo   完成：dist\Fairy\Fairy.exe
echo   整个 dist\Fairy 目录一起分发（exe 依赖同级的 _internal\）。
echo.
pause
exit /b 0

:fail
echo.
echo   [错误] 打包失败，往上翻看 PyInstaller 的输出。
echo.
pause
exit /b 1
