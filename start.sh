#!/bin/bash
set -e

# MineBoard - Startup Script
# Minecraft Server Dashboard

echo "🚀 Starting MineBoard Dashboard..."
echo "=================================="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Install Python3 to continue."
    exit 1
fi

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 not found. Install pip3 to continue."
    exit 1
fi

echo "Creating venv..."
echo "=================================="
python3 -m venv mineboard
source mineboard/bin/activate

# Install dependencies if needed
echo "📦 Checking dependencies..."
pip3 install -r requirements.txt

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p servers logs uploads

# Start the application
echo "🌐 Starting web server on port 8999..."
echo "=================================="
echo "Open your browser and go to: http://localhost:8999"
echo "=================================="
echo "Press Ctrl+C to stop the server"
echo ""

python3 app.py
