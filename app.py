import os
import re
import urllib.parse
import subprocess
import platform
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
import asyncio

app = FastAPI()

# 儲存設定的類別
class Config(BaseModel):
    save_dir: str

# 預設儲存路徑
current_save_dir = os.path.expanduser("~/Desktop/分級")
if not os.path.exists(current_save_dir):
    try:
        os.makedirs(current_save_dir)
    except:
        # Fallback for cloud environments where Desktop might not exist
        current_save_dir = "/tmp"

TARGET_BASE_URL = "https://ranking.energylabel.org.tw/product/Approval"

# Browser-like headers to avoid being blocked or getting SSL/CDN errors
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://ranking.energylabel.org.tw/product/Approval/list.aspx"
}

# Ensure static folder exists
base_path = os.path.dirname(__file__)
static_dir = os.path.join(base_path, "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")

@app.get("/")
def get_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/config")
def get_config():
    return {
        "save_dir": current_save_dir,
        "is_mac": platform.system() == "Darwin"
    }

@app.post("/api/config")
def update_config(config: Config):
    global current_save_dir
    path = os.path.expanduser(config.save_dir)
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"無法建立資料夾: {str(e)}")
    current_save_dir = path
    return {"status": "success", "save_dir": current_save_dir}

@app.post("/api/select-folder")
def select_folder():
    if platform.system() != "Darwin":
        return {"status": "error", "message": "此功能僅支援 macOS 本地執行。在雲端部署時，請直接在輸入框填寫路徑。"}
        
    script = 'POSIX path of (choose folder with prompt "請選擇儲存分級圖檔的資料夾")'
    try:
        proc = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if proc.returncode == 0:
            path = proc.stdout.strip()
            return {"status": "success", "path": path}
        else:
            return {"status": "cancelled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法開啟資料夾選擇器: {str(e)}")

async def fetch_model_info(model: str) -> dict:
    # 搜尋邏輯：落實 Type=0 和 RANK=0
    params = {
        "key2": model,
        "Type": "0",
        "RANK": "0",
        "con": "0"
    }
    query_string = urllib.parse.urlencode(params)
    list_url = f"{TARGET_BASE_URL}/list.aspx?{query_string}"
    
    # Use verify=False and custom headers to bypass SSL/Security blocks
    async with httpx.AsyncClient(verify=False, headers=DEFAULT_HEADERS, timeout=15.0) as client:
        try:
            response = await client.get(list_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 搜尋產品連結
            links = soup.find_all("a", href=re.compile(r"upt\.aspx\?.*id=\d+"))
            if not links:
                return {"status": "error", "message": "找不到該型號 (請確認型號是否正確)"}
                
            href = links[0].get("href")
            
            # 提取 p0 和 id
            p0_match = re.search(r"p0=(\d+)", href)
            id_match = re.search(r"id=(\d+)", href)
            
            if not p0_match or not id_match:
                return {"status": "error", "message": "無法解析網站參數"}
                
            p0 = p0_match.group(1)
            apply_id = id_match.group(1)
            
            # 下載圖檔
            img_url = f"{TARGET_BASE_URL}/ImgViewer.ashx?applyID={apply_id}&goodID={p0}"
            img_response = await client.get(img_url)
            img_response.raise_for_status()
            
            # 處理 Base64 圖檔
            img_html_soup = BeautifulSoup(img_response.text, 'html.parser')
            img_tag = img_html_soup.find('img')
            
            if not img_tag or not img_tag.has_attr('src') or "base64," not in img_tag['src']:
                return {"status": "error", "message": "取得圖檔失敗 (網站未回傳有效圖檔)"}
                
            base64_data = img_tag['src'].split("base64,")[1]
            import base64
            img_data = base64.b64decode(base64_data)
                
            filename = f"{model.replace('/', '_').replace(' ', '_')}.jpg"
            file_path = os.path.join(current_save_dir, filename)
            
            with open(file_path, "wb") as f:
                f.write(img_data)
                
            return {"status": "success", "message": "已下載並存檔", "path": file_path}
            
        except httpx.HTTPStatusError as e:
            # Handle specific error like 526, 403, etc.
            status_code = e.response.status_code
            msg = f"網站連線失敗 (HTTP {status_code})"
            if status_code == 526:
                msg = "網站 SSL 憑證失效 (526)，伺服器端拒絕連線"
            elif status_code == 403:
                msg = "存取被阻擋 (403)，可能 IP 被網站封鎖"
            return {"status": "error", "message": msg}
        except Exception as e:
            return {"status": "error", "message": f"執行異常: {str(e)}"}

@app.post("/api/download")
async def process_downloads(request: Request):
    data = await request.json()
    models = data.get("models", [])
    
    if not models:
        raise HTTPException(status_code=400, detail="未提供型號清單")
        
    results = []
    # 稍微增加延遲避免被封鎖
    for model in models:
        model = model.strip()
        if not model:
            continue
        res = await fetch_model_info(model)
        results.append({"model": model, "result": res})
        await asyncio.sleep(0.8)
        
    return JSONResponse(content={"results": results})

if __name__ == "__main__":
    import uvicorn
    # Use 0.0.0.0 for external access support if deployed
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
