#!/usr/bin/env python3
"""
CLI entry: segment an image with SAM 2 (box and/or foreground / background points).

Examples:
  python cli.py -i photo.png --box 10,20,400,500
  python cli.py -i photo.png --fg 180,220 --fg 200,380 --bg 520,180 --box 10,10,800,600
  python cli.py -i photo.png --no-box --fg 200,300 --bg 550,250
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from sam2_config import CHECKPOINT, MODEL_CFG, REPO_ROOT, default_segment_device
from sam2_segment import run_segmentation_with_predictor


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


def _box_to_tuple(
    box: np.ndarray | tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    if isinstance(box, np.ndarray):
        t = tuple(float(x) for x in box.ravel())
        return t if len(t) == 4 else None
    return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))


def _points_from_sam_labels(
    point_coords: np.ndarray,
    point_labels: np.ndarray,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    fg: list[tuple[float, float]] = []
    bg: list[tuple[float, float]] = []
    for i in range(len(point_labels)):
        c = point_coords[i]
        if point_labels[i] == 1:
            fg.append((float(c[0]), float(c[1])))
        else:
            bg.append((float(c[0]), float(c[1])))
    return fg, bg


def build_prompts_from_cli(
    fg_specs: list[str] | None,
    bg_specs: list[str] | None,
    box_spec: str | None,
    no_box: bool,
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None] | None:
    """
    None = no point args (box-only path may still be used).
    Else (box_xyxy ndarray or None, point_coords, point_labels).
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
        raise SystemExit("Only background points require a box. Use --box or add at least one --fg.")

    return box_xyxy, point_coords, point_labels


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

    out_path = out_path.resolve()
    mask_path = mask_path.resolve()

    image_np = np.array(Image.open(img_path).convert("RGB"))

    prompts = build_prompts_from_cli(
        args.fg_points,
        args.bg_points,
        args.box,
        args.no_box,
    )

    if prompts is None:
        if args.box and not args.no_box:
            box_t = _box_to_tuple(parse_xyxy_box(args.box))
            fg: list[tuple[float, float]] = []
            bg: list[tuple[float, float]] = []
            no_box_flag = False
        else:
            print(
                "Provide --fg / --bg and/or --box (use --no-box with points only, no box).",
                file=sys.stderr,
            )
            return 1
    else:
        raw_box, point_coords, point_labels = prompts
        box_t = _box_to_tuple(raw_box)
        fg, bg = _points_from_sam_labels(point_coords, point_labels)
        no_box_flag = args.no_box

    os.chdir(REPO_ROOT)
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    device = default_segment_device()
    model = build_sam2(
        MODEL_CFG,
        str(CHECKPOINT),
        device=device,
        apply_postprocessing=False,
    )
    predictor = SAM2ImagePredictor(model)

    best, score, overlay = run_segmentation_with_predictor(
        predictor,
        image_np,
        device,
        foreground_points=fg,
        background_points=bg,
        box_xyxy=box_t,
        no_box=no_box_flag,
    )

    Image.fromarray(overlay).save(out_path)
    Image.fromarray((best * 255).astype(np.uint8), mode="L").save(mask_path)

    n_fg, n_bg = len(fg), len(bg)
    print(
        f"device={device} points_fg={n_fg} points_bg={n_bg} "
        f"box={'yes' if box_t is not None else 'no'} "
        f"mask_shape={best.shape} score={score:.4f}"
    )
    print(f"wrote {out_path}")
    print(f"wrote {mask_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
