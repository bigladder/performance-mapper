# Performance Mapper

A Python package for working with data structured as performance maps; specific to the grid-variable/lookup-variable structure.

## Language

**Performance map**:
A data structure pairing a set of grid variables with a set of lookup variables.

**Grid variable**:
An independent variable whose distinct values define one axis of a regular grid.

**Lookup variable**:
A dependent variable with one value at every point of the grid defined by the grid variables.

**Performance point**:
A single observed or simulated operating condition — one value for each variable. Points need not lie on any grid.

**Point table**:
A collection of performance points. Unlike a performance map, its points are unstructured (sparse or scattered).

**Transformation**:
A function that computes a derived variable's value at a single performance point from that point's other values. Applies equally to grid and lookup variables.

**Derived variable**:
An output variable (grid or lookup) whose values come from a transformation rather than directly from an input column.

**Grid fit**:
How faithfully a performance map, read back the way consumers read it (multilinear interpolation), reproduces the point table it was built from.

**Extrapolation zone**:
The risk classification of a grid point relative to the source data: inside the data's convex hull (interpolation), outside the hull but inside the bounding box (gap-filling), or outside the bounding box (pure extrapolation).
