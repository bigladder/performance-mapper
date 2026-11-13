import numpy as np
import pytest
from koozie import fr_u

from performance_mapper import (
    Column,
    DuplicatePointsWarning,
    GridVariableSpecification,
    LookupVariableSpecification,
    PointTable,
)


def test_fills_hole_in_sparse_structured_data() -> None:
    """Points on a 3x3 grid with the center missing; default axes recover the grid and
    thin-plate-spline reproduces the (linear) surface at the hole exactly."""
    points = [(x, y) for x in (0.0, 1.0, 2.0) for y in (0.0, 5.0, 10.0) if (x, y) != (1.0, 5.0)]
    table = PointTable(
        [
            Column("x", "", [p[0] for p in points]),
            Column("y", "", [p[1] for p in points]),
            Column("z", "", [2.0 * p[0] + 3.0 * p[1] + 1.0 for p in points]),
        ]
    )
    performance_map = table.to_performance_map(
        grid_variables=[GridVariableSpecification("x"), GridVariableSpecification("y")],
        lookup_variables=[LookupVariableSpecification("z")],
    )
    assert performance_map.grid_variables[0].values == (0.0, 1.0, 2.0)
    assert performance_map.grid_variables[1].values == (0.0, 5.0, 10.0)
    expected = [2.0 * x + 3.0 * y + 1.0 for x in (0.0, 1.0, 2.0) for y in (0.0, 5.0, 10.0)]
    assert np.allclose(performance_map.lookup_variables[0].values, expected, atol=1e-8)


def test_lookup_values_are_row_major_with_last_grid_variable_fastest() -> None:
    table = PointTable(
        [
            Column("x", "", [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]),
            Column("y", "", [0.0, 1.0, 2.0, 0.0, 1.0, 2.0]),
            Column("z", "", [0.0, 1.0, 2.0, 10.0, 11.0, 12.0]),  # z = 10x + y
        ]
    )
    performance_map = table.to_performance_map(
        grid_variables=[GridVariableSpecification("x"), GridVariableSpecification("y")],
        lookup_variables=[LookupVariableSpecification("z")],
    )
    assert np.allclose(performance_map.lookup_variables[0].values, [0.0, 1.0, 2.0, 10.0, 11.0, 12.0], atol=1e-8)


def test_unit_conversion_on_ingest_and_egress() -> None:
    table = PointTable(
        [
            Column("inlet temperature", "degF", [32.0, 212.0]),
            Column("capacity", "kBtu/h", [1.0, 2.0]),
        ]
    )
    performance_map = table.to_performance_map(
        grid_variables=[GridVariableSpecification("inlet temperature", "K")],
        lookup_variables=[LookupVariableSpecification("capacity", "W")],
    )
    assert np.allclose(performance_map.grid_variables[0].values, [273.15, 373.15])
    assert np.allclose(performance_map.lookup_variables[0].values, [fr_u(1.0, "kBtu/h"), fr_u(2.0, "kBtu/h")])


def test_transformation_creates_derived_grid_variable() -> None:
    """A step transformation turns a continuous input column into an integer-valued grid axis."""
    table = PointTable(
        [
            Column("valve opening", "%", [10.0, 35.0, 60.0, 85.0]),
            Column("heat rate", "W", [5.0, 10.0, 15.0, 20.0]),
        ]
    )
    performance_map = table.to_performance_map(
        grid_variables=[
            GridVariableSpecification(
                "valve position index", "", transformation=lambda point: round(point["valve opening"] * 4) + 1
            )
        ],
        lookup_variables=[LookupVariableSpecification("heat rate", "W")],
    )
    assert performance_map.grid_variables[0].values == (1.0, 2.0, 3.0, 4.0)
    assert np.allclose(performance_map.lookup_variables[0].values, [5.0, 10.0, 15.0, 20.0], atol=1e-8)


def test_transformations_receive_si_values() -> None:
    captured: list[dict[str, float]] = []

    def record(point: dict[str, float]) -> float:
        captured.append(point)
        return point["inlet temperature"]

    table = PointTable([Column("inlet temperature", "degC", [0.0, 100.0])])
    table.to_performance_map(
        grid_variables=[GridVariableSpecification("t", "K", transformation=record)],
        lookup_variables=[LookupVariableSpecification("t out", "K", transformation=record)],
    )
    assert captured[0]["inlet temperature"] == pytest.approx(273.15)


def test_axis_units_apply_to_range() -> None:
    table = PointTable(
        [
            Column("inlet temperature", "degC", [0.0, 50.0, 100.0]),
            Column("power", "W", [1.0, 2.0, 3.0]),
        ]
    )
    performance_map = table.to_performance_map(
        grid_variables=[
            GridVariableSpecification(
                "inlet temperature", "K", range=(32.0, 212.0), number_of_points=2, axis_units="degF"
            )
        ],
        lookup_variables=[LookupVariableSpecification("power", "W")],
    )
    assert np.allclose(performance_map.grid_variables[0].values, [273.15, 373.15])


def test_duplicate_points_are_averaged_with_warning() -> None:
    table = PointTable(
        [
            Column("x", "", [1.0, 1.0, 2.0]),
            Column("y", "", [10.0, 20.0, 30.0]),
        ]
    )
    with pytest.warns(DuplicatePointsWarning, match=r"points \[0, 1\]"):
        performance_map = table.to_performance_map(
            grid_variables=[GridVariableSpecification("x")],
            lookup_variables=[LookupVariableSpecification("y")],
        )
    assert performance_map.grid_variables[0].values == (1.0, 2.0)
    assert np.allclose(performance_map.lookup_variables[0].values, [15.0, 30.0], atol=1e-8)


def test_to_point_table_round_trip() -> None:
    table = PointTable(
        [
            Column("x", "", [0.0, 0.0, 1.0, 1.0]),
            Column("y", "", [0.0, 1.0, 0.0, 1.0]),
            Column("z", "", [0.0, 1.0, 10.0, 11.0]),
        ]
    )
    performance_map = table.to_performance_map(
        grid_variables=[GridVariableSpecification("x"), GridVariableSpecification("y")],
        lookup_variables=[LookupVariableSpecification("z")],
    )
    flattened = performance_map.to_point_table()
    assert flattened.column_names == ("x", "y", "z")
    assert flattened.columns[0].values == (0.0, 0.0, 1.0, 1.0)
    assert flattened.columns[1].values == (0.0, 1.0, 0.0, 1.0)
    assert np.allclose(flattened.columns[2].values, [0.0, 1.0, 10.0, 11.0], atol=1e-8)


def test_identity_variable_requires_matching_input_column() -> None:
    table = PointTable([Column("x", "", [1.0, 2.0]), Column("y", "", [1.0, 2.0])])
    with pytest.raises(ValueError, match="no input column"):
        table.to_performance_map(
            grid_variables=[GridVariableSpecification("x")],
            lookup_variables=[LookupVariableSpecification("missing")],
        )


def test_identity_variable_units_must_be_dimensionally_compatible() -> None:
    table = PointTable([Column("x", "degF", [1.0, 2.0]), Column("y", "", [1.0, 2.0])])
    with pytest.raises(ValueError, match="dimensionally compatible"):
        table.to_performance_map(
            grid_variables=[GridVariableSpecification("x", "m")],
            lookup_variables=[LookupVariableSpecification("y")],
        )


def test_axis_inputs_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="not both"):
        GridVariableSpecification("x", "", values=(1.0, 2.0), range=(0.0, 1.0), number_of_points=2)
    with pytest.raises(ValueError, match="given together"):
        GridVariableSpecification("x", "", range=(0.0, 1.0))
