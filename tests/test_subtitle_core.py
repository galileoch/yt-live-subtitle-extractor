from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from subtitle_core import (Word, accept_core_words, char_width, make_cues,
                           offset_seconds, parse_annotations, render_srt, words_to_text)
from transcribe_youtube import (cache_state, initialize_workdir, is_transient,
                                make_config, resolve_source, youtube_url)


class CoreTests(unittest.TestCase):
    def test_duration_parse(self):
        self.assertEqual(offset_seconds('1.250s'), 1.25)
        self.assertEqual(offset_seconds('0s'), 0)
        for bad in ('foo', '-1s', 'nan', None):
            with self.assertRaises(ValueError):
                offset_seconds(bad)

    def test_parse_annotations_dict_and_sdk_object(self):
        item = SimpleNamespace(type='word_info', text='Hello', speaker='spk_1',
                               start_offset='0.100s', end_offset='0.400s')
        response = SimpleNamespace(steps=[SimpleNamespace(content=[SimpleNamespace(annotations=[item])])])
        words = parse_annotations(response, 1.0)
        self.assertEqual(words, [Word('Hello', 0.1, 0.4, 'spk_1')])
        self.assertEqual(parse_annotations({'steps': [{'content': [{'annotations': [
            {'type': 'word_info', 'text': '早晨', 'start_offset': '0.2s', 'end_offset': '0.5s'}
        ]}]}]}, 1), [Word('早晨', .2, .5, '')])

    def test_invalid_timestamps_not_forged(self):
        for start, end in [('0.2s', '10s'), ('0.5s', '0.1s')]:
            with self.assertRaises(ValueError):
                parse_annotations({'steps': [{'content': [{'annotations': [
                    {'type': 'word_info', 'text': 'Hey', 'start_offset': start, 'end_offset': end}
                ]}]}]}, 1)

    def test_overlap_midpoint_dedup(self):
        # Two overlapping chunks: 0-10 core; 10-20 core, second starts at 8.
        first = [Word('A', 9.5, 9.9), Word('B', 10.0, 10.6)]
        second = [Word('A', 1.5, 1.9), Word('B', 2, 2.6), Word('C', 3, 3.4)]
        result = (accept_core_words(first, 0, 0, 10, False) +
                  accept_core_words(second, 8, 10, 20, True))
        self.assertEqual([w.text for w in result], ['A', 'B', 'C'])
        self.assertAlmostEqual(result[1].start, 10)

    def test_punctuation_and_cjk_spacing(self):
        def ws(seq):
            return [Word(s, i, i + .1) for i, s in enumerate(seq)]
        self.assertEqual(words_to_text(ws(['Hello', ',', 'world', '!'])), 'Hello, world!')
        self.assertEqual(words_to_text(ws(['今日', 'は', '晴れ', '。'])), '今日は晴れ。')
        self.assertEqual(words_to_text(ws(['我', '用', 'Python', '寫', 'code'])), '我用Python寫code')
        self.assertEqual(char_width('香港AB'), 6)

    def test_srt_clamps_at_next_subtitle_and_time_format(self):
        words = [Word('Hi', .0, .3), Word('there', .4, .7), Word('Okay', .85, 1.2)]
        cues = make_cues(words, max_words=2)
        self.assertEqual(len(cues), 2)
        self.assertLessEqual(cues[0].end, cues[1].start)
        self.assertIn('00:00:00,000', render_srt(cues))
        self.assertIn('-->', render_srt(cues))

    def test_speaker_changes(self):
        cues = make_cues([Word('Hello', 0, .5, 'spk_1'), Word('world', .5, 1, 'spk_2')],
                         speaker_labels=True)
        self.assertEqual(len(cues), 2)
        self.assertTrue(cues[1].text.startswith('[spk_2]'))

    def test_domain_safety(self):
        self.assertTrue(youtube_url('https://youtu.be/XYZ'))
        self.assertTrue(youtube_url('https://youtube.com/shorts/XYZ'))
        self.assertFalse(youtube_url('https://youtube.com.evil.com/video'))
        with self.assertRaises(ValueError):
            resolve_source('https://example.com/file')

    def test_config(self):
        self.assertEqual(make_config('ja-JP', True)['transcription_config']['mode']['diarization_mode'], 'speaker')
        self.assertEqual(make_config('', False)['transcription_config']['language_codes'], [])

    def test_workspace_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'innocent').write_text('hello')
            with self.assertRaises(RuntimeError):
                initialize_workdir(root, {'test': 1}, True)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'work'
            initialize_workdir(root, {'test': 1}, False)
            initialize_workdir(root, {'test': 1}, False)
            with self.assertRaises(RuntimeError):
                initialize_workdir(root, {'test': 2}, False)

    def test_retry_detection(self):
        self.assertTrue(is_transient(Exception('429 RESOURCE_EXHAUSTED')))
        self.assertFalse(is_transient(Exception('401 invalid API key')))


    def test_isolated_bad_word_time_is_discarded_without_making_up_timestamps(self):
        good = [
            {'type': 'word_info', 'text': f'字{i}',
             'start_offset': f'{i + 0.1:.3f}s',
             'end_offset': f'{i + 0.4:.3f}s'}
            for i in range(40)
        ]
        invalid = {'type': 'word_info', 'text': '力',
                   'start_offset': '19.900s', 'end_offset': '10.100s'}
        good.insert(20, invalid)
        response = {'steps': [{'content': [{'annotations': good}]}]}
        skipped = []
        parsed = parse_annotations(
            response, 124, skip_bad_timestamps=True, skipped=skipped,
        )
        self.assertEqual(len(parsed), 40)
        self.assertEqual(len(skipped), 1)
        self.assertIn('19.900-10.100s', skipped[0])
        self.assertTrue(all(w.start <= w.end for w in parsed))
        self.assertNotIn('力', [w.text for w in parsed])

    def test_broad_timestamp_corruption_still_fails(self):
        good = [
            {'type': 'word_info', 'text': f'good{i}', 'start_offset': f'{i}s',
             'end_offset': f'{i + .2}s'}
            for i in range(25)
        ]
        bad = [
            {'type': 'word_info', 'text': f'bad{i}', 'start_offset': '19.900s',
             'end_offset': '10.100s'}
            for i in range(3)
        ]
        with self.assertRaisesRegex(ValueError, 'exceed recovery limit'):
            parse_annotations(
                {'steps': [{'content': [{'annotations': good + bad}]}]},
                124, skip_bad_timestamps=True,
            )

    def test_all_invalid_timestamps_still_fail(self):
        with self.assertRaisesRegex(ValueError, 'exceed recovery limit'):
            parse_annotations({
                'steps': [{'content': [{'annotations': [{
                    'type': 'word_info', 'text': 'a',
                    'start_offset': '5.000s', 'end_offset': '1.000s',
                }]}]}],
            }, 124, skip_bad_timestamps=True)

    def test_small_out_of_range_issue_does_not_change_valid_timestamps(self):
        annotations = [
            {'type': 'word_info', 'text': 'right',
             'start_offset': '1.2s', 'end_offset': '1.4s'},
            {'type': 'word_info', 'text': 'wrong',
             'start_offset': '160s', 'end_offset': '160.4s'},
            {'type': 'word_info', 'text': 'again',
             'start_offset': '2.0s', 'end_offset': '2.2s'},
        ]
        skipped = []
        result = parse_annotations({
            'steps': [{'content': [{'annotations': annotations}]}],
        }, 124, skip_bad_timestamps=True, skipped=skipped)
        self.assertEqual([(w.text, w.start, w.end) for w in result],
                         [('right', 1.2, 1.4), ('again', 2.0, 2.2)])
        self.assertEqual(len(skipped), 1)


if __name__ == '__main__':
    unittest.main()
