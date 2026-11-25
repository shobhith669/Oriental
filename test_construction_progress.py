import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from construction_progress import BLOCK, MAX_PIXELS, Scene, compare


class ProgressTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def pair(self, first, last):
        result = []
        for i, data in enumerate((first, last)):
            path = self.root / str(i)
            path.write_bytes(bytes(data))
            result.append(Scene(path, date(2024+i, 3, 1), 'grid', 'series', len(data), 100))
        return result

    def test_exact_threshold_and_different_visible_areas(self):
        a, b = self.pair([0,0,1,1,0,0,0,255,0,255,254], [1,1,0,1,0,0,0,1,255,255,254])
        r = compare(a, b)
        self.assertEqual((r.valid_pixels, r.footprint_pixels, r.newly_visible_ha), (7,10,.02))
        self.assertEqual((r.before_share, r.after_share), (2/7,3/7))

    def test_suppression(self):
        for initial, final, status in [([254],[254],'empty_footprint'),
                                       ([255],[0],'insufficient_coverage'),
                                       ([0,0,0],[1,1,255],'insufficient_coverage')]:
            with self.subTest(status=status):
                r = compare(*self.pair(initial, final))
                self.assertEqual(r.status, status)
                self.assertIsNone(r.newly_visible_ha)

    def test_bad_pixels(self):
        for a, b in [([3],[1]), ([0],[9]), ([254],[255]), ([0],[0,0])]:
            with self.assertRaises(ValueError):
                compare(*self.pair(a,b))

    def test_invalid_inputs(self):
        a,b = self.pair([0],[1])
        for change in (dict(acquired=a.acquired), dict(series_key='sim'), dict(grid_key='other'),
                       dict(pixel_m2=float('nan')), dict(pixel_m2=float('inf')), dict(pixels=True),
                       dict(pixels=MAX_PIXELS+1), dict(grid_key=None)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                compare(a, replace(b, **change))
        b.path.write_bytes(b'')
        with self.assertRaises(ValueError):
            compare(a,b)
        with self.assertRaises(FileNotFoundError):
            compare(a,replace(b,path=self.root/'missing'))

    def test_concurrent_multiblock_readers(self):
        a,b = self.pair(bytes(BLOCK+1), bytes(BLOCK)+bytes([1]))
        with ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(lambda _: compare(a,b), range(8)):
                self.assertEqual(result.newly_visible_ha,.01)
                self.assertEqual(result.valid_pixels,BLOCK+1)
