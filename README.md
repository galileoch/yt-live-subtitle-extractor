# YouTube → Gemini 3.5 Transcribe → SRT / TXT / Word JSON (v2)

**功能**：YouTube URL 或本地 MP3/MP4/WAV → 音訊分段 → Gemini 非即時逐字辨識／word timestamps → 合併全片時間碼 → `.srt`, `.txt`, `.words.json`。語音不需從喇叭播放，亦不會擷取 Windows 系統雜音。原有即時版 `gemini-3.5-transcribe-live` 不支援 word-level timestamps；因此精準字幕版本採用 `gemini-3.5-transcribe`。

## Windows 11 安裝

1. 安裝 Python 3.10+：<https://www.python.org/downloads/windows/>
2. 安裝 FFmpeg（要 `ffmpeg` 和 `ffprobe` 命令都可在 PowerShell 執行），例如 `winget install Gyan.FFmpeg`。如果新裝完仍顯示找不到命令，重新開 PowerShell。
3. 在下載 ZIP 並解壓的資料夾開 PowerShell：

```powershell
py -m pip install --upgrade -r requirements.txt
$env:GEMINI_API_KEY = 'YOUR_GEMINI_API_KEY'
ffmpeg -version
```

API Key：<https://aistudio.google.com/apikey>。需有可用 Gemini API 模型額度；此工具不提供免費額度或繞過限制。

## 自訂 Gemini API URL

預設使用 Google 官方 API，毋須設定 URL。若要改成自訂 API Gateway / 代理伺服器，可用以下三種方式：

**方法一：修改設定檔（推薦）**

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

把 `config.json` 入面嘅 `api_base_url` 改成你嘅 API 根網址，例如：

```json
{
  "api_base_url": "https://your-gemini-proxy.example.com"
}
```

`config.json` 已加入 `.gitignore`，方便儲存自己嘅地址，唔會意外 commit。**API Key 請繼續用 `GEMINI_API_KEY` 環境變數，唔好寫入設定檔。**

**方法二：環境變數**（PowerShell）：

```powershell
$env:GEMINI_API_BASE_URL = 'https://your-gemini-proxy.example.com'
```

**方法三：命令列參數**（只覆蓋今次執行）：

```powershell
py transcribe_youtube.py 'https://youtu.be/VIDEO_ID' --api-base-url 'https://your-gemini-proxy.example.com' -o result.srt
```

設定優先次序：`--api-base-url` ＞ `GEMINI_API_BASE_URL` ＞ `config.json` ＞ Google SDK 官方預設值。自訂 URL 應係 **base URL**，例如 `https://host.example.com/gemini`，**唔好附加 `/v1beta`、`/models`、`/interactions` 或 API Key**；SDK 會自行組成 API 路徑。非本機地址需要 HTTPS，本機開發可使用 `http://localhost:8080`。

注意：呢個程式會用同一地址呼叫 **Gemini Files API（上傳及刪除音訊）同 Interactions API（逐字轉錄）**。第三方 Gateway 必須完整支援以上接口，只支援 `generateContent` 嘅代理唔可以直接使用。使用非 Google 官方地址時，**API Key 同音訊資料可能會傳送到該服務提供者**，請只使用可信服務。更改地址後如已有舊暫存，程式會要求用另一個 `-o` 檔名，或加 `--restart` 重新處理，以避免混用兩個後端結果。


## 轉錄 YouTube

```powershell
py transcribe_youtube.py "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --language ja-JP --output japanese.srt
```

輸出：`japanese.srt`、`japanese.txt`、`japanese.words.json`（每個詞的 `text,start,end,speaker`）。SRT 可在 VLC 或 Subtitle Edit 開啟。

自動辨識語言（例如日英混合）省略 `--language`：

```powershell
py transcribe_youtube.py "https://youtu.be/VIDEO_ID" --output transcript.srt
```

本地影片／音訊：

