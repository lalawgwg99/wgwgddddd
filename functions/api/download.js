/**
 * Cloudflare Pages Function - Energy Label Saver
 *
 * 526 SSL 修復說明：
 * Cloudflare Worker 的 fetch() 無法跳過 SSL 驗證。
 * 解決方案：優先使用 HTTP（無 SSL），同時告訴 CF 略過憑證錯誤。
 */

// 優先嘗試 HTTP，因為 CF Workers 無法忽略無效 SSL 憑證 (526)
const TARGET_HTTP  = "http://ranking.energylabel.org.tw/product/Approval";
const TARGET_HTTPS = "https://ranking.energylabel.org.tw/product/Approval";

const BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    "Cache-Control": "no-cache",
};

const CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
};

// 嘗試帶 CF 選項的 fetch（允許較舊 TLS、跳過不安全連線）
async function cfFetch(url, options = {}) {
    const cfOptions = {
        ...options,
        cf: {
            // 告訴 Cloudflare 對這個 fetch 放寬 SSL 要求
            minTLSVersion: "TLSv1",
            ...(options.cf || {})
        }
    };
    return fetch(url, cfOptions);
}

// 自動切換 HTTP/HTTPS 嘗試
async function robustFetch(path, options = {}) {
    const urls = [
        TARGET_HTTP  + path,   // 先試 HTTP（避開 SSL 問題）
        TARGET_HTTPS + path,   // 再試 HTTPS
    ];
    let lastError = null;
    for (const url of urls) {
        try {
            const resp = await cfFetch(url, {
                ...options,
                headers: { ...BROWSER_HEADERS, ...(options.headers || {}) }
            });
            if (resp.ok) return resp;
            if (resp.status === 526 || resp.status === 525) continue; // SSL 問題，換另一個
            return resp; // 其他狀態碼直接回傳
        } catch (e) {
            lastError = e;
        }
    }
    throw lastError || new Error("All fetch attempts failed");
}

function extractHiddenFields(html) {
    const fields = {};
    const re = /<input[^>]+type=["']hidden["'][^>]*>/gi;
    let m;
    while ((m = re.exec(html)) !== null) {
        const tag = m[0];
        const name  = (tag.match(/name=["']([^"']+)["']/i) || [])[1];
        const value = (tag.match(/value=["']([^"']*)["']/i) || [])[1] || "";
        if (name) fields[name] = value;
    }
    return fields;
}

function extractSelectNames(html) {
    const names = [];
    const re = /<select[^>]+name=["']([^"']+)["'][^>]*>/gi;
    let m;
    while ((m = re.exec(html)) !== null) names.push(m[1]);
    return names;
}

function extractFirstTextInput(html) {
    const re = /<input[^>]+type=["']text["'][^>]*>/gi;
    let m;
    while ((m = re.exec(html)) !== null) {
        const tag = m[0];
        const name = (tag.match(/name=["']([^"']+)["']/i) || [])[1];
        const id   = ((tag.match(/id=["']([^"']+)["']/i) || [])[1] || "").toLowerCase();
        if (name && (id.includes("key") || id.includes("search") || id.includes("txt") || id.includes("model"))) {
            return name;
        }
    }
    // fallback: 第一個 text input
    re.lastIndex = 0;
    const first = re.exec(html);
    if (first) return (first[0].match(/name=["']([^"']+)["']/i) || [])[1] || null;
    return null;
}

function extractSubmitButton(html) {
    const re = /<input[^>]+type=["']submit["'][^>]*>/gi;
    const m = re.exec(html);
    if (!m) return null;
    const tag = m[0];
    const name  = (tag.match(/name=["']([^"']+)["']/i) || [])[1];
    const value = (tag.match(/value=["']([^"']+)["']/i) || [])[1] || "搜尋";
    return name ? { name, value } : null;
}

async function searchModel(model) {
    // === Step 1: GET 頁面，拿表單狀態 ===
    let pageHtml = null;
    try {
        const pageResp = await robustFetch("/list.aspx", {
            headers: { Referer: TARGET_HTTP + "/list.aspx" }
        });
        pageHtml = await pageResp.text();
    } catch (e) {
        // Step1 失敗，直接 fallback GET
        return await simpleGetSearch(model);
    }

    // 建立 POST 表單資料
    const formFields = extractHiddenFields(pageHtml);
    const selectNames = extractSelectNames(pageHtml);
    const keywordField = extractFirstTextInput(pageHtml);
    const submitBtn = extractSubmitButton(pageHtml);

    // 所有 select 設為空字串（= 全部）
    for (const sel of selectNames) formFields[sel] = "";
    if (keywordField) formFields[keywordField] = model;
    if (submitBtn) formFields[submitBtn.name] = submitBtn.value;

    const body = new URLSearchParams(formFields).toString();

    // === Step 2: POST 搜尋 ===
    try {
        const searchResp = await robustFetch("/list.aspx", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": TARGET_HTTP + "/list.aspx",
            },
            body,
        });

        const html = await searchResp.text();
        const link = findProductLink(html);
        if (link) return link;
    } catch (e) {
        // POST 失敗，繼續 fallback
    }

    return await simpleGetSearch(model);
}

async function simpleGetSearch(model) {
    const paramSets = [
        `key2=${encodeURIComponent(model)}`,
        `key2=${encodeURIComponent(model)}&Type=&RANK=&con=`,
        `key2=${encodeURIComponent(model)}&Type=0&RANK=0&con=0`,
    ];
    for (const params of paramSets) {
        try {
            const resp = await robustFetch(`/list.aspx?${params}`);
            const html = await resp.text();
            const link = findProductLink(html);
            if (link) return link;
        } catch (e) {
            // 繼續下一個
        }
    }
    return null;
}

function findProductLink(html) {
    const re = /href="([^"]*upt\.aspx\?[^"]*id=\d+[^"]*)"/i;
    const m = re.exec(html);
    return m ? m[1] : null;
}

