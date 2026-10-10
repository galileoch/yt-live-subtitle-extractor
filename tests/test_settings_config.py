"""Config defaults / CLI overrides; no Gemini calls required."""
from __future__ import annotations

import yaml
from unittest import mock
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcribe_youtube import MODEL, cache_state, parse_cli_args
from app_settings import (load_settings_config, resolve_api_base_url,
                          resolve_api_key, default_config_path)


class SettingsConfigTests(unittest.TestCase):
    def test_yaml_defaults_include_language_and_all_subtitle_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            path.write_text(yaml.safe_dump({
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
            path = Path(tmp) / 'config.yaml'
            path.write_text(yaml.safe_dump({'default_language': 'ja-JP', 'model': 'a',
                                        'max_chars': 40, 'diarize': True, 'keep_work': True}))
            args = parse_cli_args(['video.mp4', '--config', str(path), '--language', 'en-US',
                                   '--model', 'b', '--max-chars', '80',
                                   '--no-diarize', '--no-keep-work'])
            self.assertEqual((args.language, args.model, args.max_chars), ('en-US', 'b', 80))
            self.assertFalse(args.diarize)
            self.assertFalse(args.keep_work)

    def test_legacy_language_key_and_auto_detect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            path.write_text(yaml.safe_dump({'language': 'ja-JP'}))
            self.assertEqual(parse_cli_args(['video.mp4', '--config', str(path)]).language, 'ja-JP')
            args = parse_cli_args(['video.mp4', '--config', str(path), '--language', ''])
            self.assertEqual(args.language, '')
            self.assertEqual(args.model, MODEL)

    def test_no_config_reuses_builtin_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                parse_cli_args(['video.mp4', '--config', str(Path(tmp) / 'missing.yaml')])
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
                path = Path(tmp) / 'config.yaml'
                path.write_text(yaml.safe_dump(bad))
                with self.assertRaises(SystemExit):
                    parse_cli_args(['video.mp4', '--config', str(path)])

    def test_backend_configuration_env_priority_and_manifest_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            path.write_text(yaml.safe_dump({'api_base_url': 'https://config.example.org'}))
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

    def test_cli_can_return_preloaded_settings_without_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'secure.yaml'
            path.write_text('api_key: "test-private-key"\ndefault_language: en-US\n')
            args, config = parse_cli_args(['video.mp4', '--config', str(path)],
                                          return_config=True)
            self.assertEqual(config['api_key'], 'test-private-key')
            self.assertEqual(args.language, 'en-US')
            self.assertNotIn('api_key', vars(args))
            self.assertNotIn('test-private-key', str(cache_state(args, {'source': 'video.mp4'})))

    def test_yml_extension_and_proxy_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yml'
            path.write_text('api_key: "test-key"\ndefault_language: ja-JP\n'
                            'api_base_url: http://remote.test:8080\n')
            self.assertEqual(load_settings_config(path)['default_language'], 'ja-JP')
            self.assertEqual(resolve_api_key(config_path=path, environ={}), 'test-key')
            self.assertEqual(resolve_api_base_url(None, config_path=path, environ={}),
                             'http://remote.test:8080')

    def test_env_key_priority_and_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            path.write_text('api_key: "stored-key"\n')
            self.assertEqual(resolve_api_key(config_path=path,
                             environ={'GEMINI_API_KEY': 'env-key',
                                      'GOOGLE_API_KEY': 'another-key'}), 'env-key')
            self.assertEqual(resolve_api_key(config_path=path,
                             environ={'GOOGLE_API_KEY': 'google-key'}), 'google-key')
            path.write_text('default_language: ""\n')
            with self.assertRaisesRegex(RuntimeError, 'api_key'):
                resolve_api_key(config_path=path, environ={})

    def test_yaml_unsafe_tags_and_malformed_values_rejected(self):
        for content in ('api_key: !!python/object/apply:os.system ["echo bad"]',
                        'api_base_url: [broken', '[]', 'api_key: 123',
                        'diarize: "true"', 'chunk_minutes: .nan',
                        'unexpected: value', 'api_base_url: "https://x.test/v1beta"'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'config.yaml'
                path.write_text(content)
                with self.assertRaises(ValueError):
                    load_settings_config(path)

    def test_legacy_json_rejected_and_default_path_ignores_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'config.json'
            path.write_text('{"api_key":"old-key"}')
            with self.assertRaisesRegex(ValueError, '只支援'):
                load_settings_config(path)
            with self.assertRaises(SystemExit) as ctx:
                parse_cli_args(['video.mp4', '--config', str(path)])
            self.assertEqual(ctx.exception.code, 2)
            with mock.patch('app_settings.__file__', str(root / 'app_settings.py')):
                self.assertEqual(default_config_path(), root / 'config.yaml')
                (root / 'config.yml').write_text('default_language: en-US\n')
                self.assertEqual(default_config_path(), root / 'config.yml')
                (root / 'config.yaml').write_text('default_language: ja-JP\n')
                self.assertEqual(default_config_path(), root / 'config.yaml')

    def test_sample_config_is_valid(self):
        path = Path(__file__).resolve().parents[1] / 'config.example.yaml'
        self.assertEqual(load_settings_config(path)['default_language'], 'ja-JP')


if __name__ == '__main__':
    unittest.main()
