import pytest

from frequenzradio import geo


def test_closest_level_is_the_top_of_the_slider():
    assert geo.zoom_fraction(geo.MIN_DISTANCE) == pytest.approx(1.0)


def test_farthest_level_is_the_bottom_of_the_slider():
    assert geo.zoom_fraction(geo.MAX_DISTANCE) == pytest.approx(0.0)


@pytest.mark.parametrize("fraction", [0.0, 0.2, 0.5, 0.9, 1.0])
def test_slider_position_round_trips(fraction):
    assert geo.zoom_fraction(geo.zoom_distance(fraction)) == pytest.approx(fraction)


def test_closer_is_a_smaller_distance():
    assert geo.zoom_distance(0.8) < geo.zoom_distance(0.2)


def test_out_of_range_values_are_clamped():
    assert geo.zoom_fraction(1000.0) == pytest.approx(0.0)
    assert geo.zoom_distance(2.0) == pytest.approx(geo.MIN_DISTANCE)
