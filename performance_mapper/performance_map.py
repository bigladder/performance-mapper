"""The performance map data structure."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .table import PointTable


@dataclass(frozen=True)
class GridVariable:
    """An independent variable: its sorted values define one axis of the regular grid."""

    name: str
    units: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class LookupVariable:
    """A dependent variable with one value at every grid point.

    Values are flattened row-major: the last grid variable varies fastest, and the list length is the product
    of the axis lengths.
    """

    name: str
    units: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class PerformanceMap:
    """A set of grid variables and the lookup variables defined over their regular grid.

    Values are stored in each variable's declared units. (Representations will fix
    units in the schema; reconciling them is an exporter's concern, not the map's.)
    """

    grid_variables: tuple[GridVariable, ...]
    lookup_variables: tuple[LookupVariable, ...]

    def __post_init__(self) -> None:
        expected_length = math.prod(self.grid_shape)
        for lookup_variable in self.lookup_variables:
            if len(lookup_variable.values) != expected_length:
                raise ValueError(
                    f"Lookup variable '{lookup_variable.name}' has {len(lookup_variable.values)} values; "
                    f"the grid {self.grid_shape} requires {expected_length}."
                )

    @property
    def grid_shape(self) -> tuple[int, ...]:
        return tuple(len(grid_variable.values) for grid_variable in self.grid_variables)

    def to_point_table(self) -> "PointTable":
        """Flatten the grid into a point table with one performance point per grid point."""
        from .table import Column, PointTable  # noqa: PLC0415  (circular at module scope)

        number_of_points = math.prod(self.grid_shape)
        columns = []
        repetitions_within = number_of_points
        for grid_variable in self.grid_variables:
            repetitions_within //= len(grid_variable.values)
            cycles = number_of_points // (repetitions_within * len(grid_variable.values))
            values = [value for _ in range(cycles) for value in grid_variable.values for _ in range(repetitions_within)]
            columns.append(Column(grid_variable.name, grid_variable.units, tuple(values)))
        for lookup_variable in self.lookup_variables:
            columns.append(Column(lookup_variable.name, lookup_variable.units, lookup_variable.values))
        return PointTable(tuple(columns))

    def to_csv(self, path: Any) -> None:
        self.to_point_table().to_csv(path)

    def to_dataframe(self) -> Any:
        return self.to_point_table().to_dataframe()
