"""Translate irregular chiller operating data in inch-pound units into a regular SI performance map.

The input, ``chiller_operating_points.csv``, holds actual operating points of a water-cooled
chiller: flows in gpm, temperatures in degrees Fahrenheit, load as a percentage of full
capacity, power in kW, and capacity in tons of refrigeration. The output,
``chiller_map_si.csv``, is a performance map on a regular grid whose variables are the
ASHRAE 205 RS0001 ``PerformanceMapCoolingLiquid`` Data Elements, in SI units, with load
expressed as a compressor sequence number.

Every output variable is defined by a transformation of the input columns, which receive
values already converted to SI. The script also writes the figures in ``images/`` that the
example's README embeds.

Run from the repository root:

    uv run --group examples python examples/chiller/translate_to_regular_map.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from koozie import fr_u, to_u  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from performance_mapper import (  # noqa: E402
    FitReport,
    GridVariableSpecification,
    LookupVariableSpecification,
    PerformanceMap,
    PointTable,
)

EXAMPLE_DIRECTORY = Path(__file__).parent
INPUT_PATH = EXAMPLE_DIRECTORY / "chiller_operating_points.csv"
OUTPUT_PATH = EXAMPLE_DIRECTORY / "chiller_map_si.csv"
IMAGE_DIRECTORY = EXAMPLE_DIRECTORY / "images"

# Input column names (inch-pound units are declared in the CSV header).
CHILLED_WATER_FLOW = "chilled water flow"
CHILLED_WATER_LEAVING_TEMPERATURE = "chilled water leaving temperature"
CONDENSER_WATER_FLOW = "condenser water flow"
CONDENSER_WATER_ENTERING_TEMPERATURE = "condenser water entering temperature"
PERCENT_LOAD = "percent load"
POWER = "power"
CAPACITY = "capacity"

# The load steps the chiller was run at, as a fraction of full capacity.
LOAD_STEP = 0.1
MINIMUM_LOAD = 0.2

# How close an operating point must be to the plotted map slice to be drawn beside it.
NEAR_SLICE_FLOW_FRACTION = 0.1
NEAR_SLICE_TEMPERATURE_DIFFERENCE = 1.5  # degF

# Chart styling.
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID_LINE = "#d6d5d0"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
SEQUENTIAL = LinearSegmentedColormap.from_list("blue", ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])


def column_values(points: PointTable, name: str) -> np.ndarray:
    """The values of one input column, in the units of the input file."""
    return np.array(next(column.values for column in points.columns if column.name == name))


def compressor_sequence_number(load_fraction: float) -> int:
    """Number the load steps from 1 at minimum load, rounding each point to its nearest step."""
    return round((load_fraction - MINIMUM_LOAD) / LOAD_STEP) + 1


def grid_variables() -> list[GridVariableSpecification]:
    """Five example grid variables, each with an evenly spaced axis stated in
    inch-pound units through ``axis_units`` and stored in SI.
    """
    return [
        GridVariableSpecification(
            "evaporator_liquid_volumetric_flow_rate",
            "m**3/s",
            transformation=lambda point: point[CHILLED_WATER_FLOW],
            range=(840.0, 1260.0),
            number_of_points=3,
            axis_units="gpm",
        ),
        GridVariableSpecification(
            "evaporator_liquid_leaving_temperature",
            "K",
            transformation=lambda point: point[CHILLED_WATER_LEAVING_TEMPERATURE],
            range=(39.0, 53.0),
            number_of_points=8,
            axis_units="degF",
        ),
        GridVariableSpecification(
            "condenser_liquid_volumetric_flow_rate",
            "m**3/s",
            transformation=lambda point: point[CONDENSER_WATER_FLOW],
            range=(1080.0, 1720.0),
            number_of_points=3,
            axis_units="gpm",
        ),
        GridVariableSpecification(
            "condenser_liquid_entering_temperature",
            "K",
            transformation=lambda point: point[CONDENSER_WATER_ENTERING_TEMPERATURE],
            range=(64.0, 89.0),
            number_of_points=6,
            axis_units="degF",
        ),
        GridVariableSpecification(
            "compressor_sequence_number",
            "",
            transformation=lambda point: compressor_sequence_number(point[PERCENT_LOAD]),
        ),
    ]


def lookup_variables() -> list[LookupVariableSpecification]:
    """Input power, net evaporator capacity, and net condenser capacity (by energy balance), in W."""
    return [
        LookupVariableSpecification("input_power", "W", transformation=lambda point: point[POWER]),
        LookupVariableSpecification("net_evaporator_capacity", "W", transformation=lambda point: point[CAPACITY]),
        LookupVariableSpecification(
            "net_condenser_capacity", "W", transformation=lambda point: point[CAPACITY] + point[POWER]
        ),
    ]


def print_summary(points: PointTable, performance_map: PerformanceMap, report: FitReport) -> None:
    """Print the grid shape, read-back fit quality, and how much of the grid the data supports."""
    total = int(np.prod(performance_map.grid_shape))
    outside_box = len(report.grid_points_outside_bounding_box)
    outside_hull = len(report.grid_points_outside_convex_hull)
    print(f"read {len(points)} operating points from {INPUT_PATH.name}")
    print(f"wrote a {' x '.join(map(str, performance_map.grid_shape))} grid ({total:,} nodes) to {OUTPUT_PATH.name}")
    for grid_variable in performance_map.grid_variables:
        values = ", ".join(f"{value:.6g}" for value in grid_variable.values)
        print(f"  {grid_variable.name} ({grid_variable.units or 'dimensionless'}): {values}")
    print(f"read-back R^2: {report.r_squared:.4f}")
    for statistic in report.lookup_variable_statistics:
        print(f"  {statistic.name}: RMSE {statistic.root_mean_squared_error:,.0f} {statistic.units}")
    if report.convex_hull_evaluated:
        print(
            f"grid nodes inside the data's convex hull: {total - outside_box - outside_hull:,}; "
            f"in the bounding box but outside the hull: {outside_hull:,}; outside the bounding box: {outside_box:,}"
        )
    print(f"input points outside the grid's range: {len(report.points_outside_grid)}")


def style_axes(axes: plt.Axes, title: str, x_label: str, y_label: str) -> None:
    """Apply the shared chart styling: recessive grid and spines, text in text colors."""
    axes.set_facecolor(SURFACE)
    axes.set_title(title, loc="left", color=TEXT_PRIMARY, fontsize=12)
    axes.set_xlabel(x_label, color=TEXT_SECONDARY)
    axes.set_ylabel(y_label, color=TEXT_SECONDARY)
    axes.tick_params(colors=TEXT_SECONDARY, length=0)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(GRID_LINE)


def plot_input_points(points: PointTable, performance_map: PerformanceMap, path: Path) -> None:
    """Scatter the irregular operating temperatures, colored by percent load, over the regular grid."""
    figure, axes = plt.subplots(figsize=(7.5, 5), facecolor=SURFACE)
    for value in to_u(np.array(performance_map.grid_variables[3].values), "degF"):
        axes.axvline(value, color=GRID_LINE, linewidth=1, zorder=0)
    for value in to_u(np.array(performance_map.grid_variables[1].values), "degF"):
        axes.axhline(value, color=GRID_LINE, linewidth=1, zorder=0)
    scatter = axes.scatter(
        column_values(points, CONDENSER_WATER_ENTERING_TEMPERATURE),
        column_values(points, CHILLED_WATER_LEAVING_TEMPERATURE),
        c=column_values(points, PERCENT_LOAD),
        cmap=SEQUENTIAL,
        s=36,
        edgecolors=SURFACE,
        linewidths=1,
        zorder=2,
    )
    colorbar = figure.colorbar(scatter, ax=axes)
    colorbar.set_label("percent load (%)", color=TEXT_SECONDARY)
    colorbar.outline.set_visible(False)
    colorbar.ax.tick_params(colors=TEXT_SECONDARY, length=0)
    style_axes(
        axes,
        "Irregular operating points and the regular grid (lines)",
        "condenser water entering temperature (°F)",
        "chilled water leaving temperature (°F)",
    )
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_load_to_sequence(points: PointTable, path: Path) -> None:
    """Show the step transformation from percent load to compressor sequence number."""
    figure, axes = plt.subplots(figsize=(7.5, 4), facecolor=SURFACE)
    loads = np.linspace(MINIMUM_LOAD - LOAD_STEP / 2, 1.0 + LOAD_STEP / 2, 500)
    axes.plot(
        100 * loads,
        [compressor_sequence_number(load) for load in loads],
        color=TEXT_SECONDARY,
        linewidth=2,
        drawstyle="steps-mid",
        label="transformation",
        zorder=1,
    )
    point_loads = column_values(points, PERCENT_LOAD)
    axes.scatter(
        point_loads,
        [compressor_sequence_number(load / 100) for load in point_loads],
        color=SERIES[0],
        s=36,
        edgecolors=SURFACE,
        linewidths=1,
        label="operating points",
        zorder=2,
    )
    axes.set_yticks(range(1, compressor_sequence_number(1.0) + 1))
    axes.legend(frameon=False, labelcolor=TEXT_SECONDARY, loc="upper left")
    style_axes(axes, "Percent load to compressor sequence number", "percent load (%)", "compressor sequence number")
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_map_slice(points: PointTable, performance_map: PerformanceMap, path: Path) -> None:
    """Plot input power along the condenser temperature axis of the map, for three sequence numbers,
    with the operating points nearest that slice for comparison.
    """
    evaporator_flow_index, evaporator_temperature_index, condenser_flow_index = 1, 2, 0
    grid = performance_map.grid_variables
    power = np.array(performance_map.lookup_variables[0].values).reshape(performance_map.grid_shape)
    sequence_numbers = (1, 5, 9)

    # Compare in the input file's units: gpm, degrees Fahrenheit, and kW.
    slice_evaporator_flow = to_u(grid[0].values[evaporator_flow_index], "gpm")
    slice_evaporator_temperature = to_u(grid[1].values[evaporator_temperature_index], "degF")
    slice_condenser_flow = to_u(grid[2].values[condenser_flow_index], "gpm")
    near_slice = (
        (np.abs(column_values(points, CHILLED_WATER_FLOW) / slice_evaporator_flow - 1.0) < NEAR_SLICE_FLOW_FRACTION)
        & (
            np.abs(column_values(points, CHILLED_WATER_LEAVING_TEMPERATURE) - slice_evaporator_temperature)
            < NEAR_SLICE_TEMPERATURE_DIFFERENCE
        )
        & (np.abs(column_values(points, CONDENSER_WATER_FLOW) / slice_condenser_flow - 1.0) < NEAR_SLICE_FLOW_FRACTION)
    )
    point_sequence = np.array([compressor_sequence_number(load / 100) for load in column_values(points, PERCENT_LOAD)])
    point_condenser_temperature = fr_u(column_values(points, CONDENSER_WATER_ENTERING_TEMPERATURE), "degF")
    point_power = column_values(points, POWER)

    figure, axes = plt.subplots(figsize=(7.5, 5), facecolor=SURFACE)
    condenser_temperatures = np.array(grid[3].values)
    for color, sequence_number in zip(SERIES, sequence_numbers):
        sequence_index = grid[4].values.index(sequence_number)
        slice_power = power[
            evaporator_flow_index, evaporator_temperature_index, condenser_flow_index, :, sequence_index
        ]
        axes.plot(
            condenser_temperatures,
            slice_power / 1000.0,
            color=color,
            linewidth=2,
            marker="o",
            markersize=8,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            label=f"map, sequence {sequence_number}",
        )
        axes.annotate(
            f"sequence {sequence_number}",
            (condenser_temperatures[-1], slice_power[-1] / 1000.0),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            color=TEXT_SECONDARY,
        )
        selected = near_slice & (point_sequence == sequence_number)
        axes.scatter(
            point_condenser_temperature[selected],
            point_power[selected],
            facecolors=SURFACE,
            edgecolors=color,
            linewidths=2,
            s=64,
            marker="D",
            zorder=3,
        )
    axes.scatter(
        [],
        [],
        facecolors=SURFACE,
        edgecolors=TEXT_SECONDARY,
        linewidths=2,
        s=64,
        marker="D",
        label="nearby operating points",
    )
    axes.margins(x=0.12)
    axes.legend(frameon=False, labelcolor=TEXT_SECONDARY, loc="center left")
    slice_note = (
        f"evaporator {grid[0].values[evaporator_flow_index]:.4f} m³/s leaving at "
        f"{grid[1].values[evaporator_temperature_index]:.2f} K; "
        f"condenser {grid[2].values[condenser_flow_index]:.4f} m³/s"
    )
    style_axes(
        axes,
        f"One slice of the SI map\n{slice_note}",
        "condenser_liquid_entering_temperature (K)",
        "input_power (kW)",
    )
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main() -> None:
    points = PointTable.from_csv(INPUT_PATH)
    performance_map, report = points.to_performance_map(grid_variables(), lookup_variables(), fit_report=True)
    performance_map.to_csv(OUTPUT_PATH)
    print_summary(points, performance_map, report)

    IMAGE_DIRECTORY.mkdir(exist_ok=True)
    plot_input_points(points, performance_map, IMAGE_DIRECTORY / "input_points.png")
    plot_load_to_sequence(points, IMAGE_DIRECTORY / "percent_load_to_sequence.png")
    plot_map_slice(points, performance_map, IMAGE_DIRECTORY / "map_slice.png")
    print(f"wrote figures to {IMAGE_DIRECTORY.relative_to(EXAMPLE_DIRECTORY.parent.parent)}")


if __name__ == "__main__":
    main()
