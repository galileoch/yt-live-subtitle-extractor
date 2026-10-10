"""Integration smoke test with real FFmpeg and simulated Gemini API. No API key needed."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transcribe_youtube import run_pipeline


class FakeFiles:
    def __init__(self):
        self.uploaded = []
        self.deleted = []

    def upload(self, file: str):
        path = Path(file)
        assert path.is_file() and path.stat().st_size > 100
        name = f'files/test_{len(self.uploaded)}'
        self.uploaded.append((name, file))
        return SimpleNamespace(name=name, uri=f'https://api.invalid/{path.stem}', mime_type='audio/wav')

    def delete(self, name: str):
        self.deleted.append(name)


class FakeInteractions:
    def __init__(self, fail_on: int | None = None, model: str = 'gemini-3.5-transcribe'):
        self.calls = 0
        self.fail_on = fail_on
        self.model = model

    def create(self, *, model, input, generation_config):
        i = self.calls
        self.calls += 1
        if i == self.fail_on:
            raise RuntimeError('mock simulated Gemini error')
        assert model == self.model
        assert generation_config['transcription_config']['mode']['timestamp_granularities'] == ['word']
        chunk_index = int(input[0]['uri'].rsplit('/', 1)[-1])
        text = ('私', 'Hello', 'おはよう')[chunk_index]
        # The second and third chunks start 2 seconds before their core window.
        begin = .1 if chunk_index == 0 else 2.1
        annotation = SimpleNamespace(type='word_info', text=text, speaker=None,
                                     start_offset=f'{begin:.3f}s', end_offset=f'{begin+.35:.3f}s')
        return SimpleNamespace(status='completed', output_text=text,
                               steps=[SimpleNamespace(content=[SimpleNamespace(annotations=[annotation])])])


class FakeClient:
    def __init__(self, fail_on: int | None = None, model: str = 'gemini-3.5-transcribe'):
        self.files = FakeFiles()
        self.interactions = FakeInteractions(fail_on, model)
        self.closed = False

    def close(self):
        self.closed = True


def args_for(path, out):
    return argparse.Namespace(source=str(path), output=str(out), language='ja-JP',
                              diarize=False, chunk_minutes=0.5, overlap=2,
                              max_chars=64, max_words=14, max_seconds=5.5,
                              gap=.75, retries=0, keep_work=True, restart=False)


class PipelineTests(unittest.TestCase):
    def test_full_pipeline_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'mock_input.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'lavfi',
                            '-i', 'anullsrc=r=16000:cl=mono', '-t', '65', '-c:a', 'pcm_s16le',
                            '-y', str(video)], check=True)
            output = root / 'sample.srt'
            args = args_for(video, output)
            first = FakeClient(fail_on=1)
            with self.assertRaisesRegex(RuntimeError, 'mock simulated'):
                run_pipeline(args, client=first)
            self.assertTrue((root / '.sample.gemini-stt-work' / 'results' / '0000.json').is_file())
            self.assertTrue(first.closed)
            # Resume the first completed chunk without re-billing; second attempt uses new fake session.
            retry = FakeClient()
            outputs = run_pipeline(args, client=retry)
            self.assertTrue(retry.closed)
            self.assertEqual(retry.interactions.calls, 2)
            self.assertEqual(len(retry.files.deleted), len(retry.files.uploaded))
            srt = output.read_text('utf-8-sig')
            self.assertIn('私', srt)
            self.assertIn('Hello', srt)
            self.assertIn('おはよう', srt)
            self.assertIn('00:00:30,', srt)
            self.assertIn('00:01:00,', srt)
            self.assertEqual(len(outputs), 3)
            self.assertTrue(output.with_suffix('.txt').is_file())
            self.assertIn('"start": 60.1', output.with_suffix('.words.json').read_text('utf-8'))
            # Reformat without calling Gemini again
            args.max_words = 1
            cached = FakeClient()
            run_pipeline(args, client=cached)
            self.assertEqual(cached.interactions.calls, 0)

    def test_preloaded_config_skips_yaml_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav = root / 'short.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error',
                            '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono',
                            '-t', '2', '-c:a', 'pcm_s16le', '-y', str(wav)], check=True)
            args = args_for(wav, root / 'short.srt')
            args.config = str(root / 'does-not-exist.yaml')
            fake = FakeClient()
            settings = {'api_base_url': 'https://proxy.example.org',
                        'api_key': 'test-private-key'}
            with mock.patch('transcribe_youtube.load_settings_config',
                            side_effect=AssertionError('unexpected YAML reload')):
                run_pipeline(args, client=fake, settings_config=settings)
            self.assertEqual(fake.interactions.calls, 1)
            manifest = (root / '.short.gemini-stt-work' / 'manifest.json').read_text()
            self.assertNotIn('test-private-key', manifest)

    def test_configured_model_used_for_actual_transcribe_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'short.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'lavfi',
                            '-i', 'anullsrc=r=16000:cl=mono', '-t', '2', '-c:a', 'pcm_s16le',
                            '-y', str(video)], check=True)
            args = args_for(video, root / 'short.srt')
            args.model = 'gemini-test-transcribe'
            fake = FakeClient(model=args.model)
            run_pipeline(args, client=fake)
            self.assertEqual(fake.interactions.calls, 1)
            self.assertIn('"model": "gemini-test-transcribe"',
                          (root / 'short.words.json').read_text('utf-8'))



if __name__ == '__main__':
    unittest.main()
