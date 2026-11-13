from pathlib import Path

import pytest

from performance_mapper import Column, PointTable


def make_table() -> PointTable:
    return PointTable(
        [
            Column("inlet temperature", "degF", [45.0, 55.0, 65.0]),
            Column("capacity", "kBtu/h", [10.0, 11.0, 12.0]),
            Column("capacity fraction", "", [0.5, 0.75, 1.0]),
        ]
    )


def test_length_and_names() -> None:
    table = make_table()
    assert len(table) == 3
    assert table.column_names == ("inlet temperature", "capacity", "capacity fraction")


def test_rejects_mismatched_column_lengths() -> None:
    with pytest.raises(ValueError, match="same number of points"):
        PointTable([Column("a", "", [1.0]), Column("b", "", [1.0, 2.0])])


def test_rejects_duplicate_column_names() -> None:
    with pytest.raises(ValueError, match="unique"):
        PointTable([Column("a", "", [1.0]), Column("a", "K", [2.0])])


def test_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        Column("a", "", [1.0, float("nan")])


def test_rejects_empty_table() -> None:
    with pytest.raises(ValueError, match="at least one column"):
        PointTable([])


def test_csv_round_trip(tmp_path: Path) -> None:
    table = make_table()
    path = tmp_path / "points.csv"
    table.to_csv(path)

    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert header == "inlet temperature (degF),capacity (kBtu/h),capacity fraction"

    read_back = PointTable.from_csv(path)
    assert read_back == table


def test_dataframe_round_trip() -> None:
    pytest.importorskip("pandas")
    table = make_table()
    dataframe = table.to_dataframe()
    assert list(dataframe.columns) == [
        "inlet temperature (degF)",
        "capacity (kBtu/h)",
        "capacity fraction",
    ]
    assert PointTable.from_dataframe(dataframe) == table
