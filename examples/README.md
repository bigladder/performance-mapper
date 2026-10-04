# performance-mapper examples

Runnable, self-contained examples built on a **synthetic** water-cooled chiller dataset.
The data is fabricated from a small physics model and contains no private information, but
it reproduces the structure that makes real equipment data instructive: a handful of
independent design setpoints, dependent results derived from them, and a condenser
condition that diverges from its design value at part load.

Column names and units follow the `PerformanceMapCoolingLiquid` section of the **ASHRAE 205
RS0001 (Chiller)** schema exactly — every column is a schema Data Element name, and every
value is in that element's **SI** unit (temperatures in K, volumetric flows in m³/s, powers
and capacities in W, the compressor sequence number dimensionless).

## Two datasets, one difference

The schema has a single condenser grid variable, `condenser_liquid_entering_temperature`. To
show why the *design* value is a better axis than the *actual* value, the generator emits two
tables from the **same physical operating points** — identical in every column except that
one:

| File | `condenser_liquid_entering_temperature` holds |
|------|-----------------------------------------------|
| `data/chiller_design_conditions.csv` | the **design** setpoint (constant per design case) |
| `data/chiller_actual_conditions.csv` | the **actual** simulated value (pinned toward a common minimum-condensing-temperature floor at part load) |

## Layout

| File | What it is |
|------|------------|
| `generate_synthetic_chiller.py` | Synthesizes both datasets into `data/`. |
| `load_and_map.py` | Basic usage: load points, build one map over all five schema grid variables, read the fit report. |
| `design_vs_actual_axis.py` | Feeds both datasets to the same three-axis map to show the design column is the better axis. |
| `compare_grids.py` | The overspecification lesson: 5/4/3 grid variables, read-back R² vs. convex-hull coverage. |
| `hull_vs_box_dashboard.py` | Interactive 3-D coverage view with a toggle to switch between the two datasets. |
| `_chiller_common.py` | Shared helpers (dataset paths, Data Element names, grid/lookup specs, coverage printing). |

Read the scripts in table order; `_chiller_common.py` is support code, not a starting point.

## Running them

The examples are a member of the repository's [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/),
so their plotting dependencies (`dash`, `plotly`) stay out of the core package's dependency
tree and are installed only when this member is synced. Run any script from the repository
root with `--package`:

```
uv run --package performance-mapper-examples python examples/load_and_map.py
uv run --package performance-mapper-examples python examples/design_vs_actual_axis.py
uv run --package performance-mapper-examples python examples/compare_grids.py
uv run --package performance-mapper-examples python examples/hull_vs_box_dashboard.py   # opens a local web server
```

The committed CSVs are enough to run everything; regenerate them only if you change the model:

```
uv run --package performance-mapper-examples python examples/generate_synthetic_chiller.py
```

## The lesson they teach together

A performance map is only as good as the region its grid nodes actually cover, and the
usual quality metric hides the problem. The scripts make that concrete:

- **`load_and_map.py`** builds the map the schema suggests — all five CoolingLiquid grid
  variables. It reads back at R² ≈ 1.0, yet almost none of its grid nodes fall inside the
  data's convex hull: the five axes are not independent, so the data lies on a
  lower-dimensional manifold and nearly every delivered node is unsupported.
- **`compare_grids.py`** dials the same effect up and down. Dropping the two dependent flow
  axes barely moves the read-back R² (it only ever measured the fit *at the input points*),
  while the fraction of the grid inside the convex hull climbs from ~1 % to ~82 %.
- **`design_vs_actual_axis.py`** isolates the condenser axis. With the *design* value, each
  grid node lands on a single operating point (exact read-back, high coverage, no
  duplicates). With the *actual* value, distinct design cases collapse onto one coordinate
  at part load, so the map must silently average physically different operating points.
- **`hull_vs_box_dashboard.py`** draws the three-axis grid in 3-D and lets you switch the
  condenser column between design and actual values: green nodes interpolate safely inside
  the data, amber nodes fill gaps never simulated, red nodes (none here) would be
  extrapolation. The design view is small and mostly green (49 of 60 nodes inside the hull);
  the actual view is four times larger and less supported (136 of 240 inside the hull, with
  104 amber gap-fill nodes).

This is the motivating case for the proposed grid-axis independence warning: a cheap,
setup-time signal that the chosen axes are redundant, before any of this shows up in an
after-the-fact fit report.
