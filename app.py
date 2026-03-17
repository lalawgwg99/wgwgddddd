import os
import re
import urllib.parse
import subprocess
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
    os.makedirs(current_save_dir)

TARGET_BASE_URL = "https://ranking.energylabel.org.tw/product/Approval"

# Ensure static folder exists
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")

@app.get("/")
def get_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/config")
def get_config():
    return {"save_dir": current_save_dir}

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
    # 搜尋邏輯：帶上 Type=0 和 RANK=0 確保搜尋全部分類與級數
    params = {
        "key2": model,
        "Type": "0",
        "RANK": "0",
        "con": "0"
    }
    query_string = urllib.parse.urlencode(params)
    list_url = f"{TARGET_BASE_URL}/list.aspx?{query_string}"
    
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(list_url, timeout=10.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 找到第一個符合的產品連結
            links = soup.find_all("a", href=re.compile(r"upt\.aspx\?.*id=\d+"))
            if not links:
                return {"status": "error", "message": "找不到該型號的分級資料 (已搜全部分類)"}
                
            href = links[0].get("href")
            
            # 提取參數
            p0_match = re.search(r"p0=(\d+)", href)
            id_match = re.search(r"id=(\d+)", href)
            
            if not p0_match or not id_match:
                return {"status": "error", "message": "無法解析產品參數"}
                
            p0 = p0_match.group(1)
            apply_id = id_match.group(1)
            
            # 下載圖檔頁面
            img_url = f"{TARGET_BASE_URL}/ImgViewer.ashx?applyID={apply_id}&goodID={p0}"
            img_response = await client.get(img_url, timeout=10.0)
            img_response.raise_for_status()
            
            # 解析 Base64
            img_html_soup = BeautifulSoup(img_response.text, 'html.parser')
            img_tag = img_html_soup.find('img')
            
            if not img_tag or not img_tag.has_attr('src') or "base64," not in img_tag['src']:
                return {"status": "error", "message": "頁面讀取成功，但圖檔碼無效"}
                
            base64_data = img_tag['src'].split("base64,")[1]
            import base64
            img_data = base64.b64decode(base64_data)
                
            file_path = os.path.join(current_save_dir, f"{model.replace('/', '_')}.jpg")
            with open(file_path, "wb") as f:
                f.write(img_data)
                
            return {"status": "success", "message": "已下載並存檔", "path": file_path}
            
        except Exception as e:
            return {"status": "error", "message": f"發生錯誤: {str(e)}"}

@app.post("/api/download")
async def process_downloads(request: Request):
    data = await request.json()
    models = data.get("models", [])
    
    if not models:
        raise HTTPException(status_code=400, detail="未提供型號清單")
        
    results = []
    for model in models:
        model = model.strip()
        if not model:
            continue
        res = await fetch_model_info(model)
        results.append({"model": model, "result": res})
        await asyncio.sleep(0.3)
        
    return JSONResponse(content={"results": results})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
