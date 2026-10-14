"""Offline regression for the preserved Mission 10 Windows stdin failure."""
import io
import json
import unittest
from unittest.mock import patch

from data import store
from pipeline_common import ROOT, Invalid
from processing.evidence_contract import verify_version


FAILED_RUN = ROOT / 'runs/editorial-live-3bdc878f2f014167957b6ad2b83a9024'
NON_ASCII_ITEMS = {
    'feed:bebca6424b0efee5', 'feed:d08507c6dd8f3ff1',
    'feed:8348f8f60db16b79', 'feed:47e5fa4d38e94338',
    'feed:324e4b056d3ee600',
}


class ParsedOnly(Exception):
    """Stop after the real upsert parser, before any database/file writes."""


class StoreUTF8Tests(unittest.TestCase):
    def parse_upsert(self, raw):
        records = []
        original_loads = json.loads

        def capture(value, *args, **kwargs):
            result = original_loads(value, *args, **kwargs)
            if isinstance(result, dict) and 'item_id' in result:
                records.append(result)
            return result

        # Deliberately emulate the failing Windows text stream. The production
        # parser must use its bytes, not this CP1252 decoding layer.
        stream = io.TextIOWrapper(io.BytesIO(raw), encoding='cp1252',
                                  errors='surrogateescape')
        try:
            with patch.object(store.sys, 'stdin', stream), \
                 patch.object(store.json, 'loads', side_effect=capture), \
                 patch.object(store, 'init_store', side_effect=ParsedOnly):
                with self.assertRaises(ParsedOnly):
                    store.upsert(FAILED_RUN)
        finally:
            stream.close()
        return records

    def test_archived_58_records_and_five_titles_validate(self):
        raw = (FAILED_RUN / 'items.jsonl').read_bytes()
        records = self.parse_upsert(raw)
        expected = [json.loads(line) for line in raw.decode('utf-8').splitlines()
                    if line.strip()]
        self.assertEqual(len(records), 58)
        self.assertEqual(records, expected)
        identified = [x for x in records if x['item_id'] in NON_ASCII_ITEMS]
        self.assertEqual({x['item_id'] for x in identified}, NON_ASCII_ITEMS)
        self.assertTrue(all(any(ord(c) > 127 for c in x['title'])
                            for x in identified))
        for item in records:
            with self.subTest(item_id=item['item_id']):
                verify_version(item, (ROOT / item['text_path']).read_bytes())

    def test_fixture_reproduces_original_cp1252_metadata_failure(self):
        line = (FAILED_RUN / 'items.jsonl').read_bytes().splitlines()[6]
        correct = json.loads(line.decode('utf-8'))
        corrupted = json.loads(line.decode('cp1252'))
        self.assertEqual(correct['item_id'], 'feed:bebca6424b0efee5')
        self.assertNotEqual(correct['title'], corrupted['title'])
        text = (ROOT / correct['text_path']).read_bytes()
        verify_version(correct, text)
        with self.assertRaisesRegex(Invalid, 'Evidence version/text integrity failure'):
            verify_version(corrupted, text)

    def test_invalid_utf8_refused_before_database_initialization(self):
        stream = io.TextIOWrapper(io.BytesIO(b'\xff\n'), encoding='cp1252')
        try:
            with patch.object(store.sys, 'stdin', stream), \
                 patch.object(store, 'init_store') as initialize:
                with self.assertRaises(UnicodeDecodeError):
                    store.upsert(FAILED_RUN)
                initialize.assert_not_called()
        finally:
            stream.close()

    def test_malformed_json_refused_before_database_initialization(self):
        stream = io.TextIOWrapper(io.BytesIO(b'{broken}\n'), encoding='cp1252')
        try:
            with patch.object(store.sys, 'stdin', stream), \
                 patch.object(store, 'init_store') as initialize:
                with self.assertRaises(json.JSONDecodeError):
                    store.upsert(FAILED_RUN)
                initialize.assert_not_called()
        finally:
            stream.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
