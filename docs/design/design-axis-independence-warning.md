# Design — Grid-axis independence warning

Status: **proposed** (not yet implemented; targeted at a future branch).
Companion to [plan.md](plan.md); domain vocabulary in [CONTEXT.md](../CONTEXT.md).

## Summary

Add an early, cheap diagnostic that warns when the chosen **grid variables are not
mutually independent** — i.e. one axis is (nearly) a function of the others, so the
performance points occupy a lower-dimensional manifold inside the grid's bounding box.
When that happens, most delivered grid nodes require extrapolation and the map is
untrustworthy away from the data, even though the fit reproduces the input points well.

The warning fires at grid-setup time (before any interpolation), names the offending
axis and the variable most responsible, and mirrors the existing
`DuplicatePointsWarning` idiom. It **complements** the after-the-fact convex-hull
coverage already reported by `FitReport`: the warning is the setup-time smoke alarm;
the coverage is the post-fit forensic measurement.

## Motivation

Observed on a real dataset (an RTWD water-cooled chiller, 140 performance points). The
map was built with seven grid axes — `LWT Evap`, `EWT Evap`, `Flow Evap`, `LWT Cond`,
`EWT Cond`, `Flow Cond`, `Compressor Stage`. Only three of those are genuinely
independent control inputs (`LWT Evap`, the nominal condenser entering temperature, and
load/stage). The other four are *dependent results*:

- `EWT Evap` and `LWT Cond` are fixed by the evaporator and condenser energy balances
  (leaving temp = entering temp + duty / (flow · specific heat)).
- `Flow Evap` and `Flow Cond` are set by a design rule keyed to the temperature
  setpoints.

Using dependent variables as axes collapsed the data onto a ~3-D manifold inside the
7-D box. The result: the fit report's read-back R² was ~1.0 (the grid reproduces the
on-manifold input points), yet **0 of 86,400 grid nodes fell inside the data's convex
hull** — every delivered node was extrapolation. Nothing warned the user at the time
they chose the axes; the problem only surfaced later, in the convex-hull coverage of a
requested fit report. This feature closes that gap.

## The measures

Three ways to quantify "is this axis redundant with the others," in increasing power:

- **Pearson correlation coefficient** — strength of the *linear* relationship between
  two variables; ranges −1…+1. Defined for exactly one pair of columns.
- **Spearman rank correlation** — Pearson's coefficient computed on the *ranks* of the
  values rather than the values themselves. It measures *monotone* association (one
  variable consistently rising or falling with the other, straight-line or curved),
  and is invariant to any monotone rescaling of an axis.
- **Multiple R² / Variance Inflation Factor (VIF)** — regress one axis on **all** the
  others jointly; `R²_j` is the fraction of that axis's variance explained by the rest,
  and `VIF_j = 1 / (1 − R²_j)`. This is the multivariate measure: it detects an axis
  that is a function of a *combination* of others, which no single pairwise correlation
  can see.

### Why the multivariate measure must be primary

Pairwise correlation is fragile because an axis can depend jointly on two others while
correlating weakly with each one alone. `Flow Evap` is the case in point — it is a
design-rule function of `LWT Evap` and the nominal condenser temperature together:

| measure for `Flow Evap`                              | value |
|------------------------------------------------------|-------|
| pairwise Pearson r vs `LWT Evap`                     | 0.927 |
| pairwise Pearson r vs `Nominal EWT Cond`             | 0.021 |
| multiple R² on {`LWT Evap`, `Nominal EWT Cond`}      | 0.997 |

The dependence on the second driver is essentially invisible pairwise. In this dataset
`Flow Evap` still gets flagged pairwise — but only incidentally, because `LWT Evap`
happens to dominate its variance and the two flows co-vary (r = 0.989). Change the
design so a flow depends more evenly on its two drivers, or include only one flow, and
a pairwise threshold of |r| ≥ 0.95 would **miss it**, while the multiple-R² of 0.997
still catches it. Hence: **multiple R² / VIF is the detector; pairwise Spearman is used
only to name the single most-responsible partner in the message.**

