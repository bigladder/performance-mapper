"""Interpolation methods used to fit scattered performance points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np
from scipy.interpolate import RBFInterpolator

Evaluator = Callable[[np.ndarray], np.ndarray]
"""Maps coordinates with shape (number of points, dimensions) to values with shape (number of points, variables)."""


class InterpolationMethod(Protocol):
    """Fits normalized scattered coordinates to lookup values and returns an evaluator."""

    def fit(self, coordinates: np.ndarray, values: np.ndarray) -> Evaluator: ...


@dataclass(frozen=True)
class RadialBasisFunction:
    """Radial basis function interpolation (scipy), exact at data points when smoothing is zero.

    A positive ``smoothing`` relaxes exactness into a regression through the data.
    """

    kernel: str = "thin_plate_spline"
    smoothing: float = 0.0

    def fit(self, coordinates: np.ndarray, values: np.ndarray) -> Evaluator:
        interpolator = RBFInterpolator(coordinates, values, kernel=self.kernel, smoothing=self.smoothing)
        return lambda evaluation_coordinates: np.asarray(interpolator(evaluation_coordinates))
