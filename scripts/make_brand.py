#!/usr/bin/env python3
"""
Generate the integration's brand images (icon/logo SVG + PNGs).

Northern Ireland outline and Lough Neagh: Natural Earth 1:10m (public domain).
Bus glyph: Material Design Icons `mdi:bus` (Apache-2.0).
Colours: Translink's web palette (teal #084f5c, lime #afca1a).

Usage: scripts/make_brand.py   (needs network + rsvg-convert)
"""

from __future__ import annotations

import json
import math
import subprocess
import urllib.request
from pathlib import Path

NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
OUT = Path(__file__).resolve().parent.parent / "custom_components" / "translink_ni" / "brand"

TEAL = "#084f5c"
LIME = "#afca1a"
MDI_BUS = (
    "M18,11H6V6H18M16.5,17A1.5,1.5 0 0,1 15,15.5A1.5,1.5 0 0,1 16.5,14A1.5,1.5 0 0,1 "
    "18,15.5A1.5,1.5 0 0,1 16.5,17M7.5,17A1.5,1.5 0 0,1 6,15.5A1.5,1.5 0 0,1 7.5,14A1.5,1.5 "
    "0 0,1 9,15.5A1.5,1.5 0 0,1 7.5,17M4,16C4,16.88 4.39,17.67 5,18.22V20A1,1 0 0,0 6,21H7A1,1 "
    "0 0,0 8,20V19H16V20A1,1 0 0,0 17,21H18A1,1 0 0,0 19,20V18.22C19.61,17.67 20,16.88 20,16V6"
    "C20,2.5 16.42,2 12,2C7.58,2 4,2.5 4,6V16Z"
)

SIZE = 256
PAD = 8
MIN_SIMPLIFY_POINTS = 3


def _geojson(name: str) -> dict:
    with urllib.request.urlopen(f"{NE}/{name}") as resp:  # noqa: S310 (fixed https URL)
        return json.load(resp)


def _simplify(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker."""
    if len(points) < MIN_SIMPLIFY_POINTS:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    seg = math.hypot(x2 - x1, y2 - y1) or 1e-12
    dmax, idx = 0.0, 0
    for i, (x, y) in enumerate(points[1:-1], 1):
        d = abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1) / seg
        if d > dmax:
            dmax, idx = d, i
    if dmax <= tol:
        return [points[0], points[-1]]
    return _simplify(points[: idx + 1], tol)[:-1] + _simplify(points[idx:], tol)


def main() -> None:
    """Download the geography, build the SVG and render the PNGs."""
    units = _geojson("ne_10m_admin_0_map_units.geojson")
    ni = next(f for f in units["features"] if f["properties"].get("NAME") == "N. Ireland")
    lakes = _geojson("ne_10m_lakes.geojson")
    neagh = next(f for f in lakes["features"] if "Neagh" in (f["properties"].get("name") or ""))

    rings = [poly[0] for poly in ni["geometry"]["coordinates"]]
    rings += [neagh["geometry"]["coordinates"][0]]

    # Equirectangular, corrected for latitude so NI isn't squashed.
    k = math.cos(math.radians(54.6))
    proj = [[(lon * k, -lat) for lon, lat in ring] for ring in rings]
    xs = [x for r in proj for x, _ in r]
    ys = [y for r in proj for _, y in r]
    scale = (SIZE - 2 * PAD) / max(max(xs) - min(xs), max(ys) - min(ys))
    ox = (SIZE - (max(xs) - min(xs)) * scale) / 2
    oy = (SIZE - (max(ys) - min(ys)) * scale) / 2

    def path(ring: list[tuple[float, float]]) -> str:
        pts = [((x - min(xs)) * scale + ox, (y - min(ys)) * scale + oy) for x, y in ring]
        # Closed ring: start == end, so split at the farthest point first or
        # Douglas-Peucker sees zero distance everywhere and collapses it.
        far = max(range(len(pts)), key=lambda i: math.dist(pts[0], pts[i]))
        pts = _simplify(pts[: far + 1], 0.35)[:-1] + _simplify(pts[far:], 0.35)
        return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"

    land = "".join(path(r) for r in proj)  # last ring (Lough Neagh) becomes a hole via evenodd

    # Bus: MDI glyph (24x24) scaled up and centred slightly south-east, over Belfast-ish.
    bus_scale = 5.2
    bx, by = SIZE / 2 - 12 * bus_scale + 14, SIZE / 2 - 12 * bus_scale + 10
    bus = f'transform="translate({bx:.1f},{by:.1f}) scale({bus_scale})"'

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}"
     width="{SIZE}" height="{SIZE}">
  <title>Translink NI for Home Assistant</title>
  <path d="{land}" fill="{LIME}" fill-rule="evenodd"
        stroke="{TEAL}" stroke-width="2" stroke-linejoin="round"/>
  <path d="{MDI_BUS}" {bus} fill="#fff" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>
  <rect x="5" y="4" width="14" height="15" rx="2" {bus} fill="#fff"/>
  <path d="{MDI_BUS}" {bus} fill="{TEAL}"/>
</svg>
"""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.svg").write_text(svg)
    for name, px in (
        ("icon.png", 256),
        ("icon@2x.png", 512),
        ("logo.png", 256),
        ("logo@2x.png", 512),
    ):
        subprocess.run(
            [
                "rsvg-convert",
                "-w",
                str(px),
                "-h",
                str(px),
                "-o",
                str(OUT / name),
                str(OUT / "icon.svg"),
            ],
            check=True,
        )
    print(f"wrote {OUT}: icon.svg, icon/logo PNGs ({len(land)} bytes of path data)")


if __name__ == "__main__":
    main()
