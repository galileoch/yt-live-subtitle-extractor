"""No-network tests for configurable Gemini API base URL."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transcribe_youtube import cache_state, gemini_client_options
from app_settings import resolve_api_base_url, resolve_api_key, validate_api_base_url


class ApiConfigTests(unittest.TestCase):
    def test_sdk_default_when_no_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            actual = resolve_api_base_url(None, config_path=Path(tmp) / 'missing.json', environ={})
        self.assertIsNone(actual)
        self.assertEqual(gemini_client_options('secret-key', actual), {'api_key': 'secret-key'})
        self.assertIsNone(validate_api_base_url('https://generativelanguage.googleapis.com/'))

    def test_config_file_and_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            path.write_text('api_base_url: "https://config.example.org/gemini/"\n')
            self.assertEqual(resolve_api_base_url(None, config_path=path, environ={}),
                             'https://config.example.org/gemini')
            self.assertEqual(resolve_api_base_url(None, config_path=path,
                                                  environ={'GEMINI_API_BASE_URL': 'https://env.example.org/'}),
                             'https://env.example.org')
            self.assertEqual(resolve_api_base_url('https://cli.example.org/', config_path=path,
                                                  environ={'GEMINI_API_BASE_URL': 'https://env.example.org'}),
                             'https://cli.example.org')

    def test_sdk_receives_override(self):
        self.assertEqual(gemini_client_options('my-key', 'https://proxy.example.org'),
                         {'api_key': 'my-key', 'http_options': {'base_url': 'https://proxy.example.org'}})

    def test_reject_unsafe_or_full_endpoint(self):
        invalid = ('', 'https://user:pass@example.com',
                   'https://example.com?key=secret', 'https://example.com/#frag',
                   'https://example.com/v1beta', 'https://example.com/v1', 'https://example.com/interactions',
                   'https://example.com:abc', 'https://example.com/method path')
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_api_base_url(url)
        self.assertEqual(validate_api_base_url('http://localhost:8080/'), 'http://localhost:8080')
        self.assertEqual(validate_api_base_url('http://example.com/'), 'http://example.com')

    def test_bad_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            for content in ('api_base_url: [broken', '[]', 'other: ok', 'api_base_url: 123'):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    resolve_api_base_url(None, config_path=path, environ={})

    def test_preloaded_settings_skip_file_reads(self):
        from unittest import mock

        settings = {'api_base_url': 'https://proxy.example.org', 'api_key': 'test-private-key'}
        with mock.patch('app_settings.load_settings_config',
                        side_effect=AssertionError('unexpected second file read')):
            self.assertEqual(resolve_api_base_url(
                None, config_path='missing.yaml', environ={}, settings_config=settings),
                'https://proxy.example.org')
            self.assertEqual(resolve_api_key(
                config_path='missing.yaml', environ={}, settings_config=settings),
                'test-private-key')

    def test_cache_separates_custom_endpoint_and_keeps_legacy_default(self):
        args = argparse.Namespace(language='', diarize=False, chunk_minutes=10, overlap=2)
        src = {'source': 'some.mp3'}
        default = cache_state(args, src)
        custom = cache_state(args, src, 'https://proxy.example.com')
        self.assertNotIn('api_base_url', default)
        self.assertEqual(custom['api_base_url'], 'https://proxy.example.com')


if __name__ == '__main__':
    unittest.main()