```powershell
py transcribe_youtube.py "D:\Videos\clip.mp4" --language yue-Hant-HK -o clip.srt
```

多位講者：

```powershell
py transcribe_youtube.py "D:\Videos\interview.mp4" --diarize -o interview.srt
```

## 常用參數

| 參數 | 用途 |
|---|---|
| `--language ja-JP` | 日文；`en-US` 英文、`yue-Hant-HK` 廣東話、`ko-KR` 韓文；不指定自動偵測 |
| `--api-base-url URL` | 指定 Gemini 相容 API 根網址，覆蓋環境變數及設定檔 |
| `--chunk-minutes 10` | 每段 10 分鐘，支援 0.5–25 分鐘（因啟用 timestamps，Google 限制 30 分鐘／次） |
| `--overlap 2` | 分段前後重疊 2 秒，處理跨界句子；只保留核心區時間碼，防止重複字幕 |
| `--max-seconds 5.5` | 單條字幕最長 5.5 秒 |
| `--max-chars 64` | 字幕最多約 64 個英文字寬（中文字佔兩格） |
| `--max-words 14` | 每條字幕最多 14 詞 |
| `--diarize` | 要求說話者標籤（對多人會話較有用） |
| `--keep-work` | 成功後仍保留下載音訊、分段回應暫存（較佔磁碟） |
| `--restart` | 刪除由本程式管理的對應暫存，重新轉錄，會再次產生 API 用量 |

## 續做及可靠性

每一段成功之後會即時儲存 JSON 暫存。下載或轉錄中途失敗後，以相同參數重新執行同一條命令，**已完成段落不會重複向 Gemini 收費**；失敗中的段落仍可能已用 API 額度。全部成功後，預設清理暫存。若需事後調校字幕分段但保留原始段落，首次執行加 `--keep-work`，修改 `--max-chars` 或 `--max-seconds` 後可重新執行而不需再轉錄。

> 注意：`--restart` 只應用於由本程式建立、有 `.gemini-stt-managed` 標記的暫存資料夾；同一輸出檔名換不同影片或語言請用 `--restart` 或另一個輸出檔名。

## 限制與準確度

- Gemini **word timestamps 係模型提供嘅時間碼**，非播放時間估算，但實際準確度視乎口音、歌聲、音質、背景音樂等，不能保證無誤。英文及日文詞的切分跟隨模型輸出。中文可能以字詞或短語作為單位。
- Gemini 官方提醒，開啟 word timestamps 可能降低轉錄文字準確度。Word timestamps / speaker diarization 最多 **30 分鐘音訊／API 請求**；此程式每段 10 分鐘及重疊，適合長片。
- `.txt` 用去重後的字幕內容合成；`.words.json` 保留模型字詞與時間碼，方便進行人工校正。多段末端交界處如模型漏字，仍要校對。如啟用 `--diarize`，講者 ID 可能喺新分段重新編號，不能保證跨段對應同一人。原文不會自動翻譯。
- YouTube 下載依賴 `yt-dlp`，受影片權限／地區／反機械人措施／網站變動影響，無法保證所有 URL 均可下載。需要時更新 `py -m pip install -U yt-dlp`；DRM 或無權限影片不支援。只能轉錄你有權存取及使用嘅內容。
- 程式把音訊分段上載到 Google API 進行處理；留意私隱、服務條款、API 收費及額度。遠端已上載檔案會盡量刪除，刪除失敗會顯示警告。
- API Key 唔好寫死在程式或公開儲存庫。字詞時間碼缺失時程式會報錯，而**不會偷偷用猜測時間填補**。
- 已通過離線單元測試，**未以真實 Gemini API Key 及 YouTube 影片完成端到端測試**。

### 官方參考

- Gemini 3.5 Transcribe：<https://ai.google.dev/gemini-api/docs/transcribe>
- 模型能力／限制：<https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe>
- yt-dlp：<https://github.com/yt-dlp/yt-dlp>
- FFmpeg：<https://ffmpeg.org/>
