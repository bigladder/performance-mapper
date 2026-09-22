# Design — Decimal-place rounding on write

Status: **proposed** (not yet implemented; targeted at a future branch).
Companion to [plan.md](plan.md); domain vocabulary in [CONTEXT.md](../CONTEXT.md).

## Summary

Add an optional `decimal_places` parameter that lets the caller round numeric output to a
chosen number of digits after the decimal point. It appears on two methods, for two
different reasons:

- `PointTable.to_csv()` — formats the text written to the file. The point table itself is
  untouched.
- `PointTable.to_performance_map()` — rounds the floating-point values actually stored in
  the returned `PerformanceMap`, so every downstream consumer sees clean numbers without
  the caller repeating the argument at each write.

The parameter accepts either a single integer, applying to every variable, or a mapping
keyed by variable name, applying per variable. Its default of `None` leaves all values
unrounded, so existing behaviour is unchanged.

## Motivation

Nothing in the library converts a float to a string deliberately. `PointTable.to_csv`
relies on the implicit `str()` that `csv.writer` performs on each value
(`table.py:125`), and the regridding engine applies declared units with no rounding step
(`_engine.py:244-245`):

```python
def _in_units(si_values: np.ndarray, units: str) -> tuple[float, ...]:
    return tuple(float(to_u(value, units)) for value in si_values)
```

Two consequences show up in real output. First, grid axis values inherit binary
floating-point noise — a chilled-liquid temperature that should read `277.15` is stored
and written as `277.15000000000003`, because the axis is built in SI and converted back
through `koozie`. Second, interpolated lookup values are written with the full sixteen
digits of a double, nearly all of them meaningless against input data known to a few
significant figures.

A performance map is a publishable artifact — it is the thing handed to a consumer or
serialized into an ASHRAE 205 representation. Digit noise in that artifact is both
misleading about precision and unpleasant to read.

The repository already recognises the need, but only outside the library:
`examples/generate_synthetic_chiller.py:186` hand-rolls its CSV writer specifically to
control precision, using six significant figures with an integer special case:

```python
str(int(row[name])) if name == "compressor_sequence_number" else f"{row[name]:.6g}"
```

That workaround exists because the library offers no rounding option. This design adds
one.

## Design

### Why the parameter belongs on methods, not on `Column`

The obvious alternative is a `decimal_places` field on `Column`, alongside `name` and
`units`, so precision travels with the data and every writer honours it automatically.
That was considered and rejected, because **precision is only meaningful once the final
units are fixed**, and a `Column` never knows them.

A `Column` describes an *input*. The engine converts input columns to SI on ingest
(`_engine.py:175`) and applies each specification's declared units as the final step. The
output variables are constructed from the specifications, not from the input columns
(`_engine.py:98,102`):

```python
GridVariable(s.name, s.units, _in_units(axis, s.units))
```

Only `s.name` and `s.units` survive that step. A precision declared on an input column
would therefore describe the wrong units entirely — six decimal places is right for a flow
rate in m³/s and absurd for the same flow rate in gal/min — and would never reach a
`PerformanceMap` at all.

Declaring it on the specification classes instead was also considered. It would put the
value where the units are declared, which is the right place conceptually, but it requires
a defaulted field on `LookupVariableSpecification` (`specifications.py:19`), which
`GridVariableSpecification` inherits from — shifting the positional order of `values`,
`range`, `number_of_points`, and `axis_units`. It also forces the caller to restate
precision when they only want it for one particular write. A method parameter costs
nothing at construction time and reads naturally at the call site.

### Two methods, two meanings

The distinction is worth stating plainly, because the two are not interchangeable:

| method | what it changes | who it serves |
|--------|-----------------|---------------|
| `to_csv` | the text in the file; the `PointTable` is unmodified | tables that never became a map — raw input data, or a table read back from disk |
| `to_performance_map` | the floats stored in the returned `PerformanceMap` | anyone consuming the map — CSV, DataFrame, or a future 205 exporter |

Because `str()` of a rounded float never emits more digits than were requested, a map
rounded at `to_performance_map` already writes clean CSV with no further argument. The
`to_csv` parameter is not redundant with it, but it is the secondary case.

### The parameter

One keyword-only parameter in every signature, so no existing positional call site changes
meaning:

```python
table.to_csv(path, decimal_places=3)                     # every column
table.to_csv(path, decimal_places={"capacity": 1})       # per column; others unrounded

performance_map, report = points.to_performance_map(
    grid_variables=full_grid_variables(),
    lookup_variables=lookup_variables(),
    fit_report=True,
    decimal_places={
        "evaporator liquid volumetric flow rate": 6,
        "evaporator liquid leaving temperature": 2,
        "input power": 1,
        "net evaporator capacity": 1,
    },
)
```

