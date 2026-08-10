@echo off
title ASN - Build EXE

echo ================================================
echo   AutoSpaceNews - EXE Builder
echo ================================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

REM Install PyInstaller if needed
echo [1/3] Checking PyInstaller...
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo       Installing PyInstaller...
    pip install pyinstaller --quiet
)

REM Install project dependencies
echo [2/3] Installing dependencies...
pip install -r requirements.txt --quiet

REM Build EXE
echo [3/3] Building EXE (this may take a few minutes)...
echo.

pyinstaller --noconfirm --onefile --console ^
    --name "AutoSpaceNews" ^
    --add-data "static;static" ^
    --add-data "requirements.txt;." ^
    --hidden-import uvicorn.logging ^
    --hidden-import uvicorn.loops ^
    --hidden-import uvicorn.loops.auto ^
    --hidden-import uvicorn.protocols ^
    --hidden-import uvicorn.protocols.http.auto ^
    --hidden-import uvicorn.protocols.websockets.auto ^
    --hidden-import uvicorn.lifespan.on ^
    --hidden-import asn_fetchers ^
    --hidden-import asn_fetchers.asn_rss ^
    --hidden-import asn_fetchers.asn_bidding ^
    --hidden-import asn_fetchers.asn_snapi ^
    --hidden-import asn_fetchers.asn_sina ^
    --collect-all feedparser ^
    --collect-all pystray ^
    asn_main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed. Check error messages above.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Build complete!
echo   EXE location: dist\AutoSpaceNews.exe
echo.
echo   You can copy dist\AutoSpaceNews.exe to your
echo   desktop as a shortcut.
echo   Note: The exe still needs to be run from the
echo   project directory (or copy the entire folder).
echo ================================================
echo.
pause
