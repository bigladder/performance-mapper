import math

import pytest

from performance_mapper import (
    Column,
    GridVariableSpecification,
    LookupVariableSpecification,
    PointTable,
)


def test_linear_data_fits_perfectly() -> None:
    table = PointTable(
        [
            Column("x", "", [0.0, 1.0, 2.0, 3.0]),
            Column("y", "", [1.0, 3.0, 5.0, 7.0]),
        ]
    )
    performance_map, report = table.to_performance_map(
        grid_variables=[GridVariableSpecification("x")],
        lookup_variables=[LookupVariableSpecification("y")],
        fit_report=True,
    )
    assert report.r_squared == pytest.approx(1.0, abs=1e-9)
    statistics = report.lookup_variable_statistics[0]
    assert statistics.root_mean_squared_error == pytest.approx(0.0, abs=1e-9)
    assert report.points_outside_grid == ()
    assert report.grid_points_outside_bounding_box == ()
    assert report.grid_points_outside_convex_hull == ()
    assert report.convex_hull_evaluated


def test_coarse_grid_reports_discretization_error() -> None:
    """y = x**2 sampled at 0..4, gridded at [0, 2, 4]: multilinear read-back misses the
    curvature at x = 1 and x = 3 even though the surface is exact at data points."""
    table = PointTable(
        [
            Column("x", "", [0.0, 1.0, 2.0, 3.0, 4.0]),
            Column("y", "", [0.0, 1.0, 4.0, 9.0, 16.0]),
        ]
    )
    _, report = table.to_performance_map(
        grid_variables=[GridVariableSpecification("x", range=(0.0, 4.0), number_of_points=3)],
        lookup_variables=[LookupVariableSpecification("y")],
        fit_report=True,
    )
    statistics = report.lookup_variable_statistics[0]
    assert statistics.root_mean_squared_error == pytest.approx(math.sqrt(2.0 / 5.0), rel=1e-6)
    assert statistics.maximum_absolute_error == pytest.approx(1.0, rel=1e-6)
    assert 0.0 < report.r_squared < 1.0
    assert len(statistics.residuals) == 5


def test_extrapolation_zones() -> None:
    """Data on a triangle: grid corners beyond the hypotenuse are gap-filling; a grid
    wider than the data is pure extrapolation."""
    table = PointTable(
        [
            Column("x", "", [0.0, 2.0, 0.0, 0.5]),
            Column("y", "", [0.0, 0.0, 2.0, 0.5]),
            Column("z", "", [0.0, 2.0, 2.0, 1.0]),
        ]
    )
    _, report = table.to_performance_map(
        grid_variables=[
            GridVariableSpecification("x", range=(0.0, 3.0), number_of_points=4),
            GridVariableSpecification("y", range=(0.0, 3.0), number_of_points=4),
        ],
        lookup_variables=[LookupVariableSpecification("z")],
        fit_report=True,
    )
    assert report.convex_hull_evaluated
    assert len(report.grid_points_outside_bounding_box) > 0
    assert len(report.grid_points_outside_convex_hull) > 0
    # x = 3 is beyond the data's bounding box; flat indices of the x = 3 row are 12..15
    assert set(range(12, 16)).issubset(report.grid_points_outside_bounding_box)
    # (1, 2) is inside the box but beyond the hypotenuse x + y = 2; flat index 1*4 + 2
    grid_point = 1 * 4 + 2
    assert grid_point in report.grid_points_outside_convex_hull

    coverage = report.grid_variable_coverage[0]
    assert coverage.axis_maximum == pytest.approx(3.0)
    assert coverage.data_maximum == pytest.approx(2.0)


def test_points_outside_grid_are_flagged_and_excluded() -> None:
    table = PointTable(
        [
            Column("x", "", [0.0, 1.0, 2.0, 10.0]),
            Column("y", "", [0.0, 1.0, 2.0, 10.0]),
        ]
    )
    _, report = table.to_performance_map(
        grid_variables=[GridVariableSpecification("x", range=(0.0, 2.0), number_of_points=3)],
        lookup_variables=[LookupVariableSpecification("y")],
        fit_report=True,
    )
    assert report.points_outside_grid == (3,)
    assert len(report.lookup_variable_statistics[0].residuals) == 3