async function fetchModelImage(model) {
    try {
        const href = await searchModel(model);

        if (!href) {
            return { status: "error", message: "找不到該型號（官網搜尋無結果）" };
        }

        const p0Match = href.match(/p0=(\d+)/);
        const idMatch = href.match(/id=(\d+)/);

        if (!p0Match || !idMatch) {
            return { status: "error", message: "無法解析產品連結參數" };
        }

        const imgPath = `/ImgViewer.ashx?applyID=${idMatch[1]}&goodID=${p0Match[1]}`;
        const imgResp = await robustFetch(imgPath, {
            headers: { Referer: TARGET_HTTP + "/list.aspx" }
        });

        if (!imgResp.ok) {
            return { status: "error", message: `圖檔請求失敗 (HTTP ${imgResp.status})` };
        }

        const imgHtml = await imgResp.text();
        const b64Match = /src="data:image\/[^;]+;base64,([^"]{100,})"/i.exec(imgHtml);

        if (!b64Match) {
            return { status: "error", message: "無法從頁面取得標章圖檔" };
        }

        return { status: "success", message: "已取得圖檔", imageData: b64Match[1] };

    } catch (err) {
        return { status: "error", message: `發生錯誤: ${err.message}` };
    }
}

export async function onRequest(context) {
    const { request } = context;

    if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: CORS });
    }

    if (request.method !== "POST") {
        return new Response(JSON.stringify({ error: "僅支援 POST" }), {
            status: 405, headers: { "Content-Type": "application/json", ...CORS }
        });
    }

    try {
        const { models = [] } = await request.json();
        if (!models.length) {
            return new Response(JSON.stringify({ error: "未提供型號" }), {
                status: 400, headers: { "Content-Type": "application/json", ...CORS }
            });
        }

        const results = [];
        for (const raw of models.slice(0, 10)) {
            const model = raw.trim();
            if (!model) continue;
            const result = await fetchModelImage(model);
            results.push({ model, result });
            await new Promise(r => setTimeout(r, 400));
        }

        return new Response(JSON.stringify({ results }), {
            status: 200, headers: { "Content-Type": "application/json", ...CORS }
        });

    } catch (err) {
        return new Response(JSON.stringify({ error: `伺服器錯誤: ${err.message}` }), {
            status: 500, headers: { "Content-Type": "application/json", ...CORS }
        });
    }
}
