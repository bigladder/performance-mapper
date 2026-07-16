"""Compare five-, four-, and three-axis grids to show read-back R-squared and convex-hull
coverage moving in opposite directions -- the "overspecification" lesson.

A performance map is only as trustworthy as the region its grid nodes actually cover. The
RS0001 ``PerformanceMapCoolingLiquid`` grid has five variables, but for this equipment two
of them -- the evaporator and condenser volumetric flows -- are a design-rule function of
the temperature setpoints, not independent knobs. Using them as axes collapses the data
onto a lower-dimensional manifold inside the grid's bounding box: the fit still reproduces
the input points beautifully (high read-back R-squared), but almost none of the delivered
grid nodes fall inside the data, so the map is pure extrapolation away from the points.
Dropping the dependent flow axes barely moves the read-back score while sharply raising the
fraction of the grid that is genuinely supported.

The three axis sets, all with input power and net evaporator capacity as the lookup outputs
and run on the design-conditions dataset (so the condenser axis is clean and the effect
isolates to the flows):

  * 5 axes: every CoolingLiquid grid variable -- both flows are dependent results,
  * 4 axes: drop the condenser flow, and
  * 3 axes: drop both flows, leaving the independent temperatures and the sequence number.

Run:
    uv run --package performance-mapper-examples python examples/compare_grids.py
"""

from __future__ import annotations

import warnings

from _chiller_common import (
    CONDENSER_FLOW,
    DESIGN_DATA_PATH,
    full_grid_variables,
    grid_node_count,
    load_points,
    lookup_variables,
    reduced_grid_variables,
)

from performance_mapper import GridVariableSpecification, PointTable


def _without(grid_variables: list[GridVariableSpecification], name: str) -> list[GridVariableSpecification]:
    return [grid_variable for grid_variable in grid_variables if grid_variable.name != name]


GRIDS = {
    "5 axes (both flows, both temperatures, sequence)": full_grid_variables(),
    "4 axes (drop condenser flow)": _without(full_grid_variables(), CONDENSER_FLOW),
    "3 axes (drop both flows)": reduced_grid_variables(),
}


def summarize(label: str, points: PointTable, grid_variables: list[GridVariableSpecification]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate averaging is expected in the overspecified grids
        performance_map, report = points.to_performance_map(
            grid_variables=grid_variables, lookup_variables=lookup_variables(), fit_report=True
        )

    total = grid_node_count(performance_map)
    outside_box = len(report.grid_points_outside_bounding_box)
    print(f"\n=== {label} ===")
    print(f"  grid nodes: {total:,}")
    print(f"  read-back R^2: {report.r_squared:.4f}")
    if report.convex_hull_evaluated:
        inside_hull = total - outside_box - len(report.grid_points_outside_convex_hull)
        print(f"  inside convex hull: {inside_hull:,} / {total:,} ({100 * inside_hull / total:.1f}%)")
    else:
        print("  inside convex hull: not evaluable (axes degenerate -- the manifold has no volume)")
    print(f"  outside bounding box: {outside_box:,}   input points excluded: {len(report.points_outside_grid)}")


def main() -> None:
    points = load_points(DESIGN_DATA_PATH)
    print(f"loaded {len(points)} performance points from {DESIGN_DATA_PATH.name}")
    for label, grid_variables in GRIDS.items():
        summarize(label, points, grid_variables)
    print(
        "\nRead-back R^2 stays near 1.0 for every grid -- it only measures the fit at the input\n"
        "points, which all lie on the data manifold. Convex-hull coverage tells the real story:\n"
        "it rises as the dependent flow axes are dropped, and only the three independent variables\n"
        "give a grid that is mostly supported by the data."
    )


if __name__ == "__main__":
    main()
