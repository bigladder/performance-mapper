"""Shared helpers for the synthetic-chiller examples: dataset locations, the ASHRAE 205
RS0001 CoolingLiquid Data Element names, grid/lookup specifications, and coverage printing.
The leading underscore marks this as a support module -- start with the numbered scripts,
not here.
"""

from __future__ import annotations

from pathlib import Path

from performance_mapper import (
    FitReport,
    GridVariableSpecification,
    LookupVariableSpecification,
    PerformanceMap,
    PointTable,
)

DATA_DIRECTORY = Path(__file__).parent / "data"
DESIGN_DATA_PATH = DATA_DIRECTORY / "chiller_design_conditions.csv"
ACTUAL_DATA_PATH = DATA_DIRECTORY / "chiller_actual_conditions.csv"

# RS0001 PerformanceMapCoolingLiquid Data Element names (used verbatim as column names).
EVAPORATOR_FLOW = "evaporator_liquid_volumetric_flow_rate"
EVAPORATOR_LEAVING_TEMPERATURE = "evaporator_liquid_leaving_temperature"
CONDENSER_FLOW = "condenser_liquid_volumetric_flow_rate"
CONDENSER_ENTERING_TEMPERATURE = "condenser_liquid_entering_temperature"
COMPRESSOR_SEQUENCE = "compressor_sequence_number"
INPUT_POWER = "input_power"
NET_EVAPORATOR_CAPACITY = "net_evaporator_capacity"
NET_CONDENSER_CAPACITY = "net_condenser_capacity"

# SI units of each grid variable, per the schema (m^3/s, K, and dimensionless for the
# integer sequence number).
_FLOW_UNITS = "m**3/s"
_TEMPERATURE_UNITS = "K"


def load_points(path: Path) -> PointTable:
    """Load a generated chiller dataset. The generated tables are pristine, so the built-in
    ``PointTable.from_csv`` reader is enough -- no cleaning step is needed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Generate the datasets first:\n"
            "  uv run --package performance-mapper-examples python examples/generate_synthetic_chiller.py"
        )
    return PointTable.from_csv(path)


def reduced_grid_variables() -> list[GridVariableSpecification]:
    """The three independent axes: chilled-liquid leaving temperature, condenser entering
    temperature, and compressor sequence number. Each defaults to its sorted unique values.
    """
    return [
        GridVariableSpecification(EVAPORATOR_LEAVING_TEMPERATURE, _TEMPERATURE_UNITS),
        GridVariableSpecification(CONDENSER_ENTERING_TEMPERATURE, _TEMPERATURE_UNITS),
        GridVariableSpecification(COMPRESSOR_SEQUENCE, ""),
    ]


def full_grid_variables() -> list[GridVariableSpecification]:
    """All five RS0001 CoolingLiquid grid variables, including the two dependent flows."""
    return [
        GridVariableSpecification(EVAPORATOR_FLOW, _FLOW_UNITS),
        GridVariableSpecification(EVAPORATOR_LEAVING_TEMPERATURE, _TEMPERATURE_UNITS),
        GridVariableSpecification(CONDENSER_FLOW, _FLOW_UNITS),
        GridVariableSpecification(CONDENSER_ENTERING_TEMPERATURE, _TEMPERATURE_UNITS),
        GridVariableSpecification(COMPRESSOR_SEQUENCE, ""),
    ]


def lookup_variables() -> list[LookupVariableSpecification]:
    """The core CoolingLiquid lookup outputs used throughout the examples."""
    return [
        LookupVariableSpecification(INPUT_POWER, "W"),
        LookupVariableSpecification(NET_EVAPORATOR_CAPACITY, "W"),
    ]


def grid_node_count(performance_map: PerformanceMap) -> int:
    """Total number of nodes in a map's regular grid (the product of the axis lengths)."""
    count = 1
    for grid_variable in performance_map.grid_variables:
        count *= len(grid_variable.values)
    return count


def print_coverage(performance_map: PerformanceMap, report: FitReport) -> None:
    """Print the grid size, read-back fit quality, and extrapolation-zone breakdown."""
    total = grid_node_count(performance_map)
    outside_box = len(report.grid_points_outside_bounding_box)
    outside_hull = len(report.grid_points_outside_convex_hull)
    inside_hull = total - outside_box - outside_hull
    print(f"  grid nodes: {total:,}")
    print(f"  read-back R^2: {report.r_squared:.4f}")
    if report.convex_hull_evaluated:
        print(
            f"  inside convex hull: {inside_hull:,} / {total:,} "
            f"({100 * inside_hull / total:.1f}%)   "
            f"gap-fill (in box, outside hull): {outside_hull:,}   "
            f"outside box: {outside_box:,}"
        )
    else:
        # The convex hull could not be computed: with this many axes the data is degenerate
        # (it lies on a lower-dimensional manifold), so scipy's Delaunay triangulation fails.
        # That failure is itself the diagnosis -- the axes are not mutually independent.
        print(f"  outside bounding box: {outside_box:,} / {total:,}   (convex hull could not be evaluated)")
    print(f"  input points excluded from the grid: {len(report.points_outside_grid)}")
    for statistic in report.lookup_variable_statistics:
        print(
            f"    {statistic.name:26s} RMSE={statistic.root_mean_squared_error:12.3f} {statistic.units:3s}"
            f"  max abs err={statistic.maximum_absolute_error:12.3f}"
        )
