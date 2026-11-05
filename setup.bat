@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   Fairy 桌宠 - 环境准备
echo   =====================
echo.

rem ---- 1. 找一个可用的 Python -------------------------------------------
set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%v in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%v"
)
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 (
        for /f "delims=" %%v in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%v"
    )
)
if not defined PYEXE goto :nopython

for /f "delims=" %%v in ('"!PYEXE!" -c "import sys;print('%%d.%%d'%%sys.version_info[:2])"') do set "PYVER=%%v"
echo   [1/3] 找到 Python !PYVER!  ->  !PYEXE!

rem ---- 2. 建虚拟环境 -----------------------------------------------------
if exist ".petenv\Scripts\python.exe" (
    echo   [2/3] 虚拟环境已存在，跳过创建
) else (
    echo   [2/3] 创建虚拟环境 .petenv ...
    "!PYEXE!" -m venv .petenv
    if errorlevel 1 goto :venvfail
)

rem ---- 3. 装依赖 ---------------------------------------------------------
echo   [3/3] 安装依赖，约 500MB，第一次会慢一点 ...
".petenv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
if errorlevel 1 goto :pipfail
".petenv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto :pipfail

rem ---- 自检 --------------------------------------------------------------
".petenv\Scripts\python.exe" -c "import PySide6, PySide6.QtWebEngineWidgets; print('      PySide6', PySide6.__version__)"
if errorlevel 1 goto :pipfail

echo.
echo   环境就绪。双击 run.bat 启动，或直接执行：
echo     .petenv\Scripts\pythonw.exe pet.py
echo.
pause
exit /b 0

:nopython
echo.
echo   [错误] 没找到 Python。
echo   请先安装 Python 3.9 或更高版本： https://www.python.org/downloads/
echo   安装时务必勾选 "Add python.exe to PATH"。
echo.
pause
exit /b 1

:venvfail
echo.
echo   [错误] 创建虚拟环境失败。常见原因：杀毒软件拦截、D 盘只读、Python 安装残缺。
echo   可以手动执行： "!PYEXE!" -m venv .petenv
echo.
pause
exit /b 1

:pipfail
echo.
echo   [错误] 依赖安装失败。检查网络或代理后重跑本脚本：
echo     .petenv\Scripts\python.exe -m pip install -r requirements.txt
echo.
pause
exit /b 1
