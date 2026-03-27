#!/usr/bin/env python3
"""
SAM 2 image segmentation pipeline: build prompts, run predictor, mask post-process.

Entry points: HTTP (`app.py`) and CLI (`cli.py`).
"""

from __future__ import annotations

import numpy as np
import torch


def overlay_mask(
    img_rgb: np.ndarray, mask: np.ndarray, color=(30, 255, 120), alpha: float = 0.45
) -> np.ndarray:
    """Blend a binary mask onto RGB image for visualization."""
    out = img_rgb.astype(np.float32) / 255.0
    m = (mask > 0).astype(np.float32)[..., None]
    col = np.array(color, dtype=np.float32) / 255.0
    out = out * (1.0 - alpha * m) + col * (alpha * m)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def clip_mask_to_xyxy_box(
    mask: np.ndarray,
    box_xyxy: tuple[float, float, float, float] | np.ndarray,
) -> np.ndarray:
    """
    Binary mask (H, W): force mask==0 for every pixel outside the XYXY rectangle (pixel coords).
    Model output may extend past the box; callers keep only the intersection with the box interior.
    """
    h, w = mask.shape[:2]
    if isinstance(box_xyxy, np.ndarray):
        x1, y1, x2, y2 = (float(t) for t in box_xyxy.ravel())
    else:
        x1, y1, x2, y2 = (float(t) for t in box_xyxy)

    x1i = max(0, min(w, int(np.floor(min(x1, x2)))))
    y1i = max(0, min(h, int(np.floor(min(y1, y2)))))
    x2i = max(0, min(w, int(np.ceil(max(x1, x2)))))
    y2i = max(0, min(h, int(np.ceil(max(y1, y2)))))

    if x2i <= x1i or y2i <= y1i:
        return np.zeros_like(mask)

    out = mask.copy()
    if y1i > 0:
        out[:y1i, :] = 0
    if y2i < h:
        out[y2i:, :] = 0
    if x1i > 0:
        out[:, :x1i] = 0
    if x2i < w:
        out[:, x2i:] = 0
    return out


def finalize_binary_mask_and_overlay(
    raw_mask: np.ndarray,
    image_rgb: np.ndarray,
    box_xyxy: tuple[float, float, float, float] | np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Optional clip to XYXY box, then build RGB overlay. Single entry point for API + CLI.
    """
    mask = raw_mask.astype(np.uint8)
    if box_xyxy is not None:
        mask = clip_mask_to_xyxy_box(mask, box_xyxy)
    return mask, overlay_mask(image_rgb, mask)


def prepare_prompts(
    _image_w: int,
    _image_h: int,
    *,
    foreground_points: list[tuple[float, float]] | None = None,
    background_points: list[tuple[float, float]] | None = None,
    box_xyxy: tuple[float, float, float, float] | None = None,
    no_box: bool = False,
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    """
    Build box / point prompts for SAM2ImagePredictor.predict().

    Returns (box_array_or_none, point_coords_or_none, point_labels_or_none).
    Point arrays may be None for box-only segmentation.
    """
    fg = list(foreground_points or [])
    bg = list(background_points or [])
    has_points = len(fg) > 0 or len(bg) > 0

    if no_box:
        box_arr: np.ndarray | None = None
    elif box_xyxy is not None:
        box_arr = np.array(box_xyxy, dtype=np.float32)
    else:
        box_arr = None

    if not has_points:
        if box_arr is None:
            raise ValueError(
                "Provide a box in box_xyxy and/or foreground and background points."
            )
        return box_arr, None, None

    coords: list[list[float]] = []
    labels: list[int] = []
    for x, y in fg:
        coords.append([float(x), float(y)])
        labels.append(1)
    for x, y in bg:
        coords.append([float(x), float(y)])
        labels.append(0)

    point_coords = np.array(coords, dtype=np.float32)
    point_labels = np.array(labels, dtype=np.int32)

    if not np.any(point_labels == 1) and box_arr is None:
        raise ValueError("Background-only prompts require a box.")

    return box_arr, point_coords, point_labels


def run_segmentation_with_predictor(
    predictor,
    image_np: np.ndarray,
    device: str,
    *,
    foreground_points: list[tuple[float, float]] | None = None,
    background_points: list[tuple[float, float]] | None = None,
    box_xyxy: tuple[float, float, float, float] | None = None,
    no_box: bool = False,
) -> tuple[np.ndarray, float, np.ndarray]:
    """
    Run SAM 2 on an RGB uint8 image (H, W, 3).
    Returns (binary mask HxW, iou score, RGB overlay HxWx3).
    """
    h, w = image_np.shape[:2]
    box_arr, point_coords, point_labels = prepare_prompts(
        w,
        h,
        foreground_points=foreground_points,
        background_points=background_points,
        box_xyxy=box_xyxy,
        no_box=no_box,
    )

    if device == "mps":
        autocast_device, autocast_dtype = "mps", torch.bfloat16
    elif device == "cuda":
        autocast_device, autocast_dtype = "cuda", torch.bfloat16
    else:
        autocast_device, autocast_dtype = "cpu", torch.float32

    with torch.inference_mode(), torch.autocast(
        autocast_device, dtype=autocast_dtype, enabled=device != "cpu"
    ):
        predictor.set_image(image_np)
        masks, scores, _ = predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            box=box_arr,
            multimask_output=False,
            normalize_coords=True,
        )

    mask, overlay = finalize_binary_mask_and_overlay(masks[0], image_np, box_xyxy)
    return mask, float(scores[0]), overlay
