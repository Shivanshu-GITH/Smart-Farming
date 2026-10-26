"""Plant counts that respect field geometry.

The textbook estimate ``area x usable_fraction / (row x plant spacing)`` assumes
every square metre can hold plants. On small, irregular smallholder plots a
large share of the area is border: plant centres must sit about half a row
spacing inside the boundary, so the true count depends on the perimeter too.
Evaluated on 10,013 hand-delineated Indian fields (research/, Paper 2), the
closed form below stays within ~1% of the geometrically feasible count, while
the fixed-fraction formula is off by >10% on a quarter to half of fields for
widely spaced crops.
"""
from __future__ import annotations

from .catalogue import usable_fraction

SETBACK_FRAC = 0.5  # plant centres >= half a row spacing inside the boundary


def cell_m2(crop: dict) -> float:
    return (crop["spacing_cm"]["row"] / 100.0) * (crop["spacing_cm"]["plant"] / 100.0)


def setback_m(crop: dict) -> float:
    return SETBACK_FRAC * crop["spacing_cm"]["row"] / 100.0


def geometric_count(crop: dict, area_m2: float, perimeter_m: float, share: float = 1.0) -> int:
    """(A - P*s + 4*s^2) / cell: the plantable area of the field shrunk by the
    border setback s (exact for a rectangle), divided by one plant's area."""
    cell = cell_m2(crop)
    if cell <= 0:
        return 0
    s = setback_m(crop)
    return int(max(0.0, area_m2 - perimeter_m * s + 4 * s * s) * share / cell)


def estimate_plants(crop: dict, area_m2: float, perimeter_m: float | None = None,
                    system: str | None = None, share: float = 1.0) -> int:
    """Geometry-aware when the field's perimeter is known, else the area formula."""
    if perimeter_m:
        return geometric_count(crop, area_m2, perimeter_m, share)
    cell = cell_m2(crop)
    return int(area_m2 * usable_fraction(system) * share / cell) if cell > 0 else 0
