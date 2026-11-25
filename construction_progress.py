"""Compare two preclassified construction masks. Requires Python 3.10+ and NumPy.

Input contract: immutable row-major uint8 files produced by trusted preprocessing.
Codes: 0 background, 1 visible infrastructure, 254 outside footprint, 255 unknown.
The grid key fingerprints CRS, transform, shape and footprint version. The series
key identifies a compatible classifier, acquisition protocol and evidence type.
"""
import logging
import os
import stat
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

LOG = logging.getLogger(__name__)
BLOCK = 256 * 1024
MAX_PIXELS = 100_000_000


@dataclass(frozen=True)
class Scene:
    path: Path
    acquired: date
    grid_key: str
    series_key: str
    pixels: int
    pixel_m2: float  # From the metric equal-area grid transform.


@dataclass(frozen=True)
class Progress:
    status: str
    footprint_pixels: int
    valid_pixels: int
    newly_visible_ha: float | None
    before_share: float | None
    after_share: float | None


def _validate(scene):
    if type(scene.pixels) is not int or not 0 < scene.pixels <= MAX_PIXELS:
        raise ValueError("Pixel count outside supported range")
    if type(scene.pixel_m2) not in (int, float) or not 0 < scene.pixel_m2 <= 1e8:
        raise ValueError("Invalid square metres per pixel")
    if type(scene.acquired) is not date:
        raise ValueError("Expected a calendar date")
    for key in (scene.grid_key, scene.series_key):
        if not isinstance(key, str) or not key.strip() or len(key) > 256:
            raise ValueError("Missing or oversized comparison key")


def _compare(before, after):
    for scene in (before, after):
        _validate(scene)
    if before.acquired >= after.acquired:
        raise ValueError("Expected two chronologically ordered observations")
    if (before.grid_key, before.series_key, before.pixels, before.pixel_m2) != (
        after.grid_key, after.series_key, after.pixels, after.pixel_m2
    ):
        raise ValueError("Incompatible grids or processing series")

    footprint = valid = new = old_total = new_total = 0
    with before.path.open("rb") as first, after.path.open("rb") as last:
        for stream in (first, last):
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != before.pixels:
                raise ValueError("Expected a regular mask file of the declared size")
        for start in range(0, before.pixels, BLOCK):
            size = min(BLOCK, before.pixels - start)
            a = np.frombuffer(first.read(size), dtype=np.uint8)
            b = np.frombuffer(last.read(size), dtype=np.uint8)
            if a.size != size or b.size != size:
                raise OSError("Short mask read")
            if np.any((a > 1) & (a < 254)) or np.any((b > 1) & (b < 254)):
                raise ValueError("Unknown mask code")
            outside = a == 254
            if np.any(outside != (b == 254)):
                raise ValueError("Footprints disagree")
            common = (a < 2) & (b < 2)
            footprint += size - int(np.count_nonzero(outside))
            valid += int(np.count_nonzero(common))
            old_total += int(np.count_nonzero(common & (a == 1)))
            new_total += int(np.count_nonzero(common & (b == 1)))
            new += int(np.count_nonzero((a == 0) & (b == 1)))

    if not footprint:
        return Progress("empty_footprint", 0, 0, None, None, None)
    if valid * 10 < footprint * 7:
        return Progress("insufficient_coverage", footprint, valid, None, None, None)
    return Progress("reviewable", footprint, valid, new * before.pixel_m2 / 10_000,
                    old_total / valid, new_total / valid)


def compare(before: Scene, after: Scene) -> Progress:
    """Paths and metadata come from a server-owned manifest, never a client path."""
    try:
        result = _compare(before, after)
    except (OSError, ValueError) as exc:
        LOG.warning("construction comparison failed category=%s reason=%s",
                    type(exc).__name__, str(exc) if isinstance(exc, ValueError) else exc.errno)
        raise
    LOG.info("construction comparison status=%s valid=%d footprint=%d",
             result.status, result.valid_pixels, result.footprint_pixels)
    return result
