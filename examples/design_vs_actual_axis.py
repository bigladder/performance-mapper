"""Show why the condenser axis should carry *design* values, not *actual* ones.

The RS0001 schema has a single condenser grid variable, ``condenser_liquid_entering_temperature``.
The two generated datasets fill it differently from the same physical operating points:

  * ``chiller_design_conditions.csv`` .. the design setpoint (constant per design case), and
  * ``chiller_actual_conditions.csv`` .. the actual simulated value (pinned toward a common
                                          minimum-condensing-temperature floor at part load).

This script feeds each dataset to the *same* three-axis map -- evaporator leaving
temperature, condenser entering temperature, and compressor sequence number, with input
power and net evaporator capacity as the lookups -- and prints the coverage of each.

The design values are constant for a design case across load, so each grid node lands on
exactly one operating point: the read-back is exact and most nodes sit inside the data's
convex hull. The actual values collapse distinct design cases onto the same coordinate at
low load, so the lookups become multivalued there; the engine averages those duplicate
points (emitting ``DuplicatePointsWarning``) and the map needs far more, less-supported
nodes to cover the scattered temperatures.

This is the same phenomenon the proposed grid-axis independence warning is meant to catch
before the fit even runs (see docs/design/design-axis-independence-warning.md); here it is
visible after the fact, in the coverage.

Run:
    uv run --package performance-mapper-examples python examples/design_vs_actual_axis.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

from _chiller_common import (
    ACTUAL_DATA_PATH,
    DESIGN_DATA_PATH,
    load_points,
    lookup_variables,
    print_coverage,
    reduced_grid_variables,
)

from performance_mapper import DuplicatePointsWarning


def build_from(path: Path) -> None:
    """Build the three-axis map from one dataset, print its coverage, and report any collapse."""
    points = load_points(path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        performance_map, report = points.to_performance_map(
            grid_variables=reduced_grid_variables(),
            lookup_variables=lookup_variables(),
            fit_report=True,
        )

    print_coverage(performance_map, report)

    duplicates = [warning for warning in caught if issubclass(warning.category, DuplicatePointsWarning)]
    if duplicates:
        # Count how many grid coordinates collected more than one input point, and how many
        # points were folded away, straight from the warning message ("points [i, j, ...]").
        message = str(duplicates[0].message)
        groups = message.count("points [")
        averaged = sum(part.count(",") + 1 for part in message.split("points [")[1:])
        print(f"  DuplicatePointsWarning: {averaged} points collapsed onto {groups} shared grid coordinates")
    else:
        print("  no duplicate points: every grid coordinate held a single operating point")


def main() -> None:
    print("=== design conditions (condenser_liquid_entering_temperature = design setpoint) ===")
    build_from(DESIGN_DATA_PATH)

    print("\n=== actual conditions (condenser_liquid_entering_temperature = simulated value) ===")
    build_from(ACTUAL_DATA_PATH)

    print(
        "\nBoth maps read back at R^2 = 1.0, so that metric alone cannot tell them apart -- which\n"
        "is exactly the trap. The difference shows in the grid size, the convex-hull coverage, and\n"
        "the duplicate warning: filling the condenser axis with actual values needs far more nodes,\n"
        "covers less of its grid from inside the data, and silently averages physically distinct\n"
        "operating points that share a condenser temperature at part load. Prefer design values."
    )


if __name__ == "__main__":
    main()
