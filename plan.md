# performance-mapper — Design

A Python package (PyPI: `performance-mapper`, import: `performance_mapper`) of utilities for
working with performance maps as structured by ASHRAE Standard 205 (and the forthcoming
Standard 232). The package is agnostic to what a map describes (HVAC equipment or otherwise);
it is specific to the grid-variable/lookup-variable structure. The initial feature is
translating sparse or unstructured performance points into a regular grid. Visualization and
other utilities come later.

Domain vocabulary lives in [CONTEXT.md](CONTEXT.md).

## Data model

- **`PointTable`** — the input: a collection of equal-length columns, each with a `name`,
  koozie-compliant `units` string (`""` = unitless), and `values: list[float]`. Row *i*
  across columns is one performance point. Validated at construction: equal lengths,
  non-empty, unique names, finite values (no NaN/inf — dense data is a v1 contract).
- **`PerformanceMap`** — the output: `grid_variables` (each with `name`, `units`, and its
  axis values) and `lookup_variables` (each with `name`, `units`, and a flattened value
  list of length ∏(axis lengths), **row-major with the last grid variable varying
  fastest**, matching the 205 array convention). Values are stored in their declared
  units; units are metadata carried by this package (205 representations fix units in the
  schema, so exporters — not the map — reconcile them).
- A future utility will convert row-oriented data (`list[dict]`) into a `PointTable`.

## Public API

`PointTable.to_performance_map()` is the sole public entry point — thin sugar over a
private engine module:

```python
performance_map = points.to_performance_map(
    grid_variables=[GridVariableSpecification(...), ...],
    lookup_variables=[LookupVariableSpecification(...), ...],
    interpolation_method=RadialBasisFunction(kernel="thin_plate_spline", smoothing=0.0),
    fit_report=False,
)
```

With `fit_report=True` it returns `(performance_map, fit_report)`, scipy-style.

- **`LookupVariableSpecification`**: `name`, `units`, optional `transformation`.
- **`GridVariableSpecification`**: the same, plus the axis inputs — exactly one of:
  - `values=[...]` — explicit axis values;
  - `range=(low, high)` + `number_of_points` — linear spacing (count, not step; a `step`
    option may come later);
  - neither — the axis defaults to the **sorted unique values** of the variable's derived
    per-point data (exact float equality; ideal for sparse-but-structured data; documented
    degenerate behavior for truly scattered data — pass `range` + count there). Smarter,
    user-selectable default algorithms are a future feature.
  - optional `axis_units`: the units in which `values`/`range` are expressed; defaults to
    the declared `units`. (Affine conversions keep a regular axis regular.)
- Naming standard: no abbreviations in identifiers (e.g., `specification`, not `spec`),
  with rare obvious exceptions.

## Units (koozie)

SI is the internal currency, per koozie's philosophy:

1. **Ingest:** every input column is converted to SI with `fr_u`.
2. **Middle:** all engine math and all transformation lambdas operate on SI floats.
3. **Egress:** each output variable declares units; `to_u` runs last; the map stores
   values in declared units.

Unitless columns use `units=""` (koozie accepts it today; `"-"` does not parse). `%` is a
legitimate unit for dimensionless-but-united data.

## Transformations

- Applied **per input point, before any interpolation** — derived values then serve as
  interpolation coordinates or data.
- Signature: one row-dict per point, keyed by input column name, SI values in, SI float
  out: `transformation=lambda point: point["capacity"] / (RHO * CP * (point["outlet temperature"] - point["inlet temperature"]))`.
  No source-column declaration needed.
- Grid and lookup variables share the mechanism — a derived quantity (e.g., flow rate) can
  be a grid axis.
- A variable with no transformation is identity-sourced from the same-named input column
  (error if absent); for these, declared output units are dimensionally checked against
  the input column's units via koozie at validation time. Derived variables trust the
  documented SI contract (a lambda returns a bare float; no check is possible).

## Interpolation engine

- Default method: `scipy.interpolate.RBFInterpolator`, thin-plate-spline kernel,
  `smoothing=0.0` (exact interpolation; `smoothing > 0` gives regression behavior and
  tolerates replicate conditions).
- Method selection: the `interpolation_method` parameter takes a small frozen strategy
  object implementing a private fit/evaluate interface; `RadialBasisFunction(...)` is the
  default and only v1 implementation. Future methods are new classes.
