// Cloudflare Pages Function - No external dependencies needed
const TARGET_BASE_URL = "https://ranking.energylabel.org.tw/product/Approval";

async function fetchModelImage(model) {
    try {
        const listUrl = `${TARGET_BASE_URL}/list.aspx?key2=${encodeURIComponent(model)}`;
        const listResponse = await fetch(listUrl, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
        });

        if (!listResponse.ok) {
            return { status: "error", message: `網站連線失敗 (HTTP ${listResponse.status})` };
        }

        const listHtml = await listResponse.text();

        // Use regex to find product link - no external parser needed
        const linkPattern = /href="([^"]*upt\.aspx\?[^"]*id=\d+[^"]*)"/gi;
        let match = linkPattern.exec(listHtml);

        if (!match) {
            return { status: "error", message: "找不到該型號的分級資料" };
        }

        const href = match[1];
        const p0Match = href.match(/p0=(\d+)/);
        const idMatch = href.match(/id=(\d+)/);

        if (!p0Match || !idMatch) {
            return { status: "error", message: "無法解析產品編號" };
        }

        const p0 = p0Match[1];
        const applyId = idMatch[1];

        // Fetch image page
        const imgUrl = `${TARGET_BASE_URL}/ImgViewer.ashx?applyID=${applyId}&goodID=${p0}`;
        const imgResponse = await fetch(imgUrl, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
        });

        if (!imgResponse.ok) {
            return { status: "error", message: `無法取得圖檔 (HTTP ${imgResponse.status})` };
        }

        const imgHtml = await imgResponse.text();

        // Extract base64 from <img src="data:image/jpeg;base64,...">
        const base64Pattern = /src="data:image\/[^;]+;base64,([^"]+)"/i;
        const base64Match = base64Pattern.exec(imgHtml);

        if (!base64Match) {
            return { status: "error", message: "無法從頁面取得標章圖檔" };
        }

        return {
            status: "success",
            message: "已取得圖檔",
            imageData: base64Match[1]
        };

    } catch (error) {
        return { status: "error", message: `發生錯誤: ${error.message}` };
    }
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

        // Limit to 10 models per request
        const limitedModels = models.slice(0, 10);
        const results = [];

        for (const model of limitedModels) {
            const trimmed = model.trim();
            if (trimmed) {
                const result = await fetchModelImage(trimmed);
                results.push({ model: trimmed, result });
                // Polite delay
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
