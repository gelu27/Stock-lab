// LINE 打字查詢：貼到 Cloudflare Workers（免費方案就夠）。
// LINE 傳來的訊息 → 驗證簽章 → 只接受你自己的 LINE 帳號 → 顯示「輸入中」動畫 → 觸發 GitHub 的 query.yml
// → 約 1 分鐘後收到文字摘要（用「回覆」傳，不算每月免費則數），再 1～2 分鐘收到 AI 分析、報告圖片與 PDF 連結。
// 打「2330快」只回文字摘要。
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

async function 輸入中(token, userId) {  // 聊天室顯示「輸入中」動畫最多 60 秒，免費
  await fetch("https://api.line.me/v2/bot/chat/loading/start", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ chatId: userId, loadingSeconds: 60 }),
  });
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
      if (e.type !== "message" || e.message.type !== "text") continue;
      if (e.source.userId !== env.LINE_USER_ID) {  // 設定錯時顯示自己的 ID，方便對照
        await 回覆(env.LINE_TOKEN, e.replyToken, `這個帳號沒有查詢權限。你的 User ID：${e.source.userId}`);
        continue;
      }
      const q = e.message.text.trim().slice(0, 12);
      if (!/^[0-9A-Za-z一-鿿*-]{2,12}$/.test(q)) {
        await 回覆(env.LINE_TOKEN, e.replyToken, "請輸入股票代號（例如 2330）或名稱（例如 台積電）。");
        continue;
      }
      const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/query.yml/dispatches`, {
        method: "POST",
        headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "line-query-worker" },
        body: JSON.stringify({ ref: "main", inputs: { q, reply: e.replyToken } }),
      });
      // 成功時不先回「查詢中」，把回覆權杖留給 GitHub 傳結果（回覆不算免費則數）；失敗才在這裡回覆
      if (r.ok) await 輸入中(env.LINE_TOKEN, e.source.userId);
      else await 回覆(env.LINE_TOKEN, e.replyToken, `查詢失敗（GitHub ${r.status}），請檢查 GH_TOKEN。`);
    }
    return new Response("ok");
  },
};
