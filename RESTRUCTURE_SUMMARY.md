# Energy Label Saver 重構完成

## 修改的檔案

### 1. app.py (本地 FastAPI 後端)
**修復和改進：**
- ✅ 將 `import base64` 移到檔案頂部（第1行）
- ✅ 加入 SSL 警告抑制：
  ```python
  import warnings
  import urllib3
  urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
  ```
- ✅ 新增 `/api/get-path` GET endpoint - 取得目前儲存路徑
- ✅ 新增 `/api/set-path` POST endpoint - 設定自訂儲存路徑
- ✅ 修改 `/api/download` endpoint 以接受可選的 `save_path` 參數
- ✅ 新增 CORS middleware 支持跨域請求
- ✅ 改進錯誤處理（HTTPException 處理）
- ✅ 全局變數 `CURRENT_SAVE_DIR` 用於動態路徑管理

### 2. static/index.html (本地模式前端)
**新功能：**
- ✅ 新增「儲存路徑」區塊（Apple HIG 風格）
  - 顯示目前儲存路徑
  - 文字輸入框輸入自訂路徑
  - 「變更路徑」按鈕
- ✅ 自動偵測部署模式（localhost vs 雲端）
- ✅ 本地模式顯示路徑選擇，雲端模式隱藏
- ✅ 改進的樣式和使用者體驗

### 3. public/index.html (雲端模式前端)
**特性：**
- ✅ 隱藏路徑選擇功能（雲端無法存檔）
- ✅ 觸發瀏覽器下載機制（blob + download attribute）
- ✅ 自動將 base64 圖檔轉換為 blob 並下載
- ✅ 檔案自動命名為「型號.jpg」

### 4. functions/api/download.js (Cloudflare Worker)
**功能：**
- ✅ POST endpoint 接收 `{ models: [...] }`
- ✅ 對每個型號 fetch 台灣能源署 list.aspx 和 ImgViewer.ashx
- ✅ 使用 `node-html-parser` 解析 HTML 和提取 base64
- ✅ 回傳 JSON `{ results: [{ model, status, imageData }] }`
- ✅ CORS 支持
- ✅ 錯誤處理和服務端延遲控制

### 5. wrangler.toml
- ✅ Cloudflare Pages 部署設定
- ✅ 兼容日期：2024-01-15
- ✅ 支持 Node modules

### 6. package.json
- ✅ 項目元資料
- ✅ 依賴：node-html-parser 7.1.0+
- ✅ 開發依賴：wrangler 3.0.0+
- ✅ 部署和開發腳本

### 7. requirements.txt
- ✅ Python 依賴列表（fastapi, uvicorn, httpx, beautifulsoup4）
- ✅ 固定版本確保相容性

### 8. RunWebTool.command
- ✅ 更新的 macOS 啟動腳本
- ✅ 自動虛擬環境設定
- ✅ Python 3 依賴檢查

### 9. .gitignore
- ✅ Python 和 Node 相關檔案
- ✅ IDE 設定檔
- ✅ Cloudflare 工作目錄
- ✅ 環境變數檔案

## 架構概覽

```
EnergyLabelWebScript/
├── app.py                          # 本地 FastAPI 後端
├── static/
│   └── index.html                  # 本地模式前端（含路徑選擇）
├── public/
│   └── index.html                  # 雲端模式前端（瀏覽器下載）
├── functions/
│   └── api/
│       └── download.js             # Cloudflare Worker
├── RunWebTool.command              # macOS 啟動腳本
├── wrangler.toml                   # Cloudflare 設定
├── package.json                    # Node 依賴
├── requirements.txt                # Python 依賴
└── .gitignore                      # Git 忽略規則
```

## 部署模式

### 本地模式（localhost）
1. 執行 `RunWebTool.command` 或 `python3 app.py`
2. 開啟 http://localhost:8000
3. 可選擇儲存路徑
4. 圖檔存檔到指定目錄

### 雲端模式（Cloudflare Pages）
1. 部署到 Cloudflare Pages
2. Cloudflare Worker 處理 API 請求
3. 前端自動偵測並隱藏路徑選擇
4. 圖檔通過瀏覽器下載機制 (blob URL)
5. 無需在伺服器上存檔

## 主要改進

1. **模式自動偵測** - 根據 hostname 自動切換本地/雲端模式
2. **路徑管理** - 本地模式支持動態設定儲存路徑
3. **CORS 支持** - 支持跨域請求（雲端部署）
4. **SSL 警告抑制** - 避免控制台警告信息
5. **瀏覽器下載** - 雲端模式使用標準 blob 下載
6. **錯誤處理** - 改進的錯誤訊息和例外處理

## 使用說明

### 啟動本地模式
```bash
bash RunWebTool.command
# 或
python3 app.py
```

### 部署到 Cloudflare
```bash
npm install
wrangler login
wrangler deploy
```

## 注意事項

- 本地模式完全可用，保留所有原始功能
- 雲端模式使用 Cloudflare Worker 作為 proxy
- 自動偵測機制確保無縫切換
- 所有依賴已明確列出（requirements.txt, package.json）
