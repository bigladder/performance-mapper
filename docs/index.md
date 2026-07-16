# performance-mapper documentation

Utilities for working with performance maps as structured by ASHRAE Standard 205
(and the forthcoming Standard 232): a set of **grid variables** whose values define a
regular grid, and **lookup variables** with one value at every grid point.

This directory holds the project's prose documentation. It is currently a set of
Markdown pages; a documentation generator (mkdocs or sphinx) has not yet been wired up
(see the TODO markers in [`.gitignore`](../.gitignore)).

## Contents

- [Usage and key behaviors](../README.md) — installation, a worked example, and the
  units/transformation/grid-axis conventions.
- [Design and rationale](design/plan.md) — the full design of the point-table-to-performance-map
  translation.
- [Domain vocabulary](CONTEXT.md) — definitions of the grid-variable and
  lookup-variable terminology.

## Package reference

The importable package is `performance_mapper`, laid out under `src/` following the
[src-layout recommended by the Python Packaging User Guide](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).
Its public interface is re-exported from the package's top-level `__init__` module; see
that module's `__all__` for the complete list of exported names.
