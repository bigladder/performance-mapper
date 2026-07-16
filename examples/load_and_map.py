"""Load the synthetic chiller points and build one performance map (the basic usage).

This is the "hello world" of the package: read a table of scattered performance points,
declare the grid axes and the looked-up outputs, and get back a ``PerformanceMap`` on a
regular grid plus a fit report describing how trustworthy it is.

The grid here uses all five RS0001 ``PerformanceMapCoolingLiquid`` grid variables -- both
volumetric flows, both liquid temperatures, and the compressor sequence number -- exactly
as the ASHRAE 205 chiller schema lays them out, with the two capacities and input power as
the lookup outputs. It reads the realistic ``actual`` dataset (the condenser entering
temperature is the simulated value the machine actually ran at).

It runs and produces a map -- but watch the coverage line: the fit reproduces the input
points almost perfectly, yet almost none of the delivered grid nodes fall inside the data's
convex hull, because the five axes are not independent (the flows are a design-rule function
of the temperatures, and the actual condenser temperature is pinned by control at part
load). ``compare_grids.py`` and ``design_vs_actual_axis.py`` unpack why, and what to choose
instead.

Run:
    uv run --package performance-mapper-examples python examples/load_and_map.py
"""

from __future__ import annotations

from _chiller_common import ACTUAL_DATA_PATH, full_grid_variables, load_points, lookup_variables, print_coverage


def main() -> None:
    points = load_points(ACTUAL_DATA_PATH)
    print(f"loaded {len(points)} performance points from {ACTUAL_DATA_PATH.name}")
    print(f"columns: {list(points.column_names)}\n")

    performance_map, report = points.to_performance_map(
        grid_variables=full_grid_variables(),
        lookup_variables=lookup_variables(),
        fit_report=True,
    )

    print("grid axes (each defaults to the sorted unique values of its column):")
    for grid_variable in performance_map.grid_variables:
        units = f" {grid_variable.units}" if grid_variable.units else ""
        print(f"  {grid_variable.name}: {len(grid_variable.values)} values{units}")
    print()
    print_coverage(performance_map, report)


if __name__ == "__main__":
    main()
