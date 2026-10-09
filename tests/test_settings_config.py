"""Config defaults / CLI overrides; no Gemini calls required."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcribe_youtube import (MODEL, cache_state, load_settings_config,
                                parse_cli_args, resolve_api_base_url)


class SettingsConfigTests(unittest.TestCase):
    def test_json_defaults_include_language_and_all_subtitle_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text(json.dumps({
                'api_base_url': 'https://proxy.example.org',
                'default_language': 'yue-Hant-HK',
                'model': 'gemini-custom-transcribe',
                'output': 'my-captions.srt',
                'diarize': True, 'keep_work': True,
                'chunk_minutes': 8, 'overlap': 3, 'max_chars': 40,
                'max_words': 8, 'max_seconds': 4, 'gap': 1.25, 'retries': 5
            }))
            args = parse_cli_args(['video.mp4', '--config', str(path)])
            self.assertEqual(args.language, 'yue-Hant-HK')
            self.assertEqual(args.model, 'gemini-custom-transcribe')
            self.assertEqual(args.output, 'my-captions.srt')
            self.assertEqual((args.chunk_minutes, args.overlap, args.max_chars, args.max_words),
                             (8, 3, 40, 8))
            self.assertEqual((args.max_seconds, args.gap, args.retries), (4, 1.25, 5))
            self.assertTrue(args.diarize)
            self.assertTrue(args.keep_work)
            self.assertEqual(resolve_api_base_url(args.api_base_url, config_path=args.config,
                                                  environ={}), 'https://proxy.example.org')

    def test_cli_overrides_config_and_boolean_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text(json.dumps({'default_language': 'ja-JP', 'model': 'a',
                                        'max_chars': 40, 'diarize': True, 'keep_work': True}))
            args = parse_cli_args(['video.mp4', '--config', str(path), '--language', 'en-US',
                                   '--model', 'b', '--max-chars', '80',
                                   '--no-diarize', '--no-keep-work'])
            self.assertEqual((args.language, args.model, args.max_chars), ('en-US', 'b', 80))
            self.assertFalse(args.diarize)
            self.assertFalse(args.keep_work)

    def test_legacy_language_key_and_auto_detect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text(json.dumps({'language': 'ja-JP'}))
            self.assertEqual(parse_cli_args(['video.mp4', '--config', str(path)]).language, 'ja-JP')
            args = parse_cli_args(['video.mp4', '--config', str(path), '--language', ''])
            self.assertEqual(args.language, '')
            self.assertEqual(args.model, MODEL)

    def test_no_config_reuses_builtin_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                parse_cli_args(['video.mp4', '--config', str(Path(tmp) / 'missing.json')])
            self.assertEqual(ctx.exception.code, 2)
        args = parse_cli_args(['video.mp4'])
        self.assertEqual(args.output, 'transcript.srt')
        self.assertEqual(args.chunk_minutes, 10)
        self.assertFalse(args.diarize)
        self.assertFalse(args.restart)

    def test_unknown_fields_and_bad_types_fail_fast(self):
        for bad in ({'api_key': 123}, {'default_language': 123},
                    {'max_words': 5.2}, {'chunk_minutes': True}, {'diarize': 'yes'},
                    {'retries': -1}, {'max_seconds': 0}, {'model': '  '},
                    {'language': 'ja-JP', 'default_language': 'en-US'},
                    {'restart': True}):
            with self.subTest(data=bad), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'config.json'
                path.write_text(json.dumps(bad))
                with self.assertRaises(SystemExit):
                    parse_cli_args(['video.mp4', '--config', str(path)])

    def test_backend_configuration_env_priority_and_manifest_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text(json.dumps({'api_base_url': 'https://config.example.org'}))
            self.assertEqual(resolve_api_base_url(None, config_path=path,
                             environ={'GEMINI_API_BASE_URL': 'https://env.example.org'}),
                             'https://env.example.org')
            args = parse_cli_args(['video.mp4', '--config', str(path), '--model', 'gemini-new'])
            state = cache_state(args, {'source': 'video.mp4'})
            self.assertEqual(state['model'], 'gemini-new')

    def test_yaml_cli_default_and_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'my-config.yaml'
            path.write_text('api_key: "private-test-key"\ndefault_language: ja-JP\n'
                            'model: gemini-test-transcribe\nmax_chars: 42\n', encoding='utf-8')
            args = parse_cli_args(['video.mp4', '--config', str(path)])
            self.assertEqual((args.language, args.model, args.max_chars),
                             ('ja-JP', 'gemini-test-transcribe', 42))
            # The secret must not be placed in argparse output or cached state.
            self.assertNotIn('api_key', vars(args))
            args2 = parse_cli_args(['video.mp4', '--config', str(path), '--language', 'en-US'])
            self.assertEqual(args2.language, 'en-US')

    def test_sample_config_is_valid(self):
        path = Path(__file__).resolve().parents[1] / 'config.example.yaml'
        self.assertEqual(load_settings_config(path)['default_language'], 'ja-JP')


if __name__ == '__main__':
    unittest.main()