- **Coordinates are always min-max normalized to [0, 1] internally** (over the union of
  data points and requested grid) before fitting — non-optional; SI-mixed magnitudes
  (kelvin next to m³/s) would otherwise blind the kernel along small axes.
- All grid variables are continuous coordinates in v1 — no discrete/categorical axes.
  Data at one "compressor sequence number" influences fitted surfaces at neighboring
  numbers (documented caveat; acceptable because sequence numbers do not always represent
  distinct speeds).

## Validation & repair

- Fail fast with named-column/named-point messages: length mismatches, NaN/inf, unknown
  source columns, dimensional incompatibilities, too few points for the kernel
  (thin-plate-spline needs ≥ d+1 points in non-degenerate position).
- **Duplicate grid coordinates (replicates) are auto-averaged** across their lookup
  values, with a warning listing the collisions.

## Extrapolation policy

Always allowed — no warnings, no clamping; deliberate envelope extension is a first-class
use case. Exposure is made visible in the fit report instead (see below).

## Fit report (optional)

`fit_report=True` evaluates how well the *regular grid* reproduces the original points the
way a downstream consumer will read it: each original point is located in grid space (same
transformations), the grid is read back by **multilinear interpolation**
(`scipy.interpolate.RegularGridInterpolator`), and predictions are compared to actuals.
With `smoothing=0` the RBF surface is exact at data points, so this measures
**discretization error** — "is my grid resolution good enough?"

Contents:

- `r_squared` — single overall score; residuals measured as Euclidean distance in
  normalized lookup space (each lookup scaled by its data range), `R² = 1 − SS_res/SS_tot`
  over in-grid points.
- Per-lookup-variable statistics in declared units: RMSE, max |error|, mean bias — plus
  raw per-point residuals for debugging.
- Original points outside the grid's axis ranges: excluded from statistics, listed.
- **Extrapolation zones** for grid points, by rising risk: inside the data's convex hull
  (true interpolation); outside the hull but inside the bounding box (gap-filling);
  outside the bounding box (pure extrapolation). Hull membership via Delaunay
  triangulation of normalized coordinates; 1-D grids treat hull ≡ box; degenerate
  (coplanar) data falls back to box-only with a flag.
- Per-grid-variable coverage: axis min/max vs. data min/max in declared units (absolute
  values, so affine temperature conversions stay honest).

## Import/export

The `to_*`/`from_*` conversion family:

- `PerformanceMap.to_point_table()` — flatten the grid, one point per grid point, in
  declared units. Enables chained re-gridding and delegating exports.
- `PointTable.to_csv(path)` / `PointTable.from_csv(path)` — standard-library `csv`; no
  pandas required to import or use this package.
- `PointTable.to_dataframe()` / `PointTable.from_dataframe(df)` — lazy pandas import,
  helpful error if missing; pandas is an optional extra.
- `PerformanceMap.to_csv(path)` / `.to_dataframe()` — one-line delegation through
  `to_point_table()`.
- Header convention (CSV and DataFrame labels): `name (units)` — e.g.
  `inlet_temperature (K)`; the rightmost trailing parenthesized group is the units; a
  header with no trailing group is unitless.

## Packaging

- Scaffolded with atheneum-forge (`forge-cli init . performance_mapper --type python`);
  the forge template dictates build/CI/lint conventions.
- Runtime dependencies: `scipy`, `koozie` only. Optional extra: `performance-mapper[pandas]`.
- Python ≥ 3.10 (koozie's floor), unless the forge template dictates newer.
- License: BSD-3-Clause.

## Worked example (from the original plan)

Input columns: inlet temperature (°F), capacity (kBtu/h), outlet temperature (°F).
Requested map: grid of inlet temperature (K) × flow rate (m³/s) — flow rate derived from
capacity and ΔT via a transformation — with capacity (W) as the lookup variable. The
chiller study's "Percent load" → "compressor sequence number" step-function transformation
is the same mechanism producing a (continuous) grid axis.

## Future features (explicitly deferred)

- Performance map visualization.
- Row-oriented (`list[dict]`) → `PointTable` converter.
- Smarter/user-selectable default axis algorithms; snapping tolerance for near-duplicate
  axis values; `step`-based spacing.
- Discrete/per-slice grid variables; per-lookup missing-value masks.
- Additional interpolation methods; per-axis scale weights.
- 205/232-aware adapters (schema-fixed units, RS-specific structures).
