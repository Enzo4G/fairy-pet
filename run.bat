@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".petenv\Scripts\pythonw.exe" (
    echo   还没准备好环境，先跑 setup.bat
    pause
    exit /b 1
)

start "" ".petenv\Scripts\pythonw.exe" pet.py
