[![Build and Test](https://github.com/bigladder/performance-mapper/actions/workflows/build-and-test.yaml/badge.svg)](https://github.com/bigladder/performance-mapper/actions/workflows/build-and-test.yaml)

# performance-mapper

Utilities for working with performance maps as structured by ASHRAE Standard 205 (and the
forthcoming Standard 232): a set of **grid variables** whose values define a regular grid,
and **lookup variables** with one value at every grid point. The package is agnostic to
what a map describes — HVAC equipment or otherwise.

The core operation translates sparse or scattered performance points (a `PointTable`) into
a `PerformanceMap` on a regular grid, using radial basis function interpolation
(thin-plate-spline by default). See [docs/design/plan.md](docs/design/plan.md) for the
full design and [docs/CONTEXT.md](docs/CONTEXT.md) for the domain vocabulary.

## Usage

```python
from performance_mapper import (
    Column,
    GridVariableSpecification,
    LookupVariableSpecification,
    PointTable,
)

points = PointTable(
    [
        Column("inlet temperature", "degF", [44.0, 44.0, 54.0, 54.0, 64.0]),
        Column("outlet temperature", "degF", [54.0, 60.0, 64.0, 70.0, 74.0]),
        Column("capacity", "kBtu/h", [10.0, 14.0, 11.0, 15.0, 12.0]),
    ]
)

WATER_VOLUMETRIC_HEAT_CAPACITY = 4.18e6  # J/(m³·K)

performance_map, fit_report = points.to_performance_map(
    grid_variables=[
        GridVariableSpecification("inlet temperature", "K"),
        GridVariableSpecification(
            "flow rate",
            "m**3/s",
            transformation=lambda point: point["capacity"]
            / (WATER_VOLUMETRIC_HEAT_CAPACITY * (point["outlet temperature"] - point["inlet temperature"])),
            range=(1.0e-4, 1.6e-4),
            number_of_points=4,
        ),
    ],
    lookup_variables=[LookupVariableSpecification("capacity", "W")],
    fit_report=True,
)
```

Key behaviors:

- **Units** are koozie-compliant strings (`""` = unitless). Input columns are converted to
  SI on ingest; transformations receive and return SI values; the finished map stores
  values in each variable's declared units.
- **Transformations** are per-point lambdas receiving a dictionary keyed by input column
  name; they can define grid variables and lookup variables alike.
- **Grid axes** come from explicit `values`, a linear `range`/`number_of_points` spacing
  (optionally expressed in `axis_units`), or default to the sorted unique values of the
  data.
- **Lookup values** are flattened row-major with the last grid variable varying fastest
  (the ASHRAE 205 array convention).
- **The fit report** (optional, scipy-style tuple return) measures how well the grid
  reproduces the original points under multilinear read-back, and classifies grid points
  by extrapolation risk (inside the data's convex hull, gap-filling inside the bounding
  box, or pure extrapolation).
- **Import/export**: `PointTable` ⇄ CSV (standard library) and pandas DataFrames
  (optional extra: `pip install performance-mapper[pandas]`);
  `PerformanceMap.to_point_table()` flattens a map back into a table.

## Examples

The [examples](examples/README.md) directory holds self-contained examples, each in its own
directory with its data, script, figures, and README.

| Example | Description |
|---------|-------------|
| [chiller](examples/chiller/README.md) | Translates irregular inch-pound chiller operating data, with percent load, into a regular map in SI units with compressor sequence numbers, whose variables follow the ASHRAE 205 RS0001 (Chiller) schema. |

The examples' plotting dependency is in the `examples` dependency group, so it is not
installed with the core package. Run an example from the repository root:

```
uv run --group examples python examples/chiller/translate_to_regular_map.py
```

## Development

This Python project is managed with [uv](https://docs.astral.sh/uv/#installation):

```
uv run pytest test    # run the test suite
uv run ruff check .   # lint
uv run mypy performance_mapper test
```