### Evidence (RTWD chiller, 140 points, seven-axis set)

Multiple R² of each axis regressed on the other six:

| axis              | multiple R² | VIF      |
|-------------------|-------------|----------|
| LWT Evap          | 1.0000      | ~1.1e8   |
| EWT Evap          | 1.0000      | ~1.3e8   |
| Flow Evap         | 0.9994      | ~1.7e3   |
| LWT Cond          | 0.9999      | ~1.7e4   |
| EWT Cond          | 0.9999      | ~1.0e4   |
| Flow Cond         | 0.9998      | ~4.1e3   |
| Compressor Stage  | 1.0000      | ~1.0e7   |

Every axis is ~100% explained by the others — the statistical fingerprint of the same
manifold collapse that produced 0% convex-hull coverage. Pearson and Spearman pairwise
matrices agree closely except where the ordinal `Compressor Stage` participates in a
monotone-but-nonlinear relation (e.g. `LWT Cond`–`Stage`: Spearman 0.938 vs Pearson
0.851; `EWT Cond`–`Stage`: 0.813 vs 0.739), where Spearman is the stronger, safer
signal.

## Proposed implementation

### Hook point

A *hook point* is the location in existing source where the new behaviour is inserted.
The per-point derived-value matrix already exists in `_Regridding.__init__`:

- `_engine.py:66` — `grid_data = np.column_stack([_derive(s, si_points) for s in grid_specifications])`
- `_engine.py:68` — `self.grid_data, ... = _average_duplicates(grid_data, lookup_data)`

Run the check on `self.grid_data` (the de-duplicated points) immediately after
`_engine.py:68`, and before the minimum-points guard at `_engine.py:74`. Correlation
and R² are scale-invariant, so no min-max normalization is needed first.

### Warning class and check (sketch — not yet applied)

```python
class NonIndependentAxesWarning(UserWarning):
    """Grid axes are strongly inter-dependent; the data lies on a lower-dimensional
    manifold, so many grid nodes will require extrapolation."""


_HIGH_MULTIPLE_R_SQUARED = 0.99   # equivalently VIF >= 100
_HIGH_PAIRWISE_RHO = 0.95
_MINIMUM_POINTS_PER_AXIS = 2      # need n >= 2k, else multiple R^2 overfits to 1.0


def _warn_if_axes_dependent(grid_data: np.ndarray, names: list[str]) -> None:
    n, k = grid_data.shape
    if k < 2 or n < _MINIMUM_POINTS_PER_AXIS * k:
        return
    variable = grid_data.std(axis=0) > 1e-12   # skip constant columns (undefined correlation)
    if variable.sum() < 2:
        return
    idx = np.flatnonzero(variable)
    x = grid_data[:, idx]
    rho = np.atleast_2d(scipy.stats.spearmanr(x).statistic)  # monotone-correlation matrix
    messages = []
    for local, column in enumerate(idx):
        y = x[:, local]
        others = np.delete(x, local, axis=1)
        design = np.column_stack([np.ones(n), others])
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        ss_res = float(((y - design @ beta) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        partner = np.abs(rho[local]).copy()
        partner[local] = 0.0
        best = int(np.argmax(partner))
        if r_squared >= _HIGH_MULTIPLE_R_SQUARED or partner[best] >= _HIGH_PAIRWISE_RHO:
            messages.append(
                f"'{names[column]}' is {r_squared:.1%}-explained by the other axes "
                f"(strongest single partner: '{names[idx[best]]}', "
                f"Spearman rho={rho[local, best]:+.2f})"
            )
    if messages:
        warnings.warn(
            "Grid axes appear not to be independent, so the data occupies a "
            "lower-dimensional manifold and many grid nodes will require extrapolation: "
            + "; ".join(messages)
            + ". Consider using only independent variables as grid axes.",
            NonIndependentAxesWarning,
            stacklevel=4,
        )
```

