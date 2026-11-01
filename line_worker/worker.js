// LINE 打字查詢：貼到 Cloudflare Workers（免費方案就夠）。
// LINE 傳來的訊息 → 驗證簽章 → 只接受你自己的 LINE 帳號 → 觸發 GitHub 的 query.yml → 約 1 分鐘後 LINE 收到結果。
// Worker 的 Settings → Variables and Secrets 要設定（都選 Secret）：
//   LINE_CHANNEL_SECRET  LINE Developers → Basic settings 的 Channel secret（32 個字）
//   LINE_TOKEN           Channel access token（跟 GitHub Secrets 的 LINE_TOKEN 一樣）
//   LINE_USER_ID         你的 LINE User ID（跟 GitHub Secrets 的 LINE_USER_ID 一樣），其他人傳的訊息會被忽略
//   GH_TOKEN             GitHub fine-grained token：只勾 Stock-lab，權限 Actions = Read and write
const REPO = "gelu27/Stock-lab";

async function 簽章正確(body, signature, secret) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return btoa(String.fromCharCode(...new Uint8Array(mac))) === signature;
}

async function 回覆(token, replyToken, text) {
  await fetch("https://api.line.me/v2/bot/message/reply", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ replyToken, messages: [{ type: "text", text }] }),
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok");
    const body = await request.text();
    if (!(await 簽章正確(body, request.headers.get("x-line-signature") || "", env.LINE_CHANNEL_SECRET))) {
      return new Response("bad signature", { status: 401 });
    }
    for (const e of JSON.parse(body).events || []) {
      if (e.type !== "message" || e.message.type !== "text" || e.source.userId !== env.LINE_USER_ID) continue;
      const q = e.message.text.trim().slice(0, 12);
      if (!/^[0-9A-Za-z一-鿿*-]{2,12}$/.test(q)) {
        await 回覆(env.LINE_TOKEN, e.replyToken, "請輸入股票代號（例如 2330）或名稱（例如 台積電）。");
        continue;
      }
      const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/query.yml/dispatches`, {
        method: "POST",
        headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "line-query-worker" },
        body: JSON.stringify({ ref: "main", inputs: { q } }),
      });
      await 回覆(env.LINE_TOKEN, e.replyToken, r.ok ? `🔍 查詢「${q}」中，約 1 分鐘後回覆。` : `查詢失敗（GitHub ${r.status}），請檢查 GH_TOKEN。`);
    }
    return new Response("ok");
  },
};
