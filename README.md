# YouTube → Gemini Transcribe → SRT / TXT / Word JSON

YouTube URL 或本地 MP3/MP4/WAV → FFmpeg 分段 → Gemini Interactions API 逐字辨識及時間碼 → `.srt`、`.txt`、`.words.json`。字幕時間碼來自模型的 word timestamps，不是播放時間估算。

## Windows 11 安裝

1. 安裝 Python 3.10+ 和 FFmpeg（`winget install Gyan.FFmpeg`）。重開 PowerShell，確認 `ffmpeg -version` 可執行。
2. 安裝依賴：

```powershell
py -m pip install --upgrade -r requirements.txt
```

3. **建立本機 YAML 設定檔**：

```powershell
Copy-Item config.example.yaml config.yaml
notepad config.yaml
```

範例（`config.example.yaml` 有其餘所有參數）：

```yaml
api_key: "YOUR_API_KEY_HERE"
api_base_url: "https://generativelanguage.googleapis.com"
default_language: "ja-JP"
model: "gemini-3.5-transcribe"
output: "transcript.srt"
chunk_minutes: 10
overlap: 2
max_chars: 64
max_words: 14
max_seconds: 5.5
gap: 0.75
retries: 3
diarize: false
keep_work: false
```

由 <https://aistudio.google.com/apikey> 取得 API Key。**將自己的 Key 放入 `config.yaml`，絕對不要放進 `config.example.yaml` 或提交 GitHub。** `.gitignore` 已忽略 `config.yaml`、`config.yml`、`config.json` 及常見衍生設定名稱；Git 曾經追蹤過的檔案仍須另行移出追蹤。

如果唔想喺硬碟存 Key，仍可用環境變數覆蓋：

```powershell
$env:GEMINI_API_KEY = "YOUR_API_KEY"
# or: $env:GOOGLE_API_KEY = "YOUR_API_KEY"
```

API Key 優先次序：**`GEMINI_API_KEY` > `GOOGLE_API_KEY` > YAML `api_key`**。讀取檔案不會將 Key 印到 terminal 或寫入字幕 JSON、暫存 manifest。

## 自訂 API Proxy（包括 HTTP）

`config.yaml`：

```yaml
api_key: "YOUR_PROXY_API_KEY"
api_base_url: "http://192.168.1.20:8080"
default_language: "yue-Hant-HK"
```

**HTTP 現已容許非本機 Proxy。** 但 HTTP 不加密；沿路中間人可以讀取或修改 **API Key 和上傳音訊**。只建議在可信內網、VPN 或你清楚風險的環境使用；能用 HTTPS 就盡量用 HTTPS。程式會顯示 HTTP 警告，但不阻止請求。

請輸入 **API 根網址**，例如 `http://host:8080`，而唔係 `http://host:8080/v1beta/interactions`。SDK 會自行組成相關端點。現時程式依賴：

- `POST {baseURL}/upload/v1beta/files`：上傳分段音訊
- `POST {baseURL}/v1beta/interactions`：轉錄
- `DELETE {baseURL}/v1beta/files/{file_id}`：清理暫存檔

你的 Proxy 必須支援 **Files API + Interactions API**（不只是 `generateContent`）。不同 Gateway 可能使用不同路徑；如未支援，單純更改 base URL 不會解決相容性問題。

API URL 優先次序：`--api-base-url` > `GEMINI_API_BASE_URL` > YAML `api_base_url` > Google SDK 官方預設。

## 使用

```powershell
# 使用 config.yaml 內的日文等預設設定
py transcribe_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 臨時覆蓋語言、輸出路徑
py transcribe_youtube.py "https://youtu.be/VIDEO_ID" --language en-US -o english.srt

# 使用另一份私有 YAML 設定
py transcribe_youtube.py "D:\Videos\clip.mp4" --config "D:\MyConfigs\hk.yaml"

# 對於特定操作臨時改 API 地址
py transcribe_youtube.py "D:\Videos\clip.mp4" --api-base-url "http://192.168.1.20:8080"
```

輸出三個檔案：`transcript.srt`、`transcript.txt`、`transcript.words.json`。支援 `ja-JP`、`en-US`、`ko-KR`、`yue-Hant-HK`；將 `default_language: ""` 設成自動識別。

### 設定方式

- 預設讀取程式旁嘅 **`config.yaml`**；如果沒有，嘗試 **`config.yml`**，最後讀舊版 **`config.json`** 方便升級。新版本請用 YAML。
- `--config FILE` 指定 `.yaml`、`.yml` 或舊版 `.json`；指定了不存在檔案會報錯。
- 一般設定由命令列參數覆蓋 YAML，例如 `--model`、`--chunk-minutes`、`--max-chars`、`--no-diarize`。`--restart` 只可命令列指定，以免設定檔意外觸發重做。
- YAML 使用 `PyYAML.safe_load`；請將 Key 及語言代碼加上引號。未知設定或錯誤型別會報錯。
- `config.example.yaml` 係公開範本，**唔好填真正 Key**；本機 `config.yaml` 已被 Git 忽略。若已經誤 commit Key，單靠 `.gitignore` 不能刪除歷史紀錄，需立即輪替 Key。

## 重試、續做及限制

每段完成便緩存結果；中斷後以同一輸出檔名和設定重新執行可沿用已完成分段。轉換模型、語言、Proxy 地址或分段設定會令舊暫存不相容，請用另一個輸出檔名，或明確 `--restart` 重做（會再用 API 額度）。`--keep-work` 可保留下載音訊和中間結果，方便重新排版。

字幕時間碼仍可能受音質、口音及模型識別影響；跨段交界可能漏詞。Word timestamps / speaker diarization 使用 Google 模型時單次有長度上限，預設切成 10 分鐘。YouTube 抓取受影片權限、地域及防機械人機制影響；只處理你有權使用的內容。

**測試說明**：可用 `py -m unittest discover -s tests -v` 執行離線測試（測試範例需要 FFmpeg）。未經真實 Proxy 和 Gemini Key 完整端到端驗證。

官方參考：<https://ai.google.dev/gemini-api/docs/transcribe> · <https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe> · <https://github.com/yt-dlp/yt-dlp>


## Proxy 回覆 `requires audio input` 時

`gemini-3.5-transcribe requires audio input` 表示 Interactions 服務未收到有效音訊，唔等於 YouTube 下載失敗。
Google 官方的 Interactions API 支援 Files API URI 同直接內嵌 Base64 音訊。
第三方 Proxy 如果 Files API 上傳成功但模型無法使用其 URI，可試 Inline：

```powershell
py transcribe_youtube.py "https://youtu.be/VIDEO_ID" --audio-input inline --restart
```

亦可以在本地 `config.yaml` 設定 `audio_input: "inline"`（預設 `file`）。
改變傳輸方式會要求使用 `--restart`（刪除程式管理暫存）或另一個輸出檔名；
`--restart` 可能導致重新下載，並對已完成的段落重新使用 API 額度。
Inline 模式唔會呼叫 Files API，會將每段 WAV 編碼為 Base64 直接放入 Interactions API 請求。
如果仍然出現同一個 400，代表 Proxy 可能唔支援 Interactions audio 內容，需要查 Proxy request body／轉發實作。
Inline 上限每段 60 MiB，若 Proxy 返回 413 Payload Too Large，縮小 `chunk_minutes`（例如 1 或 2）。
請勿公開記錄 Base64 音訊、API Key 或完整請求 body；HTTP Proxy 冇 TLS 加密，使用時需評估私隱風險。

官方參考：<https://ai.google.dev/gemini-api/docs/transcribe>、<https://ai.google.dev/api/interactions-api>。
