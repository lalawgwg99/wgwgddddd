// Cloudflare Pages Function - Energy Label Saver
// Two-step ASP.NET search: GET form state → POST with all params

const TARGET_BASE_URL = "https://ranking.energylabel.org.tw/product/Approval";

const HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
};

function extractAspNetFields(html) {
    const fields = {};
    const pattern = /<input[^>]+type="hidden"[^>]*>/gi;
    let match;
    while ((match = pattern.exec(html)) !== null) {
        const tag = match[0];
        const nameMatch = tag.match(/name="([^"]+)"/);
        const valueMatch = tag.match(/value="([^"]*)"/);
        if (nameMatch) {
            fields[nameMatch[1]] = valueMatch ? valueMatch[1] : '';
        }
    }
    return fields;
}

function findSelectNames(html) {
    // Find all <select name="..."> elements
    const selectPattern = /<select[^>]+name="([^"]+)"[^>]*>/gi;
    const selects = [];
    let m;
    while ((m = selectPattern.exec(html)) !== null) {
        selects.push(m[1]);
    }
    return selects;
}

function findTextInputName(html) {
    // Find <input type="text" name="...">
    const pattern = /<input[^>]+type="text"[^>]+name="([^"]+)"/gi;
    const m = pattern.exec(html);
    return m ? m[1] : null;
}

function findSubmitButtonName(html) {
    const pattern = /<input[^>]+type="submit"[^>]+name="([^"]+)"/gi;
    const m = pattern.exec(html);
    return m ? m[1] : null;
}

async function fetchModelImage(model) {
    try {
        const listUrl = `${TARGET_BASE_URL}/list.aspx`;

        // Step 1: GET the page to capture form state
        const pageResp = await fetch(listUrl, { headers: HEADERS });
        if (!pageResp.ok) {
            return await simpleFetch(model);
        }
        const pageHtml = await pageResp.text();

        // Extract ASP.NET fields
        const aspFields = extractAspNetFields(pageHtml);
        const selects = findSelectNames(pageHtml);
        const textInput = findTextInputName(pageHtml);
        const submitBtn = findSubmitButtonName(pageHtml);

        // Build form data
        const formData = new URLSearchParams();

        // Add ASP.NET hidden fields
        for (const [key, value] of Object.entries(aspFields)) {
            formData.set(key, value);
        }

        // Set all select dropdowns to empty (= all / 全部)
        for (const sel of selects) {
            formData.set(sel, '');
        }

        // Set keyword
        if (textInput) {
            formData.set(textInput, model);
        }

        // Click search button
        if (submitBtn) {
            formData.set(submitBtn, '搜尋');
        }

        // Step 2: POST the search
        const searchResp = await fetch(listUrl, {
            method: 'POST',
            headers: {
                ...HEADERS,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': listUrl,
            },
            body: formData.toString(),
        });

        let resultHtml;
        if (searchResp.ok) {
            resultHtml = await searchResp.text();
        } else {
            return await simpleFetch(model);
        }

        // Find product links in the result
        let linkPattern = /href="([^"]*upt\.aspx\?[^"]*id=\d+[^"]*)"/gi;
        let linkMatch = linkPattern.exec(resultHtml);

        // If POST didn't find results, try simple GET fallback
        if (!linkMatch) {
            return await simpleFetch(model);
        }

        return await fetchImage(linkMatch[1]);

    } catch (error) {
        // Last resort fallback
        try {
            return await simpleFetch(model);
        } catch (e) {
            return { status: "error", message: `發生錯誤: ${error.message}` };
        }
    }
}

async function simpleFetch(model) {
    const url = `${TARGET_BASE_URL}/list.aspx?key2=${encodeURIComponent(model)}`;
    const resp = await fetch(url, { headers: HEADERS });
    if (!resp.ok) {
        return { status: "error", message: `網站連線失敗 (HTTP ${resp.status})` };
    }
    const html = await resp.text();
    const linkPattern = /href="([^"]*upt\.aspx\?[^"]*id=\d+[^"]*)"/gi;
    const match = linkPattern.exec(html);
    if (!match) {
        return { status: "error", message: "找不到該型號的分級資料" };
    }
    return await fetchImage(match[1]);
}

async function fetchImage(href) {
    const p0Match = href.match(/p0=(\d+)/);
    const idMatch = href.match(/id=(\d+)/);

    if (!p0Match || !idMatch) {
        return { status: "error", message: "無法解析產品編號" };
    }

    const imgUrl = `${TARGET_BASE_URL}/ImgViewer.ashx?applyID=${idMatch[1]}&goodID=${p0Match[1]}`;
    const imgResponse = await fetch(imgUrl, { headers: HEADERS });

    if (!imgResponse.ok) {
        return { status: "error", message: `無法取得圖檔 (HTTP ${imgResponse.status})` };
    }

    const imgHtml = await imgResponse.text();
    const base64Pattern = /src="data:image\/[^;]+;base64,([^"]+)"/i;
    const base64Match = base64Pattern.exec(imgHtml);

    if (!base64Match || base64Match[1].length < 100) {
        return { status: "error", message: "無法從頁面取得標章圖檔" };
    }

    return {
        status: "success",
        message: "已取得圖檔",
        imageData: base64Match[1]
    };
}

export async function onRequest(context) {
    const { request } = context;

    const corsHeaders = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
        return new Response(null, { status: 204, headers: corsHeaders });
    }

    if (request.method !== 'POST') {
        return new Response(JSON.stringify({ error: '僅支援 POST 請求' }), {
            status: 405,
            headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });
    }

    try {
        const data = await request.json();
        const models = data.models || [];

        if (!Array.isArray(models) || models.length === 0) {
            return new Response(JSON.stringify({ error: '未提供型號清單' }), {
                status: 400,
                headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
        }

        const limitedModels = models.slice(0, 10);
        const results = [];

        for (const model of limitedModels) {
            const trimmed = model.trim();
            if (trimmed) {
                const result = await fetchModelImage(trimmed);
                results.push({ model: trimmed, result });
                await new Promise(r => setTimeout(r, 300));
            }
        }

        return new Response(JSON.stringify({ results }), {
            status: 200,
            headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });

    } catch (error) {
        return new Response(JSON.stringify({ error: `伺服器錯誤: ${error.message}` }), {
            status: 500,
            headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });
    }
}
