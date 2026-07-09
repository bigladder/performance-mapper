"""Point tables: unstructured collections of performance points."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Sequence, Union, overload

from .interpolation import InterpolationMethod, RadialBasisFunction

if TYPE_CHECKING:
    from .fit_report import FitReport
    from .performance_map import PerformanceMap
    from .specifications import GridVariableSpecification, LookupVariableSpecification

_LABEL_PATTERN = re.compile(r"^(?P<name>.*\S)\s*\((?P<units>.*)\)$")


def _label(name: str, units: str) -> str:
    return f"{name} ({units})" if units else name


def _parse_label(label: str) -> tuple[str, str]:
    match = _LABEL_PATTERN.match(label.strip())
    if match:
        return match.group("name"), match.group("units")
    return label.strip(), ""


def _require_pandas() -> Any:
    try:
        import pandas  # noqa: PLC0415  (optional dependency, imported lazily)
    except ImportError as error:
        raise ImportError(
            "pandas is required for DataFrame conversions; install it with 'pip install performance-mapper[pandas]'."
        ) from error
    return pandas


@dataclass(frozen=True)
class Column:
    """One variable of a point table: a name, koozie-compliant units ('' = unitless), and
    one value per performance point."""

    name: str
    units: str
    values: Sequence[float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(float(value) for value in self.values))
        for index, value in enumerate(self.values):
            if not math.isfinite(value):
                raise ValueError(f"Column '{self.name}' has a non-finite value at point {index}: {value}.")


@dataclass(frozen=True)
class PointTable:
    """A collection of performance points, column-oriented. Row *i* across all columns is
    one performance point; points need not lie on any grid."""

    columns: Sequence[Column]

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        if not self.columns:
            raise ValueError("A point table requires at least one column.")
        names = [column.name for column in self.columns]
        if len(set(names)) != len(names):
            raise ValueError(f"Column names must be unique, got {names}.")
        lengths = {column.name: len(column.values) for column in self.columns}
        if len(set(lengths.values())) != 1:
            raise ValueError(f"All columns must have the same number of points, got {lengths}.")
        if len(self) == 0:
            raise ValueError("A point table requires at least one performance point.")

    def __len__(self) -> int:
        return len(self.columns[0].values)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @overload
    def to_performance_map(
        self,
        grid_variables: Sequence["GridVariableSpecification"],
        lookup_variables: Sequence["LookupVariableSpecification"],
        interpolation_method: InterpolationMethod | None = None,
        fit_report: Literal[False] = False,
    ) -> "PerformanceMap": ...

    @overload
    def to_performance_map(
        self,
        grid_variables: Sequence["GridVariableSpecification"],
        lookup_variables: Sequence["LookupVariableSpecification"],
        interpolation_method: InterpolationMethod | None = None,
        *,
        fit_report: Literal[True],
    ) -> tuple["PerformanceMap", "FitReport"]: ...

    def to_performance_map(
        self,
        grid_variables: Sequence["GridVariableSpecification"],
        lookup_variables: Sequence["LookupVariableSpecification"],
        interpolation_method: InterpolationMethod | None = None,
        fit_report: bool = False,
    ) -> Union["PerformanceMap", tuple["PerformanceMap", "FitReport"]]:
        """Translate this table's scattered points into a performance map on a regular grid.

        With ``fit_report=True``, returns ``(performance_map, fit_report)``.
        """
        from ._engine import regrid  # noqa: PLC0415  (circular at module scope)

        if interpolation_method is None:
            interpolation_method = RadialBasisFunction()
        return regrid(self, grid_variables, lookup_variables, interpolation_method, fit_report)

    def to_csv(self, path: Any) -> None:
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([_label(column.name, column.units) for column in self.columns])
            writer.writerows(zip(*(column.values for column in self.columns)))

    @classmethod
    def from_csv(cls, path: Any) -> "PointTable":
        with open(path, newline="", encoding="utf-8") as file:
            reader = csv.reader(file)
            try:
                header = next(reader)
            except StopIteration:
                raise ValueError(f"'{path}' has no header row.") from None
            rows = [row for row in reader if row]
        return cls(
            tuple(
                Column(name, units, tuple(float(row[index]) for row in rows))
                for index, (name, units) in enumerate(_parse_label(label) for label in header)
            )
        )

    def to_dataframe(self) -> Any:
        pandas = _require_pandas()
        return pandas.DataFrame({_label(column.name, column.units): list(column.values) for column in self.columns})

    @classmethod
    def from_dataframe(cls, dataframe: Any) -> "PointTable":
        return cls(
            tuple(
                Column(name, units, tuple(float(value) for value in dataframe[label]))
                for label, (name, units) in ((label, _parse_label(str(label))) for label in dataframe.columns)
            )
        )
