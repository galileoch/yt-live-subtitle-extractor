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

## 主要設定都放入 `config.json`（包括預設語言）

複製範例檔（如果已經有 `config.json`，請直接編輯原有檔案，避免覆蓋自己嘅設定）：

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

`config.json` 設定格式：

```json
{
  "api_base_url": "https://generativelanguage.googleapis.com",
  "default_language": "ja-JP",
  "model": "gemini-3.5-transcribe",
  "output": "transcript.srt",
  "diarize": false,
  "chunk_minutes": 10,
  "overlap": 2,
  "max_chars": 64,
  "max_words": 14,
  "max_seconds": 5.5,
  "gap": 0.75,
  "retries": 3,
  "keep_work": false
}
```

- **`default_language`**：例如 `ja-JP` 日文、`en-US` 英文、`yue-Hant-HK` 廣東話、`ko-KR` 韓文。設成 `""` 就係自動辨識（範例為日文，可自行修改）。亦接受舊式 `language`，但兩個欄位唔可以同時存在。
- **`model`**：Gemini Transcribe 模型名稱；換模型前要確認新模型支援 Files + Interactions 逐字時間戳接口。
- **`api_base_url`**：Google 官方 API 根網址，或者你自己嘅 Gemini API Gateway，例如 `https://your-gemini-proxy.example.com`；唔好包含 `/v1beta`、API 方法路徑或 Key。
- **`output`**：預設 SRT 名稱（相對路徑由執行程式時嘅工作目錄計算），TXT / JSON 會用相同檔名。
- **`diarize` / `keep_work`**：布林值，JSON 用 `true` 或 `false`。
- **`chunk_minutes` / `overlap`**：每段分鐘數、前後重疊秒數。
- **`max_chars` / `max_words` / `max_seconds` / `gap`**：字幕長度、斷句及停頓閾值。
- **`retries`**：短暫 API 失敗重試次數。

只需要填想修改嘅欄位；其餘使用程式預設值。`config.json` 預設位於 `transcribe_youtube.py` 同一資料夾，並且已加入 `.gitignore`。

**執行時只提供影片 URL 即可沿用全部設定**：

```powershell
py transcribe_youtube.py "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

需要臨時改語言、輸出或其他設定：

```powershell
py transcribe_youtube.py "https://youtu.be/VIDEO_ID" --language en-US -o english.srt --max-chars 48
```

如需指定另一個設定檔：

```powershell
py transcribe_youtube.py "https://youtu.be/VIDEO_ID" --config configs\japanese.json
```

亦可以用 `--no-diarize` 或 `--no-keep-work` 臨時將設定檔入面嘅 `true` 關閉。`--restart` 刻意只可以由命令列啟用，避免自動清除快取並重新計費。

設定優先次序：一般欄位 **命令列 > config.json > 程式預設**；只有 API URL 額外支援環境變數，優先次序係 **`--api-base-url` > `GEMINI_API_BASE_URL` > config.json > 官方 SDK 預設**。環境變數例如：

```powershell
$env:GEMINI_API_BASE_URL = 'https://your-gemini-proxy.example.com'
```

**API Key 一律用 `GEMINI_API_KEY` / `GOOGLE_API_KEY` 環境變數，唔好將密鑰寫入或 commit 設定檔。** 自訂 API Gateway 須支援 **Gemini Files API**（音訊上傳／刪除）及 **Interactions API**（轉錄），唔係任何 OpenAI-compatible API 都得；第三方 Gateway 會收到 API Key 及音訊。非本機地址必須使用 HTTPS。改咗 API URL、模型或轉錄參數，舊暫存如不兼容，請換一個輸出檔名或明確加 `--restart`。


## 轉錄 YouTube

```powershell
py transcribe_youtube.py "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --language ja-JP --output japanese.srt
```

輸出：`japanese.srt`、`japanese.txt`、`japanese.words.json`（每個詞的 `text,start,end,speaker`）。SRT 可在 VLC 或 Subtitle Edit 開啟。

自動辨識語言（例如日英混合）：設定 `config.json` 入面 `"default_language": ""`，或者執行時明確覆蓋：

```powershell
py transcribe_youtube.py "https://youtu.be/VIDEO_ID" --language "" --output transcript.srt
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
| `--language ja-JP` | 命令列覆蓋 `config.json` 預設語言；`--language ""` 自動偵測 |
| `--api-base-url URL` | 指定 Gemini 相容 API 根網址，覆蓋環境變數及設定檔 |
| `--config FILE` | 讀取指定 JSON 設定檔 |
| `--model NAME` | 覆蓋模型名稱 |
| `--chunk-minutes 10` | 每段 10 分鐘，支援 0.5–25 分鐘（因啟用 timestamps，Google 限制 30 分鐘／次） |
| `--overlap 2` | 分段前後重疊 2 秒，處理跨界句子；只保留核心區時間碼，防止重複字幕 |
| `--max-seconds 5.5` | 單條字幕最長 5.5 秒 |
| `--max-chars 64` | 字幕最多約 64 個英文字寬（中文字佔兩格） |
| `--max-words 14` | 每條字幕最多 14 詞 |
| `--diarize` / `--no-diarize` | 啟用／關閉說話者標籤 |
| `--keep-work` / `--no-keep-work` | 成功後保留／清除音訊、暫存結果 |
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
