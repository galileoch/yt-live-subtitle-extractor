"""Pure subtitle timing/formatting helpers (no API or network dependency)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
import unicodedata
from typing import Any


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    speaker: str = ""


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str
    speaker: str = ""


def offset_seconds(value: Any) -> float:
    """Gemini word offsets are normally strings like '1.234s'."""
    if hasattr(value, 'total_seconds'):
        return float(value.total_seconds())
    if isinstance(value, (float, int)):
        seconds = float(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not re.fullmatch(r'\d+(?:\.\d+)?s?', raw):
            raise ValueError(f'Invalid Gemini offset: {value!r}')
        seconds = float(raw.removesuffix('s'))
    else:
        raise ValueError(f'Invalid Gemini offset type: {type(value).__name__}')
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f'Invalid Gemini offset: {value!r}')
    return seconds


def get_attr(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def parse_annotations(interaction: Any, duration: float) -> list[Word]:
    """Parse Interactions API word_info annotations without guessing timestamps."""
    words: list[Word] = []
    for step in get_attr(interaction, 'steps', []) or []:
        for content in get_attr(step, 'content', []) or []:
            for item in get_attr(content, 'annotations', []) or []:
                if str(get_attr(item, 'type', '')).lower() != 'word_info':
                    continue
                text = str(get_attr(item, 'text', '') or '').strip()
                if not text:
                    continue
                start_raw = get_attr(item, 'start_offset')
                end_raw = get_attr(item, 'end_offset')
                if start_raw is None or end_raw is None:
                    raise ValueError(f'Gemini returned word without timing: {text!r}')
                start, end = offset_seconds(start_raw), offset_seconds(end_raw)
                # Do NOT manufacture timestamps if the model returned invalid offsets.
                if end < start or start > duration + 0.5 or end > duration + 0.5:
                    raise ValueError(f'Gemini word timestamp out of audio range: {text!r} {start:.3f}-{end:.3f}s (audio {duration:.3f}s)')
                speaker = str(get_attr(item, 'speaker', '') or '')
                words.append(Word(text, min(start, duration), min(end, duration), speaker))
    return sorted(words, key=lambda w: (w.start, w.end))


def accept_core_words(words: list[Word], audio_start: float, core_start: float, core_end: float, is_last: bool) -> list[Word]:
    """Keep words centered inside a chunk's non-overlap core; convert to global time."""
    selected = []
    for word in words:
        start, end = word.start + audio_start, word.end + audio_start
        mid = (start + end) / 2
        if core_start <= mid < core_end or (is_last and core_start <= mid <= core_end + 0.05):
            selected.append(Word(word.text, start, end, word.speaker))
    return selected


def _latin_alnum(c: str) -> bool:
    # Real Unicode CJK shouldn't get spaces between individual speech tokens.
    return bool(c and c.isascii() and (c.isalnum() or c in "'\""))


def words_to_text(words: list[Word]) -> str:
    pieces: list[str] = []
    prior = ''
    for w in words:
        token = w.text.strip()
        if not token:
            continue
        if prior and _latin_alnum(token[0]) and (_latin_alnum(prior[-1]) or prior[-1] in ',;:!?'):
            pieces.append(' ')
        pieces.append(token)
        prior = token
    return ''.join(pieces)


def char_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)


def wrap_text(text: str, width: int = 36) -> str:
    """Wrap at a whitespace opportunity, otherwise at a CJK character boundary."""
    if char_width(text) <= width:
        return text
    split = 0
    consumed = 0
    for i, c in enumerate(text):
        consumed += char_width(c)
        if consumed > width:
            break
        if c == ' ':
            split = i
    if split <= 0:
        consumed = 0
        for i, c in enumerate(text):
            consumed += char_width(c)
            if consumed > width:
                split = i
                break
    if split <= 0 or split >= len(text):
        return text
    return text[:split].rstrip() + '\n' + text[split:].lstrip()


def make_cues(words: list[Word], *, max_chars: int = 64, max_words: int = 14,
              max_seconds: float = 5.5, gap: float = 0.75,
              speaker_labels: bool = False) -> list[Cue]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.start, w.end))
    groups: list[list[Word]] = []
    current: list[Word] = []

    def commit() -> None:
        nonlocal current
        if current:
            groups.append(current)
            current = []

    for w in ordered:
        if w.end < w.start:
            continue
        if current:
            prev = current[-1]
            too_long = w.end - current[0].start > max_seconds
            too_many_words = len(current) >= max_words
            too_many_chars = char_width(words_to_text(current + [w])) > max_chars
            speaker_changed = w.speaker and prev.speaker and w.speaker != prev.speaker
            long_pause = w.start - prev.end > gap
            punctuation_boundary = bool(re.search(r'[.!?。！？]$', prev.text.strip())) and w.start - prev.end >= 0.12
            if too_long or too_many_words or too_many_chars or speaker_changed or long_pause or punctuation_boundary:
                commit()
        current.append(w)
    commit()

    cues: list[Cue] = []
    for i, group in enumerate(groups):
        start = max(0, group[0].start - 0.06)
        end = group[-1].end + 0.14
        next_start = groups[i + 1][0].start if i + 1 < len(groups) else None
        if next_start is not None:
            end = min(end, max(group[-1].end, next_start - 0.03))
        if cues:
            start = max(start, cues[-1].end)
        if end <= start:
            end = start + 0.1
        speaker = group[0].speaker
        text = words_to_text(group)
        if speaker_labels and speaker:
            text = f'[{speaker}] {text}'
        text = wrap_text(text)
        cues.append(Cue(start, end, text, speaker))
    return cues


def srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def render_srt(cues: list[Cue]) -> str:
    return ''.join(f'{i}\n{srt_time(c.start)} --> {srt_time(c.end)}\n{c.text}\n\n'
                   for i, c in enumerate(cues, 1))


def render_txt(cues: list[Cue]) -> str:
    return ''.join(cue.text.replace('\n', ' ') + '\n' for cue in cues)


def word_dicts(words: list[Word]) -> list[dict]:
    return [asdict(w) for w in words]