The mapping form is the one that matters for real data. The ASHRAE 205 chiller example
spans five orders of magnitude within a single table — a flow rate near `0.0167` m³/s
alongside a capacity near `348740` W — so one precision for all variables necessarily
either destroys the flow rate or leaves the capacity noisy.

**Decimal places, not significant figures.** Fixed digits after the decimal point. This is
a different convention from the six significant figures used in
`examples/generate_synthetic_chiller.py:186`, and the two disagree on the same data:

| value | 3 decimal places | 3 significant figures |
|--------------|------------------|-----------------------|
| `0.0167101`  | `0.017`          | `0.0167`              |
| `277.15`     | `277.15`         | `277.0`               |
| `61397.9312` | `61397.931`      | `61400.0`             |
| `348740.04`  | `348740.04`      | `349000.0`            |

Decimal places is the right primitive here precisely because the units are known: two
places in kelvin and six in m³/s each express a physically meaningful tolerance, whereas
significant figures express a relative one.

**No trailing-zero padding.** The semantics are rounding, not fixed-point formatting. At
three decimal places, `277.15` writes as `277.15`, not `277.150`. This keeps `to_csv` and
`to_performance_map` byte-identical in their output and keeps files tight. A caller who
wants padded, aligned columns is formatting a report, not exporting data, and should format
it themselves.

**Negative values are accepted** and passed through to `round`, which rounds to tens and
hundreds. This is deliberate rather than incidental: `decimal_places={"net evaporator
capacity": -2}` is a reasonable way to express a capacity in watts known to the nearest
hundred.

**`None` is the default and means no rounding.** This is not merely a courtesy to existing
callers; it is required. `test_csv_round_trip` (`test/test_point_table.py:44-53`) asserts
exact `PointTable` equality after `from_csv`, and the regridding tests compare values at
`atol=1e-8`. Any default rounding would break both.

### New module

A new `src/performance_mapper/rounding.py`, holding the public type alias and two helpers.
It depends on nothing else in the package, so both `table.py` and `_engine.py` can import
it at module scope without disturbing the lazy imports that currently break the
`table` ↔ `performance_map` cycle (`table.py:115`, `performance_map.py:61`).

Sketch — not yet applied:

```python
"""How much precision to keep when writing values."""

DecimalPlaces = Union[int, Mapping[str, int], None]
"""Digits to keep after the decimal point. An integer applies to every variable; a
mapping applies per variable name; ``None`` leaves values unrounded."""


def resolve(decimal_places: DecimalPlaces, name: str) -> int | None:
    """The precision for one variable, or ``None`` if it should not be rounded."""
    if decimal_places is None or isinstance(decimal_places, int):
        return decimal_places
    return decimal_places.get(name)


def validate_names(decimal_places: DecimalPlaces, valid_names: Sequence[str], subject: str) -> None:
    """Reject mapping keys that match no variable, so a typo cannot pass silently."""
    if decimal_places is None or isinstance(decimal_places, int):
        return
    unknown = sorted(set(decimal_places) - set(valid_names))
    if unknown:
        raise ValueError(
            f"'decimal_places' names {unknown}, which are not {subject}. "
            f"Available: {sorted(valid_names)}."
        )
```

`DecimalPlaces` is exported from `__init__.py` and added to `__all__`, following the
precedent of the `Transformation` alias (`specifications.py:10`, exported at
`__init__.py:12`), so callers can annotate their own wrappers.

`validate_names` exists because the failure it prevents is invisible. A mapping key that
matches no variable would simply do nothing, and the caller would conclude the feature was
broken rather than that they had misspelled a name. Its message follows the style of
`_validate_specifications` (`_engine.py:194-197`), which already lists available column
names when a specification does not match.

### Hook points

A *hook point* is the location in existing source where the new behaviour is inserted.

#### `table.py`

- `to_csv` (line 121) — validate mapping keys against `self.column_names`, then round each
  value as rows are emitted. The header row (line 124) and `_label` are unchanged.
- `to_dataframe` (line 143) — the same parameter, rounding the float values so a DataFrame
  the caller writes themselves matches the CSV.
- `to_performance_map` (lines 85-119) — the parameter must be added to **both** `@overload`
  stubs as well as the implementation, and forwarded to `regrid`. Adding it only to the
  implementation would leave it invisible to type checkers.
- `from_csv` (line 128) and `from_dataframe` (line 148) are unchanged.

#### `_engine.py` — the substantive work

In pipeline order:

