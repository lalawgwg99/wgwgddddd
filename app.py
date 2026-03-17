import base64
import os
import re
import urllib.parse
import warnings
import urllib3
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import httpx
from bs4 import BeautifulSoup
import asyncio

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 儲存圖片的目標資料夾（預設）
DEFAULT_SAVE_DIR = os.path.expanduser("~/Desktop/分級")
CURRENT_SAVE_DIR = DEFAULT_SAVE_DIR

if not os.path.exists(CURRENT_SAVE_DIR):
    os.makedirs(CURRENT_SAVE_DIR)

TARGET_BASE_URL = "https://ranking.energylabel.org.tw/product/Approval"

# Ensure static folder exists
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")

@app.get("/")
def get_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/get-path")
async def get_path():
    """Get current save path"""
    return JSONResponse(content={"path": CURRENT_SAVE_DIR})

@app.post("/api/set-path")
async def set_path(request: Request):
    """Set custom save path"""
    try:
        data = await request.json()
        new_path = data.get("path", "").strip()

        if not new_path:
            raise HTTPException(status_code=400, detail="未提供路徑")

        # Expand ~ to home directory
        new_path = os.path.expanduser(new_path)

        # Create directory if it doesn't exist
        try:
            os.makedirs(new_path, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"無法建立目錄: {str(e)}")

        global CURRENT_SAVE_DIR
        CURRENT_SAVE_DIR = new_path

        return JSONResponse(content={
            "status": "success",
            "message": "路徑已設定",
            "path": CURRENT_SAVE_DIR
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"設定路徑失敗: {str(e)}")

async def fetch_model_info(model: str, save_path: str = None) -> dict:
    """Fetch model info and save image"""
    if save_path is None:
        save_path = CURRENT_SAVE_DIR

    list_url = f"{TARGET_BASE_URL}/list.aspx?key2={urllib.parse.quote(model)}"

    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(list_url, timeout=10.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find the first product link
            # Pattern: upt.aspx?&key2={model}...&p0=119769&id=33531
            links = soup.find_all("a", href=re.compile(r"upt\.aspx\?.*id=\d+"))
            if not links:
                return {"status": "error", "message": "找不到該型號的分級資料"}

            href = links[0].get("href")

            # Extract p0 and id
            p0_match = re.search(r"p0=(\d+)", href)
            id_match = re.search(r"id=(\d+)", href)

            if not p0_match or not id_match:
                return {"status": "error", "message": "無法解析產品編號與身分ID"}

            p0 = p0_match.group(1)
            apply_id = id_match.group(1)

            # Download Image
            img_url = f"{TARGET_BASE_URL}/ImgViewer.ashx?applyID={apply_id}&goodID={p0}"
            img_response = await client.get(img_url, timeout=10.0)
            img_response.raise_for_status()

            # Evaluate the returned ImgViewer.ashx
            # It actually returns an HTML page with a base64 image: <img src="data:image/jpeg;base64,/9j/4AA... "/>
            img_html_soup = BeautifulSoup(img_response.text, 'html.parser')
            img_tag = img_html_soup.find('img')

            if not img_tag or not img_tag.has_attr('src') or "base64," not in img_tag['src']:
                return {"status": "error", "message": "無法從該產品頁面取得標章圖檔"}

            base64_data = img_tag['src'].split("base64,")[1]
            img_data = base64.b64decode(base64_data)

            file_path = os.path.join(save_path, f"{model.replace('/', '_')}.jpg")
            with open(file_path, "wb") as f:
                f.write(img_data)

            return {"status": "success", "message": "已下載並存檔", "path": file_path}

        except httpx.HTTPStatusError as e:
            return {"status": "error", "message": f"網站連線失敗 (HTTP {e.response.status_code})"}
        except Exception as e:
            return {"status": "error", "message": f"發生錯誤: {str(e)}"}

@app.post("/api/download")
async def process_downloads(request: Request):
    """Process downloads with optional custom save path"""
    try:
        data = await request.json()
        models = data.get("models", [])
        save_path = data.get("save_path", CURRENT_SAVE_DIR)

        if not models:
            raise HTTPException(status_code=400, detail="未提供型號清單")

        results = []
        # Process up to 5 concurrent downloads to avoid overwhelming the server
        for model in models:
            model = model.strip()
            if not model:
                continue
            res = await fetch_model_info(model, save_path)
            results.append({"model": model, "result": res})
            await asyncio.sleep(0.5) # Be polite

        return JSONResponse(content={"results": results})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"處理失敗: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
