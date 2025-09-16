@echo off
title MineBoard - Startup Script
echo 🚀 Starting MineBoard Dashboard...
echo ==================================

:: Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ Python not found. Install Python 3 to continue.
    pause
    exit /b
)

:: Check if pip is installed
where pip >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ pip not found. Install pip to continue.
    pause
    exit /b
)

echo Creating venv...
echo ==================================
python -m venv mineboard

:: Activate virtual environment
call mineboard\Scripts\activate.bat

:: Install dependencies
echo 📦 Checking dependencies...
pip install -r requirements.txt

:: Create necessary directories
echo 📁 Creating directories...
if not exist servers mkdir servers
if not exist logs mkdir logs
if not exist uploads mkdir uploads

:: Start the application
echo 🌐 Starting web server on port 8999...
echo ==================================
echo Open your browser and go to: http://localhost:8999
echo ==================================
echo Press Ctrl+C to stop the server
echo.

python app.py
pause
