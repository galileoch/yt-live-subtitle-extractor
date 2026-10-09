"""YouTube/local video -> Gemini 3.5 Transcribe (word timestamps) -> SRT, TXT, JSON.

Python 3.10+, yt-dlp, FFmpeg and Gemini API key required.
Use only for videos you're authorized to process.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

from subtitle_core import Word, accept_core_words, make_cues, parse_annotations, render_srt, render_txt, word_dicts

MODEL = 'gemini-3.5-transcribe'
MANAGED = '.gemini-stt-managed'


def out(message: str) -> None:
    print(message, flush=True)


def run_command(command: list[str], description: str, *, silent: bool = False) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    except FileNotFoundError as exc:
        raise RuntimeError(f'{description}: 找唔到工具 {command[0]}') from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-3500:].strip()
        raise RuntimeError(f'{description} 失敗 (exit {result.returncode}):\n{detail}')
    if not silent and result.stdout.strip():
        out(result.stdout.strip()[-800:])
    return result.stdout


def youtube_url(source: str) -> bool:
    parsed = urlparse(source)
    return (parsed.scheme in ('https', 'http') and
            (parsed.hostname or '').lower() in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'))


def resolve_source(source: str) -> dict:
    if source.startswith(('http://', 'https://')):
        if not youtube_url(source):
            raise ValueError('只接受 YouTube URL；其他影片請先另存成音訊／影片檔，再提供本地路徑。')
        return {'kind': 'youtube', 'source': source}
    p = Path(source).expanduser().resolve()
    if not p.is_file():
        raise ValueError(f'找唔到輸入檔案：{p}')
    stat = p.stat()
    return {'kind': 'file', 'source': str(p), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def check_tools(source_spec: dict) -> None:
    for program in ('ffmpeg', 'ffprobe'):
        if shutil.which(program) is None:
            raise RuntimeError(f'請先安裝 FFmpeg，並將 {program} 加到 Windows PATH。')
    if source_spec['kind'] == 'youtube':
        try:
            import yt_dlp  # noqa: F401
        except ImportError as exc:
            raise RuntimeError('需要 yt-dlp：py -m pip install -r requirements.txt') from exc


def source_media(source_spec: dict, workspace: Path) -> Path:
    if source_spec['kind'] == 'file':
        return Path(source_spec['source'])
    existing = [p for p in workspace.glob('downloaded.*') if p.is_file() and not p.name.endswith(('.part', '.ytdl'))]
    if existing:
        return existing[0]
    out('下載 YouTube 音訊（只選擇單一影片）...')
    run_command([sys.executable, '-m', 'yt_dlp', '--no-playlist', '--no-warnings',
                 '-f', 'bestaudio/best', '--output', str(workspace / 'downloaded.%(ext)s'),
                 source_spec['source']], 'YouTube 音訊下載')
    candidates = [p for p in workspace.glob('downloaded.*') if p.is_file() and not p.name.endswith(('.part', '.ytdl'))]
    if len(candidates) != 1:
        raise RuntimeError(f'下載後未找到唯一音訊檔：{[p.name for p in candidates]}')
    return candidates[0]


def probe_duration(media: Path) -> float:
    result = run_command(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'json', str(media)], 'FFprobe', silent=True)
    duration = float(json.loads(result)['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f'音訊長度異常：{duration}')
    return duration


def build_chunk(media: Path, dest: Path, start: float, duration: float) -> None:
    """Re-encode (never stream-copy) so FFmpeg seeks to the correct source position."""
    tmp = dest.with_suffix('.tmp.wav')
    try:
        run_command(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                     '-y', '-ss', f'{start:.6f}', '-i', str(media), '-t', f'{duration:.6f}',
                     '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
                     str(tmp)], f'切割音訊 {start:.1f}s', silent=True)
        if not tmp.is_file() or tmp.stat().st_size <= 44:
            raise RuntimeError(f'FFmpeg 未有產生有效音訊：{tmp}')
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def cache_state(args: argparse.Namespace, source_spec: dict) -> dict:
    return {'version': 2, 'source': source_spec, 'model': MODEL,
            'language': args.language, 'diarize': args.diarize,
            'chunk_seconds': args.chunk_minutes * 60, 'overlap': args.overlap}


def initialize_workdir(workspace: Path, expected: dict, restart: bool) -> None:
    if restart and workspace.exists():
        if not (workspace / MANAGED).is_file():
            raise RuntimeError(f'拒絕清除未知資料夾：{workspace}（冇 {MANAGED}）')
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    marker = workspace / MANAGED
    manifest = workspace / 'manifest.json'
    if manifest.exists():
        if not marker.is_file():
            raise RuntimeError(f'暫存資料夾缺少管理標記：{workspace}')
        if json.loads(manifest.read_text('utf-8')) != expected:
            raise RuntimeError('之前嘅工作目錄設定唔同。請換一個 --output，或者加 --restart 清除舊暫存。')
    elif any(workspace.iterdir()):
        raise RuntimeError(f'工作目錄已有未知檔案，拒絕覆蓋：{workspace}')
    else:
        marker.write_text('Managed by YouTube Gemini STT v2.\n', encoding='utf-8')
        atomic_json(manifest, expected)
    (workspace / 'segments').mkdir(exist_ok=True)
    (workspace / 'results').mkdir(exist_ok=True)


def make_config(language: str, diarize: bool) -> dict:
    mode = {'type': 'verbatim', 'timestamp_granularities': ['word']}
    if diarize:
        mode['diarization_mode'] = 'speaker'
    return {'transcription_config': {'language_codes': [language] if language else [], 'mode': mode}}


def is_transient(exc: Exception) -> bool:
    # API errors may expose status via code/status_code, or only in their repr.
    code = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
    if str(code) in ('408', '429', '500', '502', '503', '504'):
        return True
    msg = str(exc).lower()
    return any(s in msg for s in ('429', 'resource_exhausted', 'rate limit', 'deadline',
                                  'timeout', 'timed out', '503', '502', '504', '500', 'internal server error'))


def transcribe_segment(client, wav_path: Path, duration: float, language: str,
                       diarize: bool, retries: int) -> dict:
    config = make_config(language, diarize)
    for attempt in range(retries + 1):
        uploaded = None
        try:
            uploaded = client.files.upload(file=str(wav_path))
            if not getattr(uploaded, 'uri', None):
                raise RuntimeError('Gemini Files API 冇回傳檔案 URI')
            interaction = client.interactions.create(
                model=MODEL,
                input=[{'type': 'audio', 'uri': uploaded.uri,
                        'mime_type': uploaded.mime_type or 'audio/wav'}],
                generation_config=config,
            )
            status_obj = getattr(interaction, 'status', 'completed')
            status = str(getattr(status_obj, 'value', status_obj)).lower().rsplit('.', 1)[-1]
            if status not in ('completed', 'none', ''):
                raise RuntimeError(f'Gemini transcription returned status={status}: {getattr(interaction, "error", "")}')
            raw_text = str(getattr(interaction, 'output_text', '') or '').strip()
            words = parse_annotations(interaction, duration)
            if raw_text and not words:
                raise RuntimeError('Gemini 回傳咗文字但冇任何 word_info 時間碼；避免製作錯誤 SRT，已停止。')
            return {'text': raw_text, 'words': word_dicts(words)}
        except Exception as exc:
            if attempt >= retries or not is_transient(exc):
                raise
            delay = min(45, 2 ** (attempt + 2))
            out(f'API 暫時失敗（{type(exc).__name__}）；{delay} 秒後重試 {attempt+1}/{retries}...')
            time.sleep(delay)
        finally:
            if uploaded is not None and getattr(uploaded, 'name', None):
                try:
                    client.files.delete(name=uploaded.name)
                except Exception as error:
                    out(f'警告：無法刪除 Gemini Files API 暫存 {uploaded.name}：{error}')
    raise AssertionError('unreachable')


def run_pipeline(args: argparse.Namespace, *, client=None) -> tuple[Path, Path, Path]:
    if not (0.5 <= args.chunk_minutes <= 25):
        raise ValueError('--chunk-minutes 必須介乎 0.5 至 25（啟用時間碼上限 30 分鐘）')
    if not (0 <= args.overlap < args.chunk_minutes * 60 / 4):
        raise ValueError('--overlap 必須 >= 0 並少於每段長度 1/4')
    if args.retries < 0:
        raise ValueError('--retries 不能為負數')
    source_spec = resolve_source(args.source)
    check_tools(source_spec)
    srt_path = Path(args.output).expanduser().resolve()
    if srt_path.suffix.lower() != '.srt':
        raise ValueError('--output 路徑必須以 .srt 結尾')
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path, json_path = srt_path.with_suffix('.txt'), srt_path.with_suffix('.words.json')
    workdir = srt_path.parent / f'.{srt_path.stem}.gemini-stt-work'
    initialize_workdir(workdir, cache_state(args, source_spec), args.restart)

    media = source_media(source_spec, workdir)
    duration = probe_duration(media)
    core_length = args.chunk_minutes * 60
    total_segments = math.ceil(duration / core_length)
    out(f'影片總長 {duration:.2f}s，分成 {total_segments} 段，模型 {MODEL}')

    if client is None:
        api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
        if not api_key:
            raise RuntimeError('請先設定 GEMINI_API_KEY（或 GOOGLE_API_KEY）環境變數。')
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError('需要 google-genai：py -m pip install -r requirements.txt') from exc
        client = genai.Client(api_key=api_key)

    all_words: list[Word] = []
    try:
        for idx in range(total_segments):
            core_start = idx * core_length
            core_end = min(duration, (idx + 1) * core_length)
            audio_start = max(0.0, core_start - args.overlap)
            audio_end = min(duration, core_end + args.overlap)
            audio_duration = audio_end - audio_start
            result_file = workdir / 'results' / f'{idx:04d}.json'
            if result_file.is_file():
                result = json.loads(result_file.read_text('utf-8'))
                out(f'[{idx+1}/{total_segments}] 讀取已完成暫存')
            else:
                out(f'[{idx+1}/{total_segments}] 轉錄 {audio_start:.1f}s → {audio_end:.1f}s')
                chunk_file = workdir / 'segments' / f'{idx:04d}.wav'
                if not chunk_file.is_file():
                    build_chunk(media, chunk_file, audio_start, audio_duration)
                result = transcribe_segment(client, chunk_file, audio_duration,
                                            args.language, args.diarize, args.retries)
                # Saved only after successful parsing; interrupted jobs can resume.
                atomic_json(result_file, result)
                chunk_file.unlink(missing_ok=True)
            segment_words = [Word(**w) for w in result['words']]
            core_words = accept_core_words(segment_words, audio_start, core_start, core_end,
                                           is_last=(idx == total_segments - 1))
            all_words.extend(core_words)

        cues = make_cues(all_words, max_chars=args.max_chars, max_words=args.max_words,
                         max_seconds=args.max_seconds, gap=args.gap,
                         speaker_labels=args.diarize)
        if not all_words:
            out('警告：整條影片都冇識別出說話；輸出將會係空白。')
        # Generate everything BEFORE replacing final outputs.
        srt_text, txt_text = render_srt(cues), render_txt(cues)
        json_text = json.dumps({'model': MODEL, 'source': source_spec['source'],
                                'duration_seconds': duration, 'words': word_dicts(all_words)},
                               ensure_ascii=False, indent=2)
        for path, content in ((srt_path, srt_text), (txt_path, txt_text), (json_path, json_text)):
            temp = path.with_suffix(path.suffix + '.tmp')
            temp.write_text(content, encoding='utf-8-sig' if path.suffix in ('.txt', '.srt') else 'utf-8')
            temp.replace(path)
        out(f'完成：{len(all_words)} 個詞，{len(cues)} 條字幕')
        out(f'SRT: {srt_path}\nTXT: {txt_path}\nWords JSON: {json_path}')
        if not args.keep_work:
            shutil.rmtree(workdir)
        return srt_path, txt_path, json_path
    finally:
        close = getattr(client, 'close', None)
        if callable(close):
            close()


def main() -> None:
    parser = argparse.ArgumentParser(description='YouTube / media -> Gemini word timestamps -> exact-offset SRT/TXT')
    parser.add_argument('source', help='YouTube 影片 URL 或本地 MP3/MP4/WAV 等檔案')
    parser.add_argument('-o', '--output', default='transcript.srt', help='輸出 SRT 路徑（預設 transcript.srt）')
    parser.add_argument('--language', default='', help='語言代碼，如 ja-JP、en-US、yue-Hant-HK；留空自動偵測')
    parser.add_argument('--diarize', action='store_true', help='要求識別說話者，SRT 加上 speaker 標籤')
    parser.add_argument('--chunk-minutes', type=float, default=10, help='每段核心長度（預設 10 分鐘，最大 25）')
    parser.add_argument('--overlap', type=float, default=2.0, help='每段首尾重疊秒數（預設 2）')
    parser.add_argument('--max-chars', type=int, default=64, help='每條字幕最大顯示寬度（預設 64）')
    parser.add_argument('--max-words', type=int, default=14, help='每條字幕最多單詞／字詞數（預設 14）')
    parser.add_argument('--max-seconds', type=float, default=5.5, help='每條字幕最多秒數（預設 5.5）')
    parser.add_argument('--gap', type=float, default=0.75, help='停頓超過幾秒就分新字幕（預設 0.75）')
    parser.add_argument('--retries', type=int, default=3, help='429/5xx 等暫時錯誤重試次數')
    parser.add_argument('--keep-work', action='store_true', help='完成後保留下載音訊／暫存轉錄結果')
    parser.add_argument('--restart', action='store_true', help='清除程式管理嘅舊暫存，從頭開始')
    args = parser.parse_args()
    if args.max_chars < 8 or args.max_words < 1 or args.max_seconds <= 0 or args.gap < 0:
        parser.error('字幕寬度／字數／秒數／停頓參數無效')
    try:
        run_pipeline(args)
    except KeyboardInterrupt:
        out('\n已中止。完成嘅段落會留喺暫存，重新執行同一指令即可續做。')
        raise SystemExit(130)
    except Exception as exc:
        print(f'錯誤：{exc}\n已完成段落會保留，可修正後重試。', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