1. **`regrid` (line 36)** gains the parameter and forwards it to `_Regridding.__init__`.

2. **After `_validate_specifications` (line 63)** — call `validate_names` against the grid
   and lookup specification names.

3. **Immediately after `_axis_si` (lines 70-73)**, and critically *before* the
   normalization bounds (lines 80-84) and `meshgrid` (lines 86-87) are derived from the
   axes. Axes are stored in SI, but rounding must happen in the specification's declared
   `units` — not `axis_units`, which only describes how axis inputs were supplied — so the
   value must be converted out, rounded, checked, and converted back.

   Sketch — not yet applied:

   ```python
   def _round_axis_si(
       axis_si: np.ndarray, specification: GridVariableSpecification, decimal_places: int | None
   ) -> np.ndarray:
       if decimal_places is None:
           return axis_si
       rounded = np.round([to_u(value, specification.units) for value in axis_si], decimal_places)
       if len(np.unique(rounded)) != len(rounded):
           raise ValueError(
               f"Grid variable '{specification.name}': rounding to {decimal_places} decimal "
               f"places collapses distinct axis values into {_collisions(rounded)}."
           )
       return np.array([fr_u(value, specification.units) for value in rounded])
   ```

   The existing distinctness check on explicitly supplied `values` (lines 235-236) stays as
   it is. This new check is separate and covers all three axis paths — explicit values, a
   `range` with `number_of_points`, and the sorted unique derived values.

4. **After `self.grid_values` is computed (line 95)** — round each lookup column in its
   declared units and write it back in SI.

5. **`_in_units` (lines 244-245)** gains an optional `decimal_places` argument, used at
   lines 98 and 102. This is *not* redundant with steps 3 and 4: the SI round trip through
   `fr_u` and `to_u` is not bit-exact for affine temperature units, so a final round
   guarantees the stored values are exactly what was requested.

#### `performance_map.py`

Pure delegation, matching the existing one-line style (lines 75-79):

```python
def to_csv(self, path: Any, *, decimal_places: DecimalPlaces = None) -> None:
    self.to_point_table().to_csv(path, decimal_places=decimal_places)
```

`to_point_table()` itself is unchanged — it is the flattening step, not a writer.

Argument counts stay within the `max-args = 6` pylint ceiling configured in
`pyproject.toml`.

### Why grid axes are rounded before fitting

This is the one decision with a visible consequence beyond the numbers themselves.

Rounding an axis moves the grid points. If the axis were rounded *after* the interpolant
had been evaluated, the map would claim a lookup value belongs at `277.15` when it was
actually computed at `277.15000000000003`. At fine precision that is harmless, but at
coarse precision it is a real misattribution — rounding a temperature axis to zero decimal
places would label a value computed at 277.15 K as belonging at 277 K.

More importantly, the fit report is built from the axes. `build_fit_report` derives its
in-grid mask from `self.axes_si` (lines 110-112), reads the map back through
`RegularGridInterpolator` over those same axes (`_read_back`, lines 145-157), and takes
`axis_minimum` and `axis_maximum` from the finished `PerformanceMap` (lines 130-131). If
rounding happened last, `r_squared`, the per-variable RMSE, the coverage comparison, and
the extrapolation-zone counts would all describe a map that was never returned.

Rounding the axes in `__init__` and the lookup values in `build_performance_map` — both
before `build_fit_report` runs — means the report describes the delivered map exactly.
`r_squared` will be slightly lower with rounding than without, and that is the honest
number.

What is deliberately **not** rounded:

- `self.grid_data` — the scattered source points the interpolant is fitted to. These are
  the measurements; rounding them would discard information rather than tidy output.
- The `data_minimum` and `data_maximum` fields of `GridVariableCoverage` (lines 132-133),
  which come from `self.grid_data`. Leaving them at full precision keeps the axis-versus-data
  coverage comparison honest.

## API choice

Add `decimal_places` as a keyword-only parameter with a `None` default to
`PointTable.to_csv`, `PointTable.to_dataframe`, `PointTable.to_performance_map`,
`PerformanceMap.to_csv`, and `PerformanceMap.to_dataframe`. Rationale:

- It is **opt-in and inert by default**, so no existing behaviour, test, or round trip
  changes.
- It sits where the units are already known, which is the only place the value can be
  interpreted.
- It is **one parameter with two accepted forms** rather than two parameters, keeping the
  signatures within the project's argument-count limit and giving a short form for the
  common case without losing per-variable control.

Rejected alternatives:

- **A field on `Column`** — describes input units, and never reaches the output map. See
  "Why the parameter belongs on methods" above.
