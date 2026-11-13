"""Translate chiller operating data in inch-pound units into a regular SI performance map.

The input, ``chiller_irregular_data.csv`` (written by ``generate_irregular_data.py``),
holds irregular data for a water-cooled chiller: flows in gpm, temperatures in degrees
Fahrenheit, load as a percentage of full capacity, power in kW, and capacity in tons of
refrigeration. The output, ``chiller_map_si.csv``, is a performance map on a regular grid, in
SI units, with load expressed as a compressor sequence number.

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
INPUT_PATH = EXAMPLE_DIRECTORY / "chiller_irregular_data.csv"
OUTPUT_PATH = EXAMPLE_DIRECTORY / "chiller_map_si.csv"
IMAGE_DIRECTORY = EXAMPLE_DIRECTORY / "images"

# Input column names (inch-pound units are declared in the CSV header).
CHILLED_WATER_FLOW = "chilled water flow"
CHILLED_WATER_LEAVING_TEMPERATURE = "chilled water leaving temperature"
CONDENSER_WATER_FLOW = "condenser water flow"
CONDENSER_WATER_ENTERING_TEMPERATURE = "condenser water entering temperature"
CONDENSER_WATER_LEAVING_TEMPERATURE = "condenser water leaving temperature"
PERCENT_LOAD = "percent load"
POWER = "power"
CAPACITY = "capacity"

# Compressor sequence numbers run from 1 at a flow's minimum load to this value at full load.
HIGHEST_SEQUENCE_NUMBER = 4

# Condenser flows (gpm) are matched to one decimal place, the precision of the input file.
FLOW_DECIMALS = 1

# Volumetric heat capacity of water near 75 degF, in J/(m**3 K).
WATER_VOLUMETRIC_HEAT_CAPACITY = 997.0 * 4181.0

# The plotted map slice: grid indices of chilled water flow, chilled water leaving temperature,
# and condenser water flow, and the compressor sequence numbers drawn.
SLICE_INDICES = (1, 2, 1)
SLICE_SEQUENCE_NUMBERS = (1, 2, 3, 4)

# How close an irregular data point must be to the plotted map slice to be drawn beside it.
NEAR_SLICE_FLOW_FRACTION = 0.05
NEAR_SLICE_TEMPERATURE_DIFFERENCE = 1.5  # degF
NEAR_SLICE_SEQUENCE_DIFFERENCE = 0.2

# Chart styling.
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID_LINE = "#d6d5d0"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#8a5cd1"]
SEQUENTIAL = LinearSegmentedColormap.from_list("blue", ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])


def column_values(points: PointTable, name: str) -> np.ndarray:
    """The values of one input column, in the units of the input file."""
    return np.array(next(column.values for column in points.columns if column.name == name))


def flow_key(condenser_water_flow: float) -> float:
    """A condenser flow in gpm, rounded so that every point of one run shares the same key."""
    return round(condenser_water_flow, FLOW_DECIMALS)


def minimum_load_by_flow(points: PointTable) -> dict[float, float]:
    """The lowest load fraction measured at each condenser flow (gpm)."""
    minimum_loads: dict[float, float] = {}
    for flow, percent_load in zip(column_values(points, CONDENSER_WATER_FLOW), column_values(points, PERCENT_LOAD)):
        key = flow_key(flow)
        minimum_loads[key] = min(minimum_loads.get(key, 1.0), percent_load / 100)
    return minimum_loads


def compressor_sequence_number(load_fraction: float, minimum_load_fraction: float) -> float:
    """Scale load linearly from 1 at the lowest load measured at the point's flow to
    ``HIGHEST_SEQUENCE_NUMBER`` at full load. A flow measured only at full load gets the
    highest sequence number."""
    if minimum_load_fraction >= 1.0:
        return float(HIGHEST_SEQUENCE_NUMBER)
    return 1.0 + (HIGHEST_SEQUENCE_NUMBER - 1) * (load_fraction - minimum_load_fraction) / (1.0 - minimum_load_fraction)


def grid_variables(minimum_loads: dict[float, float]) -> list[GridVariableSpecification]:
    """Five grid variables. The flow and temperature axes are evenly spaced, stated in
    inch-pound units through ``axis_units`` and stored in SI; the sequence number axis holds
    the whole numbers from 1 to ``HIGHEST_SEQUENCE_NUMBER``.
    """
    return [
        GridVariableSpecification(
            "evaporator_liquid_volumetric_flow_rate",
            "m**3/s",
            transformation=lambda point: point[CHILLED_WATER_FLOW],
            range=(346.5, 515.7),
            number_of_points=3,
            axis_units="gpm",
        ),
        GridVariableSpecification(
            "evaporator_liquid_leaving_temperature",
            "K",
            transformation=lambda point: point[CHILLED_WATER_LEAVING_TEMPERATURE],
            range=(42.0, 62.0),
            number_of_points=5,
            axis_units="degF",
        ),
        GridVariableSpecification(
            "condenser_liquid_volumetric_flow_rate",
            "m**3/s",
            transformation=lambda point: point[CONDENSER_WATER_FLOW],
            range=(417.4, 585.9),
            number_of_points=3,
            axis_units="gpm",
        ),
        GridVariableSpecification(
            "condenser_liquid_entering_temperature",
            "K",
            transformation=lambda point: point[CONDENSER_WATER_ENTERING_TEMPERATURE],
            range=(65.0, 85.0),
            number_of_points=5,
            axis_units="degF",
        ),
        GridVariableSpecification(
            "compressor_sequence_number",
            "",
            transformation=lambda point: compressor_sequence_number(
                point[PERCENT_LOAD], minimum_loads[flow_key(to_u(point[CONDENSER_WATER_FLOW], "gpm"))]
            ),
            values=tuple(float(number) for number in range(1, HIGHEST_SEQUENCE_NUMBER + 1)),
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


def condenser_temperature_rise(points: PointTable) -> np.ndarray:
    """Condenser water leaving minus entering temperature at each point, in degrees Fahrenheit."""
    return column_values(points, CONDENSER_WATER_LEAVING_TEMPERATURE) - column_values(
        points, CONDENSER_WATER_ENTERING_TEMPERATURE
    )


def print_heat_balance(points: PointTable) -> None:
    """Compare the heat the condenser water carries away with capacity plus power, and fit
    percent load as a straight line in the condenser temperature rise."""
    rise = condenser_temperature_rise(points)
    carried = (
        fr_u(column_values(points, CONDENSER_WATER_FLOW), "gpm")
        * fr_u(rise, "delta_degF")
        * WATER_VOLUMETRIC_HEAT_CAPACITY
    )
    rejected = fr_u(column_values(points, CAPACITY), "ton_ref") + fr_u(column_values(points, POWER), "kW")
    ratio = carried / rejected
    print(f"condenser heat balance, carried / (capacity + power): {ratio.min():.3f} to {ratio.max():.3f}")
    percent_load = column_values(points, PERCENT_LOAD)
    slope, intercept = np.polyfit(rise, percent_load, 1)
    residual = percent_load - (slope * rise + intercept)
    print(
        f"percent load ~ {slope:.2f} x condenser rise (degF) {intercept:+.2f}; "
        f"RMS error {np.sqrt(np.mean(residual**2)):.2f} %, largest {np.abs(residual).max():.2f} %"
    )


def print_summary(points: PointTable, performance_map: PerformanceMap, report: FitReport) -> None:
    """Print the grid shape, read-back fit quality, and how much of the grid the data supports."""
    total = int(np.prod(performance_map.grid_shape))
    outside_box = len(report.grid_points_outside_bounding_box)
    outside_hull = len(report.grid_points_outside_convex_hull)
    print(f"read {len(points)} irregular data points from {INPUT_PATH.name}")
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
    print(f"irregular data points outside the grid's range: {len(report.points_outside_grid)}")


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


def plot_irregular_data(points: PointTable, performance_map: PerformanceMap, path: Path) -> None:
    """Scatter the operating temperatures, colored by percent load, over the regular grid. Each
    run's points spread left from its nominal condenser temperature as condenser relief lowers it."""
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
        s=48,
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
        "Irregular data and the regular grid (lines)",
        "condenser water entering temperature (°F)",
        "chilled water leaving temperature (°F)",
    )
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_load_against_condenser_rise(points: PointTable, path: Path) -> None:
    """Plot percent load against the condenser water temperature rise, colored by the nominal
    (full-load) condenser water entering temperature of each point's run."""
    rise = condenser_temperature_rise(points)
    percent_load = column_values(points, PERCENT_LOAD)
    flows = column_values(points, CONDENSER_WATER_FLOW)
    entering = column_values(points, CONDENSER_WATER_ENTERING_TEMPERATURE)
    full_load = percent_load == 100  # noqa: PLR2004
    full_load_entering = {
        flow_key(flow): temperature for flow, temperature in zip(flows[full_load], entering[full_load])
    }
    nominal = np.array([full_load_entering[flow_key(flow)] for flow in flows])

    figure, axes = plt.subplots(figsize=(7.5, 4.5), facecolor=SURFACE)
    axes.plot([0, 10], [0, 100], color=GRID_LINE, linewidth=2, zorder=0, label="percent load = 10 × rise")
    for color, temperature in zip(SERIES, sorted(set(nominal))):
        selected = nominal == temperature
        axes.scatter(
            rise[selected],
            percent_load[selected],
            color=color,
            s=36,
            edgecolors=SURFACE,
            linewidths=1,
            zorder=2,
            label=f"nominal condenser water {temperature:.0f} °F",
        )
    axes.legend(frameon=False, labelcolor=TEXT_SECONDARY, loc="upper left")
    style_axes(
        axes,
        "Percent load follows the condenser water temperature rise",
        "condenser water leaving − entering temperature (°F)",
        "percent load (%)",
    )
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_map_slice(
    points: PointTable, minimum_loads: dict[float, float], performance_map: PerformanceMap, path: Path
) -> None:
    """Plot net evaporator capacity along the condenser temperature axis of the map, for three sequence numbers,
    with the irregular data points nearest that slice for comparison.
    """
    evaporator_flow_index, evaporator_temperature_index, condenser_flow_index = SLICE_INDICES
    grid = performance_map.grid_variables
    capacity = np.array(performance_map.lookup_variables[1].values).reshape(performance_map.grid_shape)

    # Select nearby points in the input file's units: gpm and degrees Fahrenheit.
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
    point_sequence = np.array(
        [
            compressor_sequence_number(load / 100, minimum_loads[flow_key(flow)])
            for load, flow in zip(column_values(points, PERCENT_LOAD), column_values(points, CONDENSER_WATER_FLOW))
        ]
    )
    point_condenser_temperature = fr_u(column_values(points, CONDENSER_WATER_ENTERING_TEMPERATURE), "degF")
    point_capacity = fr_u(column_values(points, CAPACITY), "ton_ref") / 1000.0

    figure, axes = plt.subplots(figsize=(7.5, 5), facecolor=SURFACE)
    condenser_temperatures = np.array(grid[3].values)
    for color, sequence_number in zip(SERIES, SLICE_SEQUENCE_NUMBERS):
        sequence_index = grid[4].values.index(sequence_number)
        slice_capacity = capacity[
            evaporator_flow_index, evaporator_temperature_index, condenser_flow_index, :, sequence_index
        ]
        axes.plot(
            condenser_temperatures,
            slice_capacity / 1000.0,
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
            (condenser_temperatures[-1], slice_capacity[-1] / 1000.0),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            color=TEXT_SECONDARY,
        )
        selected = near_slice & (np.abs(point_sequence - sequence_number) < NEAR_SLICE_SEQUENCE_DIFFERENCE)
        axes.scatter(
            point_condenser_temperature[selected],
            point_capacity[selected],
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
        label="nearby irregular data",
    )
    axes.set_ylim(bottom=0)
    axes.margins(x=0.12)
    axes.legend(frameon=False, labelcolor=TEXT_SECONDARY, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3)
    slice_note = (
        f"evaporator {grid[0].values[evaporator_flow_index]:.4f} m³/s leaving at "
        f"{grid[1].values[evaporator_temperature_index]:.2f} K; "
        f"condenser {grid[2].values[condenser_flow_index]:.4f} m³/s"
    )
    style_axes(
        axes,
        f"One slice of the SI map\n{slice_note}",
        "condenser_liquid_entering_temperature (K)",
        "net_evaporator_capacity (kW)",
    )
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main() -> None:
    points = PointTable.from_csv(INPUT_PATH)
    minimum_loads = minimum_load_by_flow(points)
    performance_map, report = points.to_performance_map(
        grid_variables(minimum_loads), lookup_variables(), fit_report=True
    )
    performance_map.to_csv(OUTPUT_PATH)
    print_summary(points, performance_map, report)
    print_heat_balance(points)

    IMAGE_DIRECTORY.mkdir(exist_ok=True)
    plot_irregular_data(points, performance_map, IMAGE_DIRECTORY / "irregular_data.png")
    plot_load_against_condenser_rise(points, IMAGE_DIRECTORY / "load_against_condenser_rise.png")
    plot_map_slice(points, minimum_loads, performance_map, IMAGE_DIRECTORY / "map_slice.png")
    print(f"wrote figures to {IMAGE_DIRECTORY.relative_to(EXAMPLE_DIRECTORY.parent.parent)}")


if __name__ == "__main__":
    main()
