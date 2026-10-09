"""Check proxy-friendly inline audio and the legacy Files API path offline."""
from __future__ import annotations

import argparse
import base64
import subprocess
from unittest import mock
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_settings import load_settings_config
from transcribe_youtube import (cache_state, effective_chunk_seconds, parse_cli_args,
                                transcribe_segment, run_pipeline)


class FakeFiles:
    def __init__(self):
        self.uploads = 0
        self.deletes = 0

    def upload(self, *, file):
        self.uploads += 1
        return SimpleNamespace(name='files/mock', uri='https://fake.test/files/mock', mime_type='audio/wav')

    def delete(self, *, name):
        self.deletes += 1


class FakeInteractions:
    def __init__(self, error=None):
        self.error = error
        self.input = None
        self.calls = 0

    def create(self, *, model, input, generation_config):
        self.calls += 1
        self.input = input
        if self.error is not None:
            raise self.error
        assert generation_config['transcription_config']['mode']['timestamp_granularities'] == ['word']
        assert model == 'gemini-3.5-transcribe'
        word = SimpleNamespace(type='word_info', text='Hello', speaker=None,
                               start_offset='0.001s', end_offset='0.100s')
        return SimpleNamespace(status='completed', output_text='Hello',
                               steps=[SimpleNamespace(content=[SimpleNamespace(annotations=[word])])])


class FakeClient:
    def __init__(self, error=None):
        self.files = FakeFiles()
        self.interactions = FakeInteractions(error)


class AudioInputTests(unittest.TestCase):
    def test_inline_audio_sends_real_base64_wav_without_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / 'test.wav'
            original = b'RIFF\x00\x00\x00\x00WAVEfmt '+b'\x00'*60
            wav.write_bytes(original)
            fake = FakeClient()
            result = transcribe_segment(fake, wav, .2, 'en-US', False, 0, audio_input='inline')
            self.assertEqual(result['words'][0]['text'], 'Hello')
            self.assertEqual(fake.files.uploads, 0)
            self.assertEqual(fake.files.deletes, 0)
            self.assertEqual(fake.interactions.calls, 1)
            data = fake.interactions.input[0]
            self.assertEqual((data['type'], data['mime_type']), ('audio', 'audio/wav'))
            self.assertNotIn('uri', data)
            self.assertEqual(base64.b64decode(data['data']), original)

    def test_file_audio_preserves_uri_upload_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / 'test.wav'
            wav.write_bytes(b'RIFF...')
            fake = FakeClient()
            transcribe_segment(fake, wav, .2, 'en-US', False, 0, audio_input='file')
            self.assertEqual(fake.files.uploads, 1)
            self.assertEqual(fake.files.deletes, 1)
            self.assertIn('uri', fake.interactions.input[0])
            self.assertNotIn('data', fake.interactions.input[0])

    def test_helpful_error_for_proxy_audio_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / 'test.wav'
            wav.write_bytes(b'RIFF...')
            for mode, expected in [('file','--audio-input inline'),('inline','Interactions API')]:
                fake = FakeClient(RuntimeError('400: gemini-3.5-transcribe requires audio input'))
                with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, expected):
                    transcribe_segment(fake, wav, .2, '', False, 2, audio_input=mode)
                self.assertEqual(fake.interactions.calls, 1)
                self.assertEqual(fake.files.uploads, int(mode=='file'))
                self.assertEqual(fake.files.deletes, int(mode=='file'))

    def test_yaml_cli_and_cache_manifest_switches_mode_without_key(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config.yaml'
            path.write_text('audio_input: inline\napi_key: "some-secret"\ndefault_language: en-US\n')
            config=load_settings_config(path)
            self.assertEqual(config['audio_input'],'inline')
            args=parse_cli_args(['video.mp4','--config',str(path)])
            self.assertEqual(args.audio_input,'inline')
            self.assertNotIn('api_key',vars(args))
            manifest=cache_state(args,{'source':'video.mp4'})
            self.assertEqual(manifest['audio_input'],'inline')
            self.assertNotIn('api_key',manifest)
            args2=parse_cli_args(['video.mp4','--config',str(path),'--audio-input','file'])
            self.assertEqual(args2.audio_input,'file')
            self.assertNotIn('audio_input',cache_state(args2,{'source':'video.mp4'}))

    def test_inline_caps_at_four_minutes_and_manifest_tracks_effective_size(self):
        args = argparse.Namespace(chunk_minutes=10, overlap=2, audio_input='inline',
                                  language='en-US', diarize=False, model='gemini-3.5-transcribe')
        self.assertEqual(effective_chunk_seconds(args, 'inline'), 240.0)
        self.assertEqual(effective_chunk_seconds(args, 'file'), 600.0)
        state = cache_state(args, {'source': 'movie.mp4'})
        self.assertEqual(state['effective_chunk_seconds'], 240.0)
        args.chunk_minutes = 4
        self.assertEqual(effective_chunk_seconds(args, 'inline'), 240.0)
        self.assertNotIn('effective_chunk_seconds', cache_state(args, {'source': 'movie.mp4'}))
        args.overlap = 120
        with self.assertRaisesRegex(ValueError, 'overlap'):
            effective_chunk_seconds(args, 'inline')

    def test_inline_413_gives_specific_guidance(self):
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / 'small.wav'
            wav.write_bytes(b'RIFF' + b'\0' * 100)
            fake = FakeClient(RuntimeError('Error code: 413 - Inline request exceeds the 20 MB API limit'))
            with self.assertRaisesRegex(RuntimeError, '--chunk-minutes 2 --restart'):
                transcribe_segment(fake, wav, 0.2, '', False, 0, audio_input='inline')
            self.assertEqual(fake.files.uploads, 0)

    def test_inline_full_pipeline_auto_resizes_and_keeps_timestamps(self):
        # Reduce the cap ONLY in the test, so 13 seconds exercises three chunks.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav = root / 'input.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'lavfi',
                            '-i', 'anullsrc=r=16000:cl=mono', '-t', '13', '-c:a', 'pcm_s16le',
                            '-y', str(wav)], check=True)
            args = argparse.Namespace(source=str(wav), output=str(root / 'out.srt'),
                                      language='en-US', model='gemini-3.5-transcribe',
                                      diarize=False, chunk_minutes=0.5, overlap=0.5,
                                      max_chars=64, max_words=14, max_seconds=5.5,
                                      gap=.75, retries=0, keep_work=True,
                                      restart=False, audio_input='inline', config=None,
                                      api_base_url=None)
            fake = FakeClient()
            with mock.patch('transcribe_youtube.INLINE_MAX_CORE_SECONDS', 5):
                output_paths = run_pipeline(args, client=fake)
            self.assertEqual(fake.interactions.calls, 3)
            self.assertEqual(fake.files.uploads, 0)
            self.assertEqual(len(output_paths), 3)
            manifest = json.loads((root / '.out.gemini-stt-work' / 'manifest.json').read_text())
            self.assertEqual(manifest['effective_chunk_seconds'], 5.0)
            self.assertTrue((root / 'out.srt').is_file())

    def test_reject_bad_audio_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bad.yaml'
            for val in ['none','base64','0','true']:
                path.write_text(f'audio_input: {val}\n')
                with self.subTest(val=val),self.assertRaises(ValueError):
                    load_settings_config(path)


if __name__=='__main__':
    unittest.main()
