from edu_venue_radar.registry import CONTINENTS
from edu_venue_radar.worldmap import LABELS, REGIONS, world_map


def test_every_continent_except_online_has_a_region_and_a_label():
    assert set(REGIONS) == set(LABELS) == set(CONTINENTS) - {"Online"}


def test_map_shows_counts_and_marks_empty_regions():
    svg = world_map({"Europe": 16, "North America": 1})
    assert 'data-continent="Europe"' in svg and ">16</text>" in svg
    assert 'aria-label="North America: 1 venue"' in svg
    assert '<g class="region empty" data-continent="Africa"' in svg
