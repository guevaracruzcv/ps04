"""Offline RFC -0000 regression; synthetic RSS, no collection or audio fetch."""
import json
import unittest
import xml.etree.ElementTree as ET
from datetime import date

from collectors.contracts import rss_records
from pipeline_common import ROOT, Invalid, digest


class RSSDateTests(unittest.TestCase):
    def setUp(self):
        self.source = next(x for x in json.loads(
            (ROOT / 'config/podcast_sources.json').read_text(encoding='utf-8'))
            if x['source_id'] == 'reuters-econ-world')
        self.corpus_path = ROOT / 'editorial/rss_integration_v3/corpus_expanded_v3.jsonl'
        self.archive = next(json.loads(line) for line in
            self.corpus_path.read_text(encoding='utf-8').splitlines()
            if line.strip() and json.loads(line)['item_id'] == 'podcast:54e93bb11c79c9a2fc0b')

    def raw(self, pub, title='AI at work', enclosure=True):
        root = ET.Element('rss')
        item = ET.SubElement(ET.SubElement(root, 'channel'), 'item')
        ET.SubElement(item, 'title').text = title
        ET.SubElement(item, 'link').text = self.archive['url']
        if pub is not None:
            ET.SubElement(item, 'pubDate').text = pub
        if enclosure:
            ET.SubElement(item, 'enclosure', url=self.archive['media_url'])
        return ET.tostring(root)

    def parse(self, pub, **kwargs):
        return rss_records(self.source, self.raw(pub, **kwargs), date(2026, 10, 12))

    def test_minus0000_matches_archived_reuters_without_changing_archive(self):
        before = digest(self.corpus_path.read_bytes())
        item = self.parse('Wed, 07 Oct 2026 13:00:00 -0000')[0]
        self.assertEqual(item['published_at'], '2026-10-07T13:00:00Z')
        for field in ['source_id', 'publisher_id', 'title', 'published_at', 'media_url']:
            self.assertEqual(item[field], self.archive[field])
        self.assertEqual(digest(self.corpus_path.read_bytes()), before)

    def test_plus0000_unchanged_and_equivalent_to_minus0000(self):
        minus = self.parse('Wed, 07 Oct 2026 13:00:00 -0000')[0]
        plus = self.parse('Wed, 07 Oct 2026 13:00:00 +0000')[0]
        self.assertEqual(plus['published_at'], '2026-10-07T13:00:00Z')
        self.assertEqual(plus['item_id'], minus['item_id'])

    def test_missing_and_unrecognized_timezone_still_rejected(self):
        for suffix in ['', ' XYZ', ' XYZ -0000', ' -0000 XYZ']:
            with self.subTest(suffix=suffix), self.assertRaises(Invalid):
                self.parse('Wed, 07 Oct 2026 13:00:00' + suffix)

    def test_malformed_dates_still_rejected(self):
        for value in ['not a date -0000', 'Wed, 99 Oct 2026 13:00:00 -0000',
                      'Wed, 07 Oct 2026 99:00:00 -0000',
                      'Wed, 07 Oct 2026 13:00:00 garbage -0000']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse(value)

    def test_utc_calendar_window_and_other_offset_preserved(self):
        self.assertEqual(len(self.parse('Sun, 13 Sep 2026 00:00:00 -0000')), 1)
        self.assertEqual(self.parse('Sat, 12 Sep 2026 23:59:59 -0000'), [])
        self.assertEqual(self.parse('Tue, 13 Oct 2026 00:00:00 -0000'), [])
        self.assertEqual(self.parse('Wed, 07 Oct 2026 09:00:00 -0400')[0]['published_at'],
                         '2026-10-07T13:00:00Z')

    def test_missing_metadata_does_not_acquire_invented_values(self):
        self.assertIsNone(self.parse(None)[0]['published_at'])
        self.assertEqual(self.parse('Wed, 07 Oct 2026 13:00:00 -0000', title=''), [])
        self.assertEqual(self.parse('Wed, 07 Oct 2026 13:00:00 -0000', enclosure=False), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
