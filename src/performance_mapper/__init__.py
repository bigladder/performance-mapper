"""Utilities for working with performance maps (per ASHRAE Standard 205).

Agnostic to what a map describes; specific to the grid-variable/lookup-variable
structure. The core operation translates sparse or scattered performance points
(a ``PointTable``) into a ``PerformanceMap`` on a regular grid.
"""

from ._engine import DuplicatePointsWarning
from .fit_report import FitReport, GridVariableCoverage, LookupVariableFitStatistics
from .interpolation import InterpolationMethod, RadialBasisFunction
from .performance_map import GridVariable, LookupVariable, PerformanceMap
from .specifications import GridVariableSpecification, LookupVariableSpecification, Transformation
from .table import Column, PointTable

__all__ = [
    "Column",
    "DuplicatePointsWarning",
    "FitReport",
    "GridVariable",
    "GridVariableCoverage",
    "GridVariableSpecification",
    "InterpolationMethod",
    "LookupVariable",
    "LookupVariableFitStatistics",
    "LookupVariableSpecification",
    "PerformanceMap",
    "PointTable",
    "RadialBasisFunction",
    "Transformation",
]
