"""Configuration for the YouTube -> Gemini transcription CLI.

YAML is the preferred format. Existing JSON configuration files remain readable
for migration, but all new examples use YAML. Secrets must never be logged.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from urllib.parse import urlparse

import yaml

MODEL = 'gemini-3.5-transcribe'
DEFAULT_GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com'
DEFAULT_SETTINGS = {
    'output': 'transcript.srt',
    'language': '',
    'model': MODEL,
    'diarize': False,
    'chunk_minutes': 10,
    'overlap': 2.0,
    'max_chars': 64,
    'max_words': 14,
    'max_seconds': 5.5,
    'gap': 0.75,
    'retries': 3,
    'keep_work': False,
}
# --restart deliberately stays CLI-only, because it deletes cached data.
CONFIG_FIELDS = frozenset(DEFAULT_SETTINGS) | {'default_language', 'api_base_url', 'api_key'}


def default_config_path() -> Path:
    """Prefer YAML; preserve legacy config.json until the user migrates it."""
    folder = Path(__file__).resolve().parent
    for name in ('config.yaml', 'config.yml', 'config.json'):
        candidate = folder / name
        if candidate.exists():
            return candidate
    return folder / 'config.yaml'


def validate_api_base_url(value: str) -> str | None:
    """Validate a base URL, including user-requested HTTP for remote proxies."""
    if not isinstance(value, str) or not value or value != value.strip() or any(c.isspace() for c in value):
        raise ValueError('API URL 必須係有效網址，不能為空或包含空白。')
    parsed = urlparse(value)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or parsed.params):
        raise ValueError('API URL 必須係 HTTP/HTTPS 根網址（不能含帳密、query 或 fragment）。')
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError('API URL port 無效。') from exc
    if parsed.path.rstrip('/').split('/')[-1].lower() in (
        'v1', 'v1beta', 'v1alpha', 'models', 'interactions', 'files', 'upload'
    ):
        raise ValueError('請填 API Base URL（不含 /v1beta 等版本路徑），SDK 會自動加入版本。')
    normalized = value.rstrip('/')
    return None if normalized == DEFAULT_GEMINI_BASE_URL else normalized


def load_settings_config(path: Path | str | None = None, *, required: bool = False) -> dict:
    """Read YAML safely (or legacy JSON), and reject unknown keys and wrong types."""
    path = Path(path).expanduser() if path is not None else default_config_path()
    if not path.is_file():
        if required or path.exists():
            raise ValueError(f'找唔到有效設定檔：{path}')
        return {}
    try:
        content = path.read_text(encoding='utf-8-sig')
        if path.suffix.lower() in ('.yaml', '.yml'):
            data = yaml.safe_load(content) if content.strip() else {}
        elif path.suffix.lower() == '.json':
            data = json.loads(content)
        else:
            raise ValueError(f'{path}: 只支援 .yaml、.yml 或舊版 .json 設定檔。')
    except yaml.YAMLError as exc:
        # Do not echo malformed YAML text: it might contain an API key.
        raise ValueError(f'讀取 {path} 失敗：YAML 格式錯誤，請檢查縮排及引號。') from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'讀取 {path} 失敗：{exc}') from exc
    if not isinstance(data, dict):
        raise ValueError(f'{path} 必須係 YAML mapping（或舊版 JSON object）。')
    # YAML can have non-string map keys; avoid confusing error messages / sorting.
    if any(not isinstance(key, str) for key in data):
        raise ValueError(f'{path} 所有設定名稱必須係字串。')
    unknown = set(data) - CONFIG_FIELDS
    if unknown:
        raise ValueError(f'{path} 含未知設定：{", ".join(sorted(unknown))}')
    if 'default_language' in data and 'language' in data:
        raise ValueError('請只用 default_language 或 language 其中一個設定。')
    for key, value in data.items():
        if key in ('api_base_url', 'api_key', 'default_language', 'language', 'output', 'model'):
            if not isinstance(value, str):
                raise ValueError(f'{path}: {key} 必須係字串。')
            if key in ('default_language', 'language', 'model') and (
                value != value.strip() or any(c.isspace() for c in value)
            ):
                raise ValueError(f'{path}: {key} 唔可以含空白。')
            if key == 'model' and not value:
                raise ValueError(f'{path}: model 唔可以為空。')
            if key == 'api_key' and value and (
                value != value.strip() or any(c.isspace() for c in value)
            ):
                raise ValueError(f'{path}: api_key 唔可以含空白。')
            if key == 'api_base_url':
                validate_api_base_url(value)
        elif key in ('diarize', 'keep_work'):
            if type(value) is not bool:
                raise ValueError(f'{path}: {key} 必須係 true 或 false。')
        elif key in ('max_chars', 'max_words', 'retries'):
            if type(value) is not int:
                raise ValueError(f'{path}: {key} 必須係整數。')
        else:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f'{path}: {key} 必須係有限數字。')
    return data


def resolve_api_base_url(cli_url: str | None, *, config_path: Path | str | None = None,
                         environ: dict[str, str] | None = None) -> str | None:
    """Priority: CLI > GEMINI_API_BASE_URL > YAML/JSON > Google SDK default."""
    environ = os.environ if environ is None else environ
    if cli_url is not None:
        return validate_api_base_url(cli_url)
    env_url = environ.get('GEMINI_API_BASE_URL', '').strip()
    if env_url:
        return validate_api_base_url(env_url)
    config = load_settings_config(config_path, required=False)
    return validate_api_base_url(config['api_base_url']) if 'api_base_url' in config else None


def resolve_api_key(*, config_path: Path | str | None = None,
                    environ: dict[str, str] | None = None) -> str:
    """Use environment credentials first, falling back to the private YAML key."""
    environ = os.environ if environ is None else environ
    env_key = environ.get('GEMINI_API_KEY') or environ.get('GOOGLE_API_KEY')
    if env_key and env_key.strip():
        return env_key.strip()
    config = load_settings_config(config_path, required=False)
    key = config.get('api_key', '')
    if key:
        return key
    raise RuntimeError('請喺 config.yaml 設定 api_key，或者設定 GEMINI_API_KEY / GOOGLE_API_KEY 環境變數。')
