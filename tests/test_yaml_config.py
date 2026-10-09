"""Offline tests for YAML configuration, HTTP endpoints, and API key precedence."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_settings import (load_settings_config, resolve_api_base_url, resolve_api_key,
                          validate_api_base_url, default_config_path)


class YamlConfigTests(unittest.TestCase):
    def test_yaml_key_language_and_api_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            path.write_text('api_key: "some-private-key"\ndefault_language: ja-JP\napi_base_url: http://remote.test:8080\n')
            data = load_settings_config(path)
            self.assertEqual(data['default_language'], 'ja-JP')
            self.assertEqual(resolve_api_key(config_path=path, environ={}), 'some-private-key')
            self.assertEqual(resolve_api_base_url(None, config_path=path, environ={}), 'http://remote.test:8080')

    def test_env_credentials_override_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yml'
            path.write_text('api_key: "local-key"\n')
            self.assertEqual(resolve_api_key(config_path=path, environ={'GEMINI_API_KEY':'env-key'}), 'env-key')
            self.assertEqual(resolve_api_key(config_path=path, environ={'GOOGLE_API_KEY':'google-key'}), 'google-key')

    def test_yaml_no_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            path.write_text('default_language: ""\n')
            with self.assertRaisesRegex(RuntimeError, 'api_key'):
                resolve_api_key(config_path=path, environ={})

    def test_http_remote_allowed_and_bad_paths_rejected(self):
        self.assertEqual(validate_api_base_url('http://my-proxy.test:8000/'), 'http://my-proxy.test:8000')
        self.assertEqual(validate_api_base_url('http://localhost:8080/'), 'http://localhost:8080')
        for bad in ('http://proxy.test/v1beta', 'http://username:password@proxy.test',
                    'http://proxy.test/?secret=abc', 'ftp://proxy.test'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_api_base_url(bad)

    def test_safe_yaml_disallows_executable_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.yaml'
            path.write_text('api_key: !!python/object/apply:os.system ["echo bad"]')
            with self.assertRaisesRegex(ValueError, '讀取'):
                load_settings_config(path)

    def test_invalid_types_and_unknown_settings(self):
        for item in ('api_key: 123', 'diarize: "true"', 'chunk_minutes: .nan',
                     'unexpected: value', 'api_base_url: "https://x.test/v1beta"'):
            with self.subTest(item=item), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'config.yaml'
                path.write_text(item)
                with self.assertRaises(ValueError):
                    load_settings_config(path)

    def test_legacy_json_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text('{"api_key": "old-key", "default_language": "en-US"}')
            self.assertEqual(resolve_api_key(config_path=path, environ={}), 'old-key')
            self.assertEqual(load_settings_config(path)['default_language'], 'en-US')

    def test_checked_in_yaml_example_is_valid(self):
        path = Path(__file__).resolve().parents[1] / 'config.example.yaml'
        self.assertEqual(load_settings_config(path)['default_language'], 'ja-JP')


if __name__ == '__main__':
    unittest.main()
