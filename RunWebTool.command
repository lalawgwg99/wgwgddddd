#!/bin/bash
# MacOS Run Script for Energy Label Web Tool

# Get the script direction
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "======================================"
echo "    啟動 Energy Label Saver..."
echo "======================================"

# Check for Python 3
if ! command -v python3 &> /dev/null
then
    echo "錯誤: 系統未安裝 Python 3"
    exit 1
fi

# Setup Virtual Environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "初始化虛擬環境並安裝相依套件 (這只需要執行一次)..."
    python3 -m venv venv
    source venv/bin/activate
    pip install "fastapi[all]" httpx beautifulsoup4 uvicorn > /dev/null 2>&1
else
    source venv/bin/activate
fi

# Start the server in the background
echo "正在啟動本地伺服器..."
python3 app.py &
SERVER_PID=$!

# Wait a moment for server to start
sleep 2

# Open Safari or default browser
echo "正在開啟瀏覽器..."
open "http://localhost:8000"

# Keep Terminal open until user stops
echo ""
echo "伺服器執行中！如需關閉程式，請直接關閉此終端機視窗，或按下 Ctrl+C。"
echo "======================================"

trap "kill $SERVER_PID; exit" INT TERM
wait $SERVER_PID
