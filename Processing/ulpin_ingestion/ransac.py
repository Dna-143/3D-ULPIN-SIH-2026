"""Deterministic 2D similarity-transform RANSAC for survey controls."""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from Processing.ulpin_ingestion.errors import IngestionError


@dataclass(frozen=True)
class SimilarityTransform:
    a: float
    b: float
    translate_x: float
    translate_y: float

    @property
    def scale(self) -> float:
        return math.hypot(self.a, self.b)

    @property
    def rotation_degrees(self) -> float:
        return math.degrees(math.atan2(self.b, self.a))

    def apply(self, points: np.ndarray) -> np.ndarray:
        x = points[:, 0]
        y = points[:, 1]
        return np.column_stack(
            (
                self.a * x - self.b * y + self.translate_x,
                self.b * x + self.a * y + self.translate_y,
            )
        )

    def apply_one(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.a * x - self.b * y + self.translate_x,
            self.b * x + self.a * y + self.translate_y,
        )


@dataclass(frozen=True)
class RansacResult:
    model: SimilarityTransform
    inlier_mask: np.ndarray
    residuals_m: np.ndarray
    trials: int


def fit_similarity(source: np.ndarray, target: np.ndarray) -> SimilarityTransform:
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 2:
        raise ValueError("source and target must be matching Nx2 arrays")
    if len(source) < 2:
        raise ValueError("at least two point pairs are required")

    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    denominator = float(np.sum(source_centered[:, 0] ** 2 + source_centered[:, 1] ** 2))
    if denominator <= 1e-12:
        raise ValueError("control points are geometrically degenerate")

    a = float(
        np.sum(
            source_centered[:, 0] * target_centered[:, 0]
            + source_centered[:, 1] * target_centered[:, 1]
        )
        / denominator
    )
    b = float(
        np.sum(
            source_centered[:, 0] * target_centered[:, 1]
            - source_centered[:, 1] * target_centered[:, 0]
        )
        / denominator
    )
    translate_x = float(target_mean[0] - a * source_mean[0] + b * source_mean[1])
    translate_y = float(target_mean[1] - b * source_mean[0] - a * source_mean[1])
    return SimilarityTransform(a, b, translate_x, translate_y)


def _candidate_pairs(count: int, max_trials: int, seed: int) -> Iterable[tuple[int, int]]:
    pair_count = count * (count - 1) // 2
    if pair_count <= max_trials:
        return itertools.combinations(range(count), 2)

    rng = np.random.default_rng(seed)
    pairs: set[tuple[int, int]] = set()
    while len(pairs) < max_trials:
        first, second = sorted(rng.choice(count, size=2, replace=False).tolist())
        pairs.add((first, second))
    return sorted(pairs)


def run_ransac(
    source: np.ndarray,
    target: np.ndarray,
    *,
    residual_threshold_m: float,
    max_trials: int,
    min_inlier_ratio: float,
    random_seed: int,
) -> RansacResult:
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 2:
        raise IngestionError(
            "INVALID_CONTROL_POINTS", "control points must form matching Nx2 arrays"
        )
    count = len(source)
    if count < 4:
        raise IngestionError(
            "INSUFFICIENT_CONTROL_POINTS",
            "RANSAC requires at least four control-point pairs",
            details={"received": count},
        )

    minimum_inliers = max(3, math.ceil(count * min_inlier_ratio))
    best: tuple[tuple[float, float, float], SimilarityTransform, np.ndarray, np.ndarray] | None = (
        None
    )
    trials = 0

    for pair in _candidate_pairs(count, max_trials, random_seed):
        trials += 1
        try:
            model = fit_similarity(source[list(pair)], target[list(pair)])
        except ValueError:
            continue
        if not 0.5 <= model.scale <= 2.0:
            continue

        residuals = np.linalg.norm(model.apply(source) - target, axis=1)
        inlier_mask = residuals <= residual_threshold_m
        if int(inlier_mask.sum()) < 2:
            continue

        for _ in range(3):
            try:
                refined = fit_similarity(source[inlier_mask], target[inlier_mask])
            except ValueError:
                break
            refined_residuals = np.linalg.norm(refined.apply(source) - target, axis=1)
            refined_mask = refined_residuals <= residual_threshold_m
            model, residuals = refined, refined_residuals
            if np.array_equal(refined_mask, inlier_mask):
                break
            inlier_mask = refined_mask

        inlier_count = int(inlier_mask.sum())
        if inlier_count < 2:
            continue
        mean_inlier = float(residuals[inlier_mask].mean())
        clipped_median = float(np.median(np.minimum(residuals, residual_threshold_m * 10.0)))
        score = (float(inlier_count), -mean_inlier, -clipped_median)
        if best is None or score > best[0]:
            best = (score, model, inlier_mask, residuals)

    if best is None or int(best[2].sum()) < minimum_inliers:
        raise IngestionError(
            "UNSTABLE_CONTROL_NETWORK",
            "RANSAC could not find a trustworthy control-point consensus",
            details={
                "required_inliers": minimum_inliers,
                "point_count": count,
                "threshold_m": residual_threshold_m,
            },
        )

    final_model = fit_similarity(source[best[2]], target[best[2]])
    final_residuals = np.linalg.norm(final_model.apply(source) - target, axis=1)
    final_mask = final_residuals <= residual_threshold_m
    if int(final_mask.sum()) < minimum_inliers:
        raise IngestionError(
            "UNSTABLE_CONTROL_NETWORK",
            "refined control-point model fell below the required consensus",
            details={"required_inliers": minimum_inliers},
        )
    return RansacResult(final_model, final_mask, final_residuals, trials)
