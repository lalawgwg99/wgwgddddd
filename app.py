import base64
import os
import re
import subprocess
import platform
import urllib3
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
import asyncio

# 抑制 SSL 憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Config(BaseModel):
    save_dir: str

# 預設儲存路徑
current_save_dir = os.path.expanduser("~/Desktop/分級")
os.makedirs(current_save_dir, exist_ok=True)

TARGET_BASE_URL = "https://ranking.energylabel.org.tw/product/Approval"

# 模擬瀏覽器 Headers，避免被擋
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    "Cache-Control": "no-cache",
}

# Static files
base_path = os.path.dirname(__file__)
static_dir = os.path.join(base_path, "static")
os.makedirs(static_dir, exist_ok=True)

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
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"無法建立資料夾: {str(e)}")
    current_save_dir = path
    return {"status": "success", "save_dir": current_save_dir}


@app.post("/api/select-folder")
def select_folder():
    """macOS 原生 Finder 資料夾選擇對話框"""
    if platform.system() != "Darwin":
        return {"status": "error", "message": "此功能僅支援 macOS"}

    script = 'POSIX path of (choose folder with prompt "請選擇儲存分級圖檔的資料夾")'
    try:
        proc = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=60
        )
        if proc.returncode == 0:
            path = proc.stdout.strip()
            # 同步更新後端儲存路徑
            global current_save_dir
            current_save_dir = path
            return {"status": "success", "path": path}
        else:
            return {"status": "cancelled"}
    except subprocess.TimeoutExpired:
        return {"status": "cancelled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法開啟資料夾選擇器: {str(e)}")


async def search_model_two_step(client: httpx.AsyncClient, model: str) -> list:
    """
    兩步驟 ASP.NET 搜尋：
    Step 1: GET list.aspx → 取得 __VIEWSTATE 等隱藏欄位 + 偵測下拉選單名稱
    Step 2: POST 表單，產品類別=全部、分級=全部、關鍵字=型號
    """
    list_url = f"{TARGET_BASE_URL}/list.aspx"

    # --- Step 1: GET 頁面，取得 ASP.NET 表單狀態 ---
    try:
        page_resp = await client.get(
            list_url,
            headers={**DEFAULT_HEADERS, "Referer": list_url},
            timeout=15.0
        )
        page_resp.raise_for_status()
    except Exception:
        # GET 失敗，直接跳到備用簡單搜尋
        return await simple_get_search(client, model)

    page_html = page_resp.text
    soup = BeautifulSoup(page_html, "html.parser")

    # 收集 ASP.NET 隱藏欄位（__VIEWSTATE, __EVENTVALIDATION 等）
    post_data = {}
    for hidden in soup.find_all("input", {"type": "hidden"}):
        name = hidden.get("name")
        value = hidden.get("value", "")
        if name:
            post_data[name] = value

    # 偵測所有 <select> 名稱，設為空字串（=全部）
    for sel in soup.find_all("select"):
        name = sel.get("name")
        if name:
            post_data[name] = ""   # 空值代表選「全部」

    # 偵測關鍵字輸入框
    keyword_field = None
    for inp in soup.find_all("input", {"type": "text"}):
        name = inp.get("name", "")
        inp_id = inp.get("id", "").lower()
        if any(k in name.lower() or k in inp_id for k in ["key", "search", "query", "keyword", "txt", "model"]):
            keyword_field = name
            break
    if not keyword_field:
        all_text = soup.find_all("input", {"type": "text"})
        if all_text:
            keyword_field = all_text[0].get("name")

    if keyword_field:
        post_data[keyword_field] = model

    # 偵測送出按鈕
    for btn in soup.find_all("input", {"type": "submit"}):
        name = btn.get("name")
        value = btn.get("value", "搜尋")
        if name:
            post_data[name] = value
            break

    # --- Step 2: POST 搜尋 ---
    try:
        search_resp = await client.post(
            list_url,
            data=post_data,
            headers={
                **DEFAULT_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": list_url,
            },
            timeout=20.0
        )
        search_resp.raise_for_status()
        result_soup = BeautifulSoup(search_resp.text, "html.parser")
        links = result_soup.find_all("a", href=re.compile(r"upt\.aspx\?.*id=\d+"))
        if links:
            return links
    except Exception:
        pass

    # --- 備用：簡單 GET 搜尋 ---
    return await simple_get_search(client, model)


async def simple_get_search(client: httpx.AsyncClient, model: str) -> list:
    """備用方案：GET 帶全部類別參數"""
    # 嘗試不同的參數組合
    param_sets = [
        {"key2": model},                                              # 最簡單
        {"key2": model, "Type": "", "RANK": "", "con": ""},          # 空字串=全部
        {"key2": model, "Type": "0", "RANK": "0"},                   # 0=全部
    ]
    for params in param_sets:
        try:
            url = f"{TARGET_BASE_URL}/list.aspx?" + "&".join(f"{k}={v}" for k, v in params.items())
            resp = await client.get(url, headers=DEFAULT_HEADERS, timeout=15.0)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.find_all("a", href=re.compile(r"upt\.aspx\?.*id=\d+"))
            if links:
                return links
        except Exception:
            continue
    return []


async def fetch_model_info(model: str) -> dict:
    """主要執行流程：搜尋 → 解析連結 → 下載圖檔 → 存檔"""
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        try:
            # 搜尋（兩步驟 ASP.NET POST，附備用 GET）
            links = await search_model_two_step(client, model)

            if not links:
                return {"status": "error", "message": "找不到該型號（官網搜尋無結果，請確認型號）"}

            href = links[0].get("href", "")
            p0_match = re.search(r"p0=(\d+)", href)
            id_match = re.search(r"id=(\d+)", href)

            if not p0_match or not id_match:
                return {"status": "error", "message": "無法解析網站產品連結參數"}

            p0 = p0_match.group(1)
            apply_id = id_match.group(1)

            # 下載圖檔頁面
            img_url = f"{TARGET_BASE_URL}/ImgViewer.ashx?applyID={apply_id}&goodID={p0}"
            img_resp = await client.get(
                img_url,
                headers={**DEFAULT_HEADERS, "Referer": f"{TARGET_BASE_URL}/list.aspx"},
                timeout=20.0
            )
            img_resp.raise_for_status()

            # 解析 base64 圖片
            img_soup = BeautifulSoup(img_resp.text, "html.parser")
            img_tag = img_soup.find("img")

            if not img_tag or not img_tag.has_attr("src") or "base64," not in img_tag["src"]:
                return {"status": "error", "message": "取得圖檔失敗（網站未回傳有效圖檔）"}

            b64 = img_tag["src"].split("base64,")[1].strip()
            if len(b64) < 100:
                return {"status": "error", "message": "圖檔資料異常（過小）"}

            img_data = base64.b64decode(b64)

            # 儲存檔案
            safe_name = re.sub(r'[<>:"/\\|?*\s]', '_', model)
            file_path = os.path.join(current_save_dir, f"{safe_name}.jpg")
            with open(file_path, "wb") as f:
                f.write(img_data)

            return {"status": "success", "message": "已下載並存檔", "path": file_path}

        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            msgs = {526: "網站 SSL 憑證失效 (526)", 403: "存取被阻擋 (403)"}
            return {"status": "error", "message": msgs.get(code, f"HTTP 錯誤 {code}")}
        except Exception as e:
            return {"status": "error", "message": f"執行異常: {str(e)}"}


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
        await asyncio.sleep(0.8)  # 避免被網站封鎖

    return JSONResponse(content={"results": results})


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="127.0.0.1", port=port)
