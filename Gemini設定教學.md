# Gemini API 申請與設定教學（手機也能做）

## 一、申請 Gemini 金鑰（約 3 分鐘，有免費額度）
1. 用 Google 帳號登入 https://aistudio.google.com
2. 左下角或首頁點「Get API key」→「Create API key」（選一個專案，沒有就讓它自動建立）。
3. 複製以「AIza」開頭的一長串字，這就是 `GEMINI_API_KEY`。**不要貼到聊天或公開的地方**。
4. 免費額度夠日常用（Flash 模型）；超過或要用 Google 搜尋，才需要到 Google AI Studio 綁定付費。可在 aistudio.google.com 的 Usage 頁看用量。

## 二、放進網站與排程（兩處都要放同一把）
**A. GitHub（讓自動排程用）**：repo → Settings → Secrets and variables → Actions → New repository secret
- `GEMINI_API_KEY`：剛剛的金鑰（大盤解讀其實已經在用，已有就不用重放）
- `GEMINI_MODEL`（選填）：預設 `gemini-flash-latest`

**B. Streamlit（讓網站按鈕用）**：App settings → Secrets，加一行 `GEMINI_API_KEY = "AIza…"`。

## 三、券商報告自動讀取（雲端資料夾）
1. 雲端資料夾（放 PDF／截圖的那個）→ 共用 → 一般存取權改成「知道連結的任何人」、角色「檢視者」。
2. 資料夾網址最後一段（`folders/` 後面那串）就是 `DRIVE_FOLDER_ID`。
3. https://console.cloud.google.com → 建立專案 → API 和服務 → 啟用「Google Drive API」→ 憑證 → 建立憑證 → API 金鑰，就是 `GOOGLE_API_KEY`（可限制只能呼叫 Drive API）。
4. 兩個都存成 GitHub Secrets。注意：知道連結的人都看得到這個資料夾，請勿放不想公開的檔案；不想公開就維持現狀由 Claude 排程讀取。

## 四、網紅影片自動整理
- 在 ai-reports 分支建立 `video_sources.json`（可在 GitHub 網頁直接新增檔案）：
```json
{"頻道": [{"名稱": "宏爺講股", "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx"}],
 "網址": []}
```
- 頻道 ID：開頻道頁 → 網址若是 `/channel/UC…` 即是；若是 `@名稱`，到頻道「關於」→ 分享頻道 → 複製頻道 ID。
- 隨時想補一支：Actions →「自動收件」→ Run workflow，`mode` 填 videos，`urls` 貼影片網址。

## 五、怎麼確認有跑
- 每個交易日 21:27、22:52 自動跑；成功或失敗都會 LINE 通知。
- 每週六 LINE 會傳「近 7 天 Gemini 呼叫次數」小卡。
- 每日呼叫上限預設 80 次，可加 Secret／環境變數 `AI_DAILY_CAP` 調整。

## 費用與注意
- 影片整理每支約消耗一次長輸入（影片越長越多），建議頻道數先少量、看用量小卡再增加。
- Gemini 偶爾會把數字抄錯；自動收件只做格式與代號名稱的初步查核，重要數字仍以網站資料為準。
