#!/usr/bin/env python3
"""
Segment a subject using SAM 2 with optional box + foreground / background point prompts.

Foreground points (label 1): include this area in the mask.
Background points (label 0): exclude this area from the mask.

Coordinates are in pixel space (x, y) of the original image, matching SAM2ImagePredictor.

Examples:
  # Box only
  python sam2_segment.py -i photo.png --box 10,20,400,500

  # Custom points (pixels); foreground first, then background
  python sam2_segment.py -i photo.png \\
    --fg 180,220 --fg 200,380 \\
    --bg 520,180 --bg 540,400

  # Points only, no box
  python sam2_segment.py --no-box --fg 200,300 --bg 550,250
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent / "facebook-sam2"
CHECKPOINT = REPO_ROOT / "checkpoints" / "sam2.1_hiera_base_plus.pt"
MODEL_CFG = "configs/sam2.1/sam2.1_hiera_b+.yaml"


def overlay_mask(
    img_rgb: np.ndarray, mask: np.ndarray, color=(30, 255, 120), alpha: float = 0.45
) -> np.ndarray:
    """Blend a binary mask onto RGB image for visualization."""
    out = img_rgb.astype(np.float32) / 255.0
    m = (mask > 0).astype(np.float32)[..., None]
    col = np.array(color, dtype=np.float32) / 255.0
    out = out * (1.0 - alpha * m) + col * (alpha * m)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def parse_xy_pair(spec: str) -> tuple[float, float]:
    """Parse 'x,y' or 'x, y' into floats."""
    parts = spec.replace(" ", "").split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"Expected 'x,y', got: {spec!r}")
    return float(parts[0]), float(parts[1])


def parse_xyxy_box(spec: str) -> np.ndarray:
    """Parse 'x1,y1,x2,y2' into float32 XYXY."""
    parts = spec.replace(" ", "").split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"Expected 'x1,y1,x2,y2', got: {spec!r}")
    return np.array([float(p) for p in parts], dtype=np.float32)


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

    Returns (box_xyxy_or_none, point_coords_or_none, point_labels_or_none).
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


def build_prompts_from_cli(
    fg_specs: list[str] | None,
    bg_specs: list[str] | None,
    box_spec: str | None,
    no_box: bool,
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None] | None:
    """
    Returns None if there are no --fg/--bg (caller may still use --box only).
    Otherwise returns (box_xyxy_or_none, point_coords, point_labels).
    """
    use_custom_points = fg_specs is not None or bg_specs is not None
    if not use_custom_points:
        return None

    fg_list = fg_specs or []
    bg_list = bg_specs or []
    coords: list[list[float]] = []
    labels: list[int] = []
    for s in fg_list:
        x, y = parse_xy_pair(s)
        coords.append([x, y])
        labels.append(1)
    for s in bg_list:
        x, y = parse_xy_pair(s)
        coords.append([x, y])
        labels.append(0)

    if len(coords) == 0:
        raise SystemExit("With --fg/--bg, provide at least one --fg or one --bg.")
    # Only background points: still allowed if box is given
    if not any(labels) and no_box and box_spec is None:
        raise SystemExit(
            "Only background points require a box. Use --box or add at least one --fg, or remove --no-box."
        )

    point_coords = np.array(coords, dtype=np.float32)
    point_labels = np.array(labels, dtype=np.int32)

    if no_box:
        box_xyxy = None
    elif box_spec:
        box_xyxy = parse_xyxy_box(box_spec)
    else:
        raise SystemExit(
            "With --fg/--bg, add --box X1,Y1,X2,Y2 or use --no-box for point-only prompts."
        )

    if not any(labels) and box_xyxy is None:
        raise SystemExit(
            "Only background points require a box. Use --box or add at least one --fg."
        )

    return box_xyxy, point_coords, point_labels


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
    Run SAM 2 on an RGB uint8 image (H, W, 3). Returns (binary mask HxW, iou score, RGB overlay HxWx3).
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

    mask = masks[0].astype(np.uint8)
    overlay = overlay_mask(image_np, mask)
    return mask, float(scores[0]), overlay


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SAM 2 segmentation with optional box, foreground and background points."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        required=True,
        help="Input RGB image path",
    )
    parser.add_argument(
        "--fg",
        dest="fg_points",
        action="append",
        default=None,
        metavar="X,Y",
        help="Foreground point (include); repeatable. Pixel coordinates.",
    )
    parser.add_argument(
        "--bg",
        dest="bg_points",
        action="append",
        default=None,
        metavar="X,Y",
        help="Background point (exclude); repeatable. Pixel coordinates.",
    )
    parser.add_argument(
        "--box",
        type=str,
        default=None,
        metavar="X1,Y1,X2,Y2",
        help="Optional box prompt in XYXY pixel coords (required with --fg/--bg unless --no-box).",
    )
    parser.add_argument(
        "--no-box",
        action="store_true",
        help="Do not pass a box prompt (points only).",
    )
    parser.add_argument(
        "-o",
        "--output-prefix",
        type=Path,
        default=None,
        help="Prefix for outputs (default: stem of input -> stem_person_mask*.png)",
    )
    args = parser.parse_args()

    img_path = args.input.expanduser().resolve()
    if not img_path.is_file():
        print(f"Image not found: {img_path}", file=sys.stderr)
        return 1
    if not CHECKPOINT.is_file():
        print(f"Checkpoint not found: {CHECKPOINT}", file=sys.stderr)
        return 1

    if args.output_prefix is not None:
        stem = args.output_prefix.expanduser().resolve()
        out_path = Path(str(stem) + "_mask_overlay.png")
        mask_path = Path(str(stem) + "_mask.png")
    else:
        stem = img_path.stem
        parent = img_path.parent
        out_path = parent / f"{stem}_person_mask_overlay.png"
        mask_path = parent / f"{stem}_person_mask.png"

    # Absolute paths before os.chdir(REPO_ROOT), which breaks relative save paths.
    out_path = out_path.resolve()
    mask_path = mask_path.resolve()

    pil = Image.open(img_path).convert("RGB")
    w, h = pil.size
    image_np = np.array(pil)

    prompts = build_prompts_from_cli(
        args.fg_points,
        args.bg_points,
        args.box,
        args.no_box,
    )

    if prompts is None:
        if args.box and not args.no_box:
            box_xyxy = parse_xyxy_box(args.box)
            point_coords = None
            point_labels = None
        else:
            print(
                "Provide --fg / --bg and/or --box (use --no-box with points only, no box).",
                file=sys.stderr,
            )
            return 1
    else:
        box_xyxy, point_coords, point_labels = prompts

    os.chdir(REPO_ROOT)

    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = build_sam2(
        MODEL_CFG,
        str(CHECKPOINT),
        device=device,
        apply_postprocessing=False,
    )
    predictor = SAM2ImagePredictor(model)

    with torch.inference_mode():
        if device == "mps":
            autocast_device, autocast_dtype = "mps", torch.bfloat16
        elif device == "cuda":
            autocast_device, autocast_dtype = "cuda", torch.bfloat16
        else:
            autocast_device, autocast_dtype = "cpu", torch.float32

        with torch.autocast(autocast_device, dtype=autocast_dtype, enabled=device != "cpu"):
            predictor.set_image(image_np)
            masks, scores, _ = predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                box=box_xyxy,
                multimask_output=False,
                normalize_coords=True,
            )

    best = masks[0].astype(np.uint8)
    overlay = overlay_mask(image_np, best)

    Image.fromarray(overlay).save(out_path)
    Image.fromarray((best * 255).astype(np.uint8), mode="L").save(mask_path)

    if point_labels is not None:
        n_fg = int(np.sum(point_labels == 1))
        n_bg = int(np.sum(point_labels == 0))
    else:
        n_fg = n_bg = 0
    print(
        f"device={device} points_fg={n_fg} points_bg={n_bg} "
        f"box={'yes' if box_xyxy is not None else 'no'} "
        f"mask_shape={best.shape} score={float(scores[0]):.4f}"
    )
    print(f"wrote {out_path}")
    print(f"wrote {mask_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
