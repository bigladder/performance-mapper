"""Grid fit: how faithfully a performance map reproduces the point table it was built from."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LookupVariableFitStatistics:
    """Read-back error statistics for one lookup variable, in its declared units.

    Residuals are (grid read back by multilinear interpolation) minus (irregular data
    value), one per irregular data point in input order, each compared with that point's
    own value even when duplicate points were averaged for fitting. Points outside the
    grid's axis ranges have NaN residuals and are excluded from the statistics.
    """

    name: str
    units: str
    root_mean_squared_error: float
    maximum_absolute_error: float
    mean_bias_error: float
    residuals: tuple[float, ...]


@dataclass(frozen=True)
class GridVariableCoverage:
    """How far one grid axis reaches relative to the data along it, in declared units."""

    name: str
    units: str
    axis_minimum: float
    axis_maximum: float
    data_minimum: float
    data_maximum: float


@dataclass(frozen=True)
class FitReport:
    """How well the regular grid reproduces the irregular data when read back the way a
    consumer reads it (multilinear interpolation). With exact interpolation this measures
    discretization error: whether the grid resolution is adequate.

    Grid points are classified into extrapolation zones by rising risk: inside the data's
    convex hull (interpolation), outside the hull but inside the bounding box
    (gap-filling), and outside the bounding box (pure extrapolation). Indices into the
    grid are flat row-major indices; indices into the point table refer to the irregular
    data points in input order.
    """

    r_squared: float
    lookup_variable_statistics: tuple[LookupVariableFitStatistics, ...]
    grid_variable_coverage: tuple[GridVariableCoverage, ...]
    points_outside_grid: tuple[int, ...]
    grid_points_outside_bounding_box: tuple[int, ...]
    grid_points_outside_convex_hull: tuple[int, ...]
    convex_hull_evaluated: bool