Call site, immediately after `_engine.py:68`:

```python
_warn_if_axes_dependent(self.grid_data, [s.name for s in grid_specifications])
```

### Thresholds and message

- Primary trigger: multiple R² ≥ **0.99** (VIF ≥ 100).
- Secondary trigger / partner naming: Spearman |rho| ≥ **0.95**.
- The message names both the flagged axis and its strongest single "explained-by"
  partner — the other axis most correlated with it — so the user knows what to drop.
  Example: *"'Flow Cond' is 99.8%-explained by the other axes (strongest single
  partner: 'Flow Evap', Spearman rho=+0.99)"*.

### Edge cases

- **Constant columns.** An axis whose derived value is identical for every point has a
  standard deviation of zero, and correlation with it is undefined (division by zero →
  NaN). The `std > 1e-12` mask drops such columns before any correlation is computed.
  (The RTWD data has three: the two design-ΔT columns and `Design LWT Evap`.)
- **Too few points.** With `n` points and `k` axes, if `n < 2k` the least-squares fit
  can reach R² = 1.0 by coincidence and falsely signal dependence, so the check bails.
  This is stricter than the engine's own `n >= k + 1` requirement at `_engine.py:74`.
- **Single variable axis / all-but-one constant.** Returns early (nothing to correlate).

## API choice

Raise `NonIndependentAxesWarning` **always**, from the engine, exactly as
`DuplicatePointsWarning` is raised today. Rationale:

- It changes **no return value** — `PerformanceMap` and `FitReport` are untouched; a
  warning is orthogonal to results, and callers already silence engine warnings with
  `warnings.catch_warnings()` when they want to.
- It fires **before the fit**, which is the whole point: cheap and early, and
  independent of whether `fit_report=True` was requested.
- It matches an existing idiom, so there is no new public API to document or maintain.

Rejected alternatives: an **opt-in flag** adds public surface and hides the warning
from the users who most need it; a **new `FitReport` field** is post-hoc, requires
`fit_report=True`, and mutates the report structure. If programmatic access is later
desired, add a *supplementary* frozen field (e.g. `axis_dependencies`) computed
alongside the existing coverage in `build_fit_report`, but keep the warning as the
primary mechanism.

## Relationship to convex-hull coverage

They measure different things at different times and do not duplicate each other:

- **This warning** is an early, inexpensive, statistical heuristic on the input points
  alone — "are your chosen axes redundant?" It runs in `__init__` before fitting, costs
  O(n·k²), needs no grid evaluation, and names which axis to drop. It can raise false
  positives (correlated axes that still span the space) and cannot prove coverage.
- **`grid_points_outside_convex_hull`** (see `fit_report.py` and
  `_engine.py:159` `_extrapolation_zones`) is the definitive, geometric, post-hoc
  measure: it counts exactly how many delivered grid nodes are extrapolation. It is
  authoritative but only available after building the map with `fit_report=True`, and it
  reports the symptom (low coverage), not the cause (which axes are dependent).

Together: the warning is the diagnosis at the moment the user can cheaply act on it; the
coverage is the confirmation and quantification after the fit.

## Testing notes (for the implementation branch)

- A dependent-axis fixture (e.g. `z = x + y` with independent `x`, `y`) should raise the
  warning via the multiple-R² trigger while its pairwise correlations stay moderate —
  this guards the "multivariate is primary" behaviour against regressions.
- An independent-axis fixture should raise nothing.
- Constant-column and `n < 2k` fixtures should raise nothing (no NaN, no false positive).
- Use `pytest.warns(NonIndependentAxesWarning)` / `warnings.catch_warnings` with
  `error` to assert presence and absence precisely.

## Open questions

- Exact threshold values (0.99 / 0.95) — defensible defaults, but may want tuning or a
  module-level constant users can adjust.
- Whether to also expose the structured `axis_dependencies` data now or defer until a
  concrete consumer needs it (YAGNI leans toward defer).
