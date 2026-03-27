#!/usr/bin/env python3
"""Smoke test: build SAM 2.1 image predictor on MPS or CPU (fast startup)."""

import os
import sys

import torch

from sam2_config import CHECKPOINT, MODEL_CFG, REPO_ROOT


def main() -> int:
    if not CHECKPOINT.is_file():
        print(f"Missing checkpoint: {CHECKPOINT}", file=sys.stderr)
        return 1

    os.chdir(REPO_ROOT)
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    # No CUDA extension on Mac; skip optional mask post-processing that uses it.
    model = build_sam2(
        MODEL_CFG,
        str(CHECKPOINT),
        device=device,
        apply_postprocessing=False,
    )
    SAM2ImagePredictor(model)
    print(f"OK: SAM2ImagePredictor ready on {device} (torch {torch.__version__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
