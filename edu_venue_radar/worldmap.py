"""A small clickable world map for the continent filter, as inline SVG.

The outlines are hand-simplified (a few dozen points per landmass, equirectangular,
x = longitude, y = -latitude). They only need to be recognizable at 500 px, not exact.
Each region is one <g> with the continent name the registry uses; the page script
toggles the filter when a region is clicked.
"""

from html import escape

Outline = list[tuple[float, float]]  # (longitude, latitude)

# fmt: off
REGIONS: dict[str, list[Outline]] = {
    "North America": [
        [
            (-168, 66), (-162, 70), (-140, 70), (-125, 70), (-95, 72), (-80, 73), (-65, 62), (-56, 52), (-66, 45),
            (-70, 42), (-76, 35), (-81, 31), (-80, 25), (-82, 29), (-90, 29), (-97, 26), (-97, 21), (-90, 21),
            (-87, 16), (-83, 9), (-78, 8), (-83, 8), (-92, 15), (-105, 20), (-110, 23), (-115, 30), (-118, 34),
            (-124, 40), (-124, 48), (-130, 55), (-140, 60), (-152, 58), (-165, 60),
        ],
        [(-73, 78), (-60, 82), (-30, 83), (-20, 75), (-22, 70), (-42, 60), (-50, 64), (-55, 70)],  # Greenland
    ],
    "South America": [
        [
            (-80, 9), (-72, 12), (-62, 10), (-50, 0), (-35, -5), (-38, -13), (-40, -22), (-48, -26), (-53, -34),
            (-58, -38), (-65, -42), (-66, -55), (-72, -52), (-74, -45), (-72, -30), (-71, -18), (-76, -14),
            (-81, -5), (-80, 1), (-78, 7),
        ],
    ],
    "Europe": [
        [
            (-10, 36), (-9, 43), (-2, 44), (-5, 48), (2, 51), (5, 53), (8, 57), (5, 61), (10, 64), (15, 69),
            (25, 71), (31, 70), (40, 67), (45, 68), (60, 68), (60, 55), (52, 47), (48, 42), (40, 41), (28, 41),
            (26, 38), (23, 36), (20, 40), (15, 38), (12, 44), (8, 44), (3, 43), (-1, 37), (-5, 36),
        ],
        [(-6, 50), (-5, 58), (-3, 59), (2, 52), (1, 51)],  # Great Britain
        [(-10, 52), (-8, 55), (-6, 54), (-6, 52)],  # Ireland
        [(-24, 64), (-22, 66), (-14, 66), (-14, 64), (-19, 63)],  # Iceland
    ],
    "Africa": [
        [
            (-17, 21), (-16, 28), (-10, 30), (-6, 36), (10, 37), (11, 33), (20, 31), (32, 31), (34, 28), (38, 18),
            (43, 12), (51, 12), (46, 2), (40, -5), (40, -15), (35, -24), (32, -29), (27, -34), (20, -35),
            (18, -30), (14, -23), (12, -17), (13, -6), (9, -1), (9, 4), (5, 6), (-8, 4), (-13, 8), (-17, 14),
        ],
        [(44, -25), (47, -25), (50, -15), (49, -12), (44, -16)],  # Madagascar
    ],
    "Australia and Asia-Pacific": [
        [
            (28, 41), (36, 36), (35, 32), (34, 28), (43, 13), (52, 15), (57, 20), (60, 23), (67, 24), (72, 20),
            (77, 8), (80, 15), (88, 22), (92, 21), (98, 16), (100, 8), (103, 1), (105, 10), (109, 12), (108, 21),
            (117, 23), (122, 30), (121, 38), (126, 37), (129, 35), (130, 43), (140, 48), (142, 54), (135, 55),
            (141, 59), (155, 59), (163, 61), (178, 64), (180, 69), (160, 70), (140, 73), (113, 76), (100, 78),
            (80, 73), (68, 70), (60, 68), (60, 55), (52, 47), (48, 42), (40, 41),
        ],
        [(130, 31), (135, 34), (141, 38), (142, 45), (140, 41), (133, 34)],  # Japan
        [(95, 5), (98, 4), (106, -6), (103, -5)],  # Sumatra
        [(109, 1), (117, 7), (119, 1), (116, -4), (110, -3)],  # Borneo
        [(106, -6), (115, -8), (114, -9), (106, -7)],  # Java
        [(131, -1), (141, -3), (150, -10), (141, -9), (138, -5)],  # New Guinea
        [(120, 18), (122, 18), (126, 7), (122, 7)],  # Philippines
        [
            (114, -22), (122, -17), (130, -12), (137, -12), (142, -11), (146, -19), (153, -26), (151, -34),
            (146, -39), (140, -38), (135, -35), (129, -32), (115, -34),
        ],  # Australia
        [(172, -35), (178, -38), (174, -41), (167, -46), (171, -44)],  # New Zealand
    ],
}
# fmt: on
# Where the venue count sits on each region.
LABELS: dict[str, tuple[float, float]] = {
    "North America": (-100, 45),
    "South America": (-60, -15),
    "Europe": (15, 52),
    "Africa": (20, 5),
    "Australia and Asia-Pacific": (100, 45),
}


def _path(outline: Outline) -> str:
    return "M" + " L".join(f"{lon:g},{-lat:g}" for lon, lat in outline) + " Z"


def world_map(counts: dict[str, int]) -> str:
    """The map with one clickable region per continent and its number of venues."""
    groups = []
    for name, outlines in REGIONS.items():
        n = counts.get(name, 0)
        x, y = LABELS[name]
        label = f"{name}: {n} venue{'' if n == 1 else 's'}"
        groups.append(
            f'<g class="region{"" if n else " empty"}" data-continent="{escape(name)}" role="button" tabindex="0" '
            f'aria-pressed="false" aria-label="{escape(label)}"><title>{escape(label)}</title>'
            + "".join(f'<path d="{_path(o)}"/>' for o in outlines)
            + (f'<text x="{x}" y="{-y}">{n}</text>' if n else "")
            + "</g>"
        )
    return (
        f'<svg class="worldmap" viewBox="-170 -85 355 145" role="group" aria-label="Filter by continent">{"".join(groups)}</svg>'
    )
