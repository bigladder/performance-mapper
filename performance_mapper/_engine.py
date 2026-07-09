"""Private regridding engine behind ``PointTable.to_performance_map()``.

All internal computation is in SI units (koozie convention): input columns are converted
on ingest, transformations receive and return SI values, and declared output units are
applied as the final step. Grid coordinates are always min-max normalized to [0, 1]
before fitting so that mixed SI magnitudes cannot blind the kernel along small axes.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Sequence, Union

import numpy as np
from koozie import fr_u, get_dimensionality, to_u
from scipy.interpolate import RegularGridInterpolator
from scipy.spatial import Delaunay, QhullError

from .fit_report import FitReport, GridVariableCoverage, LookupVariableFitStatistics
from .interpolation import InterpolationMethod
from .performance_map import GridVariable, LookupVariable, PerformanceMap
from .specifications import GridVariableSpecification, LookupVariableSpecification

if TYPE_CHECKING:
    from .table import PointTable


class DuplicatePointsWarning(UserWarning):
    """Performance points sharing identical grid coordinates were averaged into one."""


_MINIMUM_DIMENSIONS_FOR_CONVEX_HULL = 2
_NEGLIGIBLE_SUM_OF_SQUARES = 1e-12


def regrid(
    point_table: "PointTable",
    grid_specifications: Sequence[GridVariableSpecification],
    lookup_specifications: Sequence[LookupVariableSpecification],
    interpolation_method: InterpolationMethod,
    build_fit_report: bool,
) -> Union[PerformanceMap, tuple[PerformanceMap, FitReport]]:
    regridding = _Regridding(point_table, tuple(grid_specifications), tuple(lookup_specifications))
    performance_map = regridding.build_performance_map(interpolation_method)
    if not build_fit_report:
        return performance_map
    return performance_map, regridding.build_fit_report(performance_map)


class _Regridding:
    def __init__(
        self,
        point_table: "PointTable",
        grid_specifications: tuple[GridVariableSpecification, ...],
        lookup_specifications: tuple[LookupVariableSpecification, ...],
    ) -> None:
        if not grid_specifications:
            raise ValueError("At least one grid variable is required.")
        if not lookup_specifications:
            raise ValueError("At least one lookup variable is required.")
        self.grid_specifications = grid_specifications
        self.lookup_specifications = lookup_specifications
        _validate_specifications(point_table, [*grid_specifications, *lookup_specifications])

        si_points = _to_si_points(point_table)
        grid_data = np.column_stack([_derive(s, si_points) for s in grid_specifications])
        lookup_data = np.column_stack([_derive(s, si_points) for s in lookup_specifications])
        self.grid_data, self.lookup_data, self.original_indices = _average_duplicates(grid_data, lookup_data)

        self.axes_si = [
            _axis_si(specification, self.grid_data[:, dimension])
            for dimension, specification in enumerate(grid_specifications)
        ]
        if len(self.grid_data) < len(self.axes_si) + 1:
            raise ValueError(
                f"Only {len(self.grid_data)} unique points for {len(self.axes_si)} grid variables; "
                f"interpolation requires at least {len(self.axes_si) + 1}."
            )

        minimums = np.minimum(self.grid_data.min(axis=0), [axis.min() for axis in self.axes_si])
        maximums = np.maximum(self.grid_data.max(axis=0), [axis.max() for axis in self.axes_si])
        spans = maximums - minimums
        spans[spans == 0.0] = 1.0
        self._minimums, self._spans = minimums, spans

        meshes = np.meshgrid(*self.axes_si, indexing="ij")
        self.grid_coordinates = np.column_stack([mesh.ravel(order="C") for mesh in meshes])
        self.grid_values: np.ndarray | None = None

    def _normalize(self, coordinates: np.ndarray) -> np.ndarray:
        return (coordinates - self._minimums) / self._spans

    def build_performance_map(self, interpolation_method: InterpolationMethod) -> PerformanceMap:
        evaluate = interpolation_method.fit(self._normalize(self.grid_data), self.lookup_data)
        self.grid_values = np.asarray(evaluate(self._normalize(self.grid_coordinates)), dtype=float)
        return PerformanceMap(
            grid_variables=tuple(
                GridVariable(s.name, s.units, _in_units(axis, s.units))
                for s, axis in zip(self.grid_specifications, self.axes_si)
            ),
            lookup_variables=tuple(
                LookupVariable(s.name, s.units, _in_units(self.grid_values[:, index], s.units))
                for index, s in enumerate(self.lookup_specifications)
            ),
        )

    def build_fit_report(self, performance_map: PerformanceMap) -> FitReport:
        assert self.grid_values is not None
        in_grid = np.ones(len(self.grid_data), dtype=bool)
        for dimension, axis in enumerate(self.axes_si):
            coordinates = self.grid_data[:, dimension]
            in_grid &= (coordinates >= axis.min()) & (coordinates <= axis.max())
        points_outside_grid = tuple(self.original_indices[i] for i in np.flatnonzero(~in_grid))

        predicted_si = self._read_back(self.grid_data[in_grid])
        actual_si = self.lookup_data[in_grid]
        statistics = tuple(
            _fit_statistics(s, predicted_si[:, index], actual_si[:, index])
            for index, s in enumerate(self.lookup_specifications)
        )

        outside_box_mask, outside_hull_mask, hull_evaluated = self._extrapolation_zones()
        return FitReport(
            r_squared=_r_squared(predicted_si, actual_si),
            lookup_variable_statistics=statistics,
            grid_variable_coverage=tuple(
                GridVariableCoverage(
                    name=s.name,
                    units=s.units,
                    axis_minimum=min(grid_variable.values),
                    axis_maximum=max(grid_variable.values),
                    data_minimum=float(to_u(self.grid_data[:, dimension].min(), s.units)),
                    data_maximum=float(to_u(self.grid_data[:, dimension].max(), s.units)),
                )
                for dimension, (s, grid_variable) in enumerate(
                    zip(self.grid_specifications, performance_map.grid_variables)
                )
            ),
            points_outside_grid=points_outside_grid,
            grid_points_outside_bounding_box=tuple(np.flatnonzero(outside_box_mask).tolist()),
            grid_points_outside_convex_hull=tuple(np.flatnonzero(outside_hull_mask).tolist()),
            convex_hull_evaluated=hull_evaluated,
        )

    def _read_back(self, coordinates: np.ndarray) -> np.ndarray:
        """Read the finished regular grid the way a consumer would: multilinear interpolation."""
        assert self.grid_values is not None
        number_of_lookups = self.grid_values.shape[1]
        active = [dimension for dimension, axis in enumerate(self.axes_si) if len(axis) > 1]
        if not active:
            return np.tile(self.grid_values[0], (len(coordinates), 1))
        values = self.grid_values.reshape(*(len(axis) for axis in self.axes_si), number_of_lookups)
        values = values.reshape(*(len(self.axes_si[d]) for d in active), number_of_lookups)
        reader = RegularGridInterpolator(
            tuple(self.axes_si[d] for d in active), values, method="linear", bounds_error=False, fill_value=None
        )
        return np.asarray(reader(coordinates[:, active]), dtype=float)

    def _extrapolation_zones(self) -> tuple[np.ndarray, np.ndarray, bool]:
        data_minimums = self.grid_data.min(axis=0)
        data_maximums = self.grid_data.max(axis=0)
        outside_box = ((self.grid_coordinates < data_minimums) | (self.grid_coordinates > data_maximums)).any(axis=1)
        no_hull_points = np.zeros(len(self.grid_coordinates), dtype=bool)
        if len(self.axes_si) < _MINIMUM_DIMENSIONS_FOR_CONVEX_HULL:
            return outside_box, no_hull_points, True  # in one dimension the hull is the bounding box
        try:
            triangulation = Delaunay(self._normalize(self.grid_data))
        except QhullError:
            return outside_box, no_hull_points, False
        inside_hull = triangulation.find_simplex(self._normalize(self.grid_coordinates)) >= 0
        return outside_box, ~inside_hull & ~outside_box, True


def _to_si_points(point_table: "PointTable") -> list[dict[str, float]]:
    si_columns = {column.name: [fr_u(value, column.units) for value in column.values] for column in point_table.columns}
    return [{name: values[index] for name, values in si_columns.items()} for index in range(len(point_table))]


def _derive(specification: LookupVariableSpecification, si_points: list[dict[str, float]]) -> np.ndarray:
    if specification.transformation is not None:
        return np.array([float(specification.transformation(point)) for point in si_points])
    return np.array([point[specification.name] for point in si_points])


def _validate_specifications(point_table: "PointTable", specifications: list[LookupVariableSpecification]) -> None:
    input_units = {column.name: column.units for column in point_table.columns}
    names_seen = set()
    for specification in specifications:
        if specification.name in names_seen:
            raise ValueError(f"Output variable '{specification.name}' is specified more than once.")
        names_seen.add(specification.name)
        if specification.transformation is None:
            if specification.name not in input_units:
                raise ValueError(
                    f"Output variable '{specification.name}' has no transformation and no input column of "
                    f"that name. Input columns: {sorted(input_units)}."
                )
            if get_dimensionality(input_units[specification.name]) != get_dimensionality(specification.units):
                raise ValueError(
                    f"Output variable '{specification.name}' declares units '{specification.units}', which are "
                    f"not dimensionally compatible with the input column's units "
                    f"'{input_units[specification.name]}'."
                )
        if isinstance(specification, GridVariableSpecification) and specification.axis_units is not None:
            if get_dimensionality(specification.axis_units) != get_dimensionality(specification.units):
                raise ValueError(
                    f"Grid variable '{specification.name}': axis_units '{specification.axis_units}' are not "
                    f"dimensionally compatible with declared units '{specification.units}'."
                )


def _average_duplicates(grid_data: np.ndarray, lookup_data: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[int]]:
    groups: dict[tuple[float, ...], list[int]] = {}
    for index, row in enumerate(grid_data):
        groups.setdefault(tuple(row), []).append(index)
    if len(groups) == len(grid_data):
        return grid_data, lookup_data, list(range(len(grid_data)))
    duplicate_groups = [indices for indices in groups.values() if len(indices) > 1]
    warnings.warn(
        "Points sharing identical grid coordinates were averaged: "
        + "; ".join(f"points {indices}" for indices in duplicate_groups),
        DuplicatePointsWarning,
        stacklevel=4,
    )
    representatives = [indices[0] for indices in groups.values()]
    averaged_grid = np.array([grid_data[indices[0]] for indices in groups.values()])
    averaged_lookups = np.array([lookup_data[indices].mean(axis=0) for indices in groups.values()])
    return averaged_grid, averaged_lookups, representatives


def _axis_si(specification: GridVariableSpecification, derived_values: np.ndarray) -> np.ndarray:
    axis_units = specification.axis_units if specification.axis_units is not None else specification.units
    if specification.values is not None:
        axis = np.sort([fr_u(value, axis_units) for value in specification.values])
        if len(np.unique(axis)) != len(axis):
            raise ValueError(f"Grid variable '{specification.name}': axis values must be distinct.")
        return axis
    if specification.range is not None and specification.number_of_points is not None:
        low, high = specification.range
        return np.array([fr_u(value, axis_units) for value in np.linspace(low, high, specification.number_of_points)])
    return np.unique(derived_values)


def _in_units(si_values: np.ndarray, units: str) -> tuple[float, ...]:
    return tuple(float(to_u(value, units)) for value in si_values)


def _fit_statistics(
    specification: LookupVariableSpecification, predicted_si: np.ndarray, actual_si: np.ndarray
) -> LookupVariableFitStatistics:
    predicted = np.array(_in_units(predicted_si, specification.units))
    actual = np.array(_in_units(actual_si, specification.units))
    residuals = predicted - actual
    if len(residuals) == 0:
        return LookupVariableFitStatistics(
            specification.name, specification.units, float("nan"), float("nan"), float("nan"), ()
        )
    return LookupVariableFitStatistics(
        name=specification.name,
        units=specification.units,
        root_mean_squared_error=float(np.sqrt(np.mean(residuals**2))),
        maximum_absolute_error=float(np.max(np.abs(residuals))),
        mean_bias_error=float(np.mean(residuals)),
        residuals=tuple(residuals.tolist()),
    )


def _r_squared(predicted_si: np.ndarray, actual_si: np.ndarray) -> float:
    """Coefficient of determination on residual Euclidean distance in normalized lookup space."""
    if len(actual_si) == 0:
        return float("nan")
    scales = actual_si.max(axis=0) - actual_si.min(axis=0)
    scales[scales == 0.0] = 1.0
    residual_sum_of_squares = float((((predicted_si - actual_si) / scales) ** 2).sum())
    total_sum_of_squares = float((((actual_si - actual_si.mean(axis=0)) / scales) ** 2).sum())
    if total_sum_of_squares == 0.0:
        return 1.0 if residual_sum_of_squares < _NEGLIGIBLE_SUM_OF_SQUARES else 0.0
    return 1.0 - residual_sum_of_squares / total_sum_of_squares
