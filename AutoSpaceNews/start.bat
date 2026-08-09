@echo off
title AutoSpaceNews

echo ================================================
echo   AutoSpaceNews (ASN) - Starting...
echo ================================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Install dependencies
echo [1/2] Installing dependencies...
pip install -r requirements.txt --quiet

REM Start service
echo [2/2] Starting service...
echo.
python asn_main.py

pause