- **A field on the specification classes** — conceptually well placed, but shifts the
  positional order of `GridVariableSpecification`'s own fields through inheritance, and
  forces precision to be declared at construction rather than at write time.
- **A separate `significant_figures` parameter** — a genuinely useful second convention,
  and the one the example generator already uses, but it doubles the surface to build,
  document, and test. Deferred; see Open questions.
- **A module-level or global default** — invisible at the call site, and hostile to a
  library whose output is someone else's input.

## Edge cases

- **Collapsed axes.** Coarse rounding can merge two nearby axis values into one, producing
  a malformed grid with a repeated coordinate. The engine's existing check catches this only
  for explicitly supplied `values` (lines 235-236), so the new post-rounding check applies to
  every axis path and raises `ValueError` naming the variable, the precision, and the
  colliding values, so the caller can choose a finer precision. Warning and silently merging
  was considered — it would follow the `DuplicatePointsWarning` idiom — but it changes the
  grid shape the caller asked for, which is worse than a clear failure.
- **Affine unit round trips.** Temperature conversions are affine, not merely scaling, so
  converting a rounded value to SI and back is not guaranteed bit-exact. The final round in
  `_in_units` absorbs this.
- **Unknown mapping keys.** Rejected with a message listing valid names, rather than
  ignored.
- **Negative precision.** Accepted and forwarded to `round`; rounds to tens and hundreds.
- **Integer-valued variables.** A variable such as a compressor sequence number is stored as
  a float like every other value, so rounding it to zero decimal places yields `5.0`, not
  `5`. This design does not introduce an integer column type; the generator's `int` special
  case (`examples/generate_synthetic_chiller.py:186`) remains its own concern.
- **Lookup values only, no grid rounding.** Naturally expressible with the mapping form by
  simply omitting the grid variable names.

## Testing notes (for the implementation branch)

Follow the existing conventions: plain annotated `def test_*() -> None:` functions, local
factories such as `make_table()` rather than fixtures, `tmp_path`, and the
read-the-text-back-and-compare-an-exact-string assertion at `test_point_table.py:44-53`.

In `test/test_point_table.py`:

- A value needing many digits survives `to_csv` → `from_csv` untouched by default. This
  guards the inert default directly, complementing the existing `test_csv_round_trip`.
- `to_csv` with an integer, asserting the exact file text.
- `to_csv` with a mapping, asserting one column rounded and another left alone.
- `to_csv` rejects an unknown mapping key, via `pytest.raises(ValueError, match=...)`.
- `to_dataframe` rounding, guarded by `pytest.importorskip("pandas")` as at line 57.

In `test/test_regridding.py`:

- `to_performance_map` rounds both axis values and lookup values, asserted by exact tuple
  equality on `grid_variables[i].values` — the style already used in that file.
- `PerformanceMap.to_csv` and `.to_dataframe` honour the parameter through delegation.
- `to_performance_map` rejects an unknown mapping key.
- Rounding that collapses an axis raises, with the variable name in the message.
- **The fit report reflects the rounded map**: build the same map with and without rounding
  and assert that `r_squared` differs. This is the test that guards the
  round-axes-before-fitting decision against a later refactor quietly moving the rounding to
  the end of the pipeline, where every other test would still pass.

## Documentation to update

- `docs/design/plan.md`, the "Import/export" section (lines 136-150) — the authoritative
  spec for this method family. Record the parameter, both accepted forms, the no-padding
  rule, and that rounding in `to_performance_map` precedes fitting.
- The matching "Import/export" bullet in `README.md`.
- No new term needs defining in [CONTEXT.md](../CONTEXT.md); "decimal places" is plain
  language, not domain vocabulary.

## Open questions

- **Should `to_dataframe` round at all?** Unlike `to_csv` it changes numeric data rather
  than presentation, so it is arguably the caller's job via `DataFrame.round`. Included here
  for symmetry with `to_csv`, but it is the weakest part of the surface.
- **Should the six-significant-figure convention be reconciled?**
  `examples/generate_synthetic_chiller.py:186` will still hand-roll its writer after this
  change, leaving the repository with two precision conventions. Adding a
  `significant_figures` parameter later would let that example use the library and remove
  the duplication.
- **Where does precision ultimately belong for 205 export?** An ASHRAE 205 representation
  exporter — deferred at `plan.md:176` — may carry schema-driven precision per field, which
  would make map-level rounding a sensible default rather than the final word. Worth
  confirming this parameter does not conflict with that before the exporter is designed.
- **Should collapsed-axis detection suggest a precision?** The error could compute and
  report the finest precision that would keep all axis values distinct. Helpful, but more
  logic in an error path; deferred unless it proves annoying in practice.
