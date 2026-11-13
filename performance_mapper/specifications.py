"""Specifications describing the variables of a performance map to be created."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

_MINIMUM_NUMBER_OF_POINTS = 2

Transformation = Callable[[dict[str, float]], float]
"""Computes a derived variable's value at a single performance point.

Receives one dictionary per point, keyed by input column name, with values in SI units.
Must return the derived value in SI units.
"""


@dataclass(frozen=True)
class LookupVariableSpecification:
    """A lookup variable of the performance map to be created.

    Without a transformation, values are taken from the input column of the same name.
    """

    name: str
    units: str = ""
    transformation: Transformation | None = None


@dataclass(frozen=True)
class GridVariableSpecification(LookupVariableSpecification):
    """A grid variable of the performance map to be created.

    The axis is defined by exactly one of:
      - ``values``: explicit axis values,
      - ``range`` and ``number_of_points``: a linear spacing, or
      - neither: the sorted unique values of the variable's derived per-point data.

    Axis inputs are expressed in ``axis_units`` when given, otherwise in ``units``.
    """

    values: tuple[float, ...] | None = None
    range: tuple[float, float] | None = None
    number_of_points: int | None = None
    axis_units: str | None = None

    def __post_init__(self) -> None:
        has_range_inputs = (self.range is not None) or (self.number_of_points is not None)
        if self.values is not None and has_range_inputs:
            raise ValueError(f"Grid variable '{self.name}': provide either 'values' or 'range', not both.")
        if (self.range is None) != (self.number_of_points is None):
            raise ValueError(f"Grid variable '{self.name}': 'range' and 'number_of_points' must be given together.")
        if self.range is not None:
            low, high = self.range
            if not low < high:
                raise ValueError(f"Grid variable '{self.name}': range must satisfy low < high, got {self.range}.")
        if self.number_of_points is not None and self.number_of_points < _MINIMUM_NUMBER_OF_POINTS:
            raise ValueError(f"Grid variable '{self.name}': number_of_points must be at least 2.")
        if self.values is not None and len(self.values) < 1:
            raise ValueError(f"Grid variable '{self.name}': 'values' must not be empty.")
