#!/usr/bin/env python3
"""
FastAPI service for SAM 2 image segmentation (box + foreground / background points).
"""

from __future__ import annotations

import base64
import io
import json
import os
from contextlib import asynccontextmanager
from typing import Any

import cv2
import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from sam2_config import CHECKPOINT, MODEL_CFG, REPO_ROOT, default_segment_device
from sam2_segment import run_segmentation_with_predictor

_predictor = None
_device: str | None = None


def load_model() -> None:
    """Load SAM 2 once into process-global predictor (call from lifespan)."""
    global _predictor, _device
    if _predictor is not None:
        return
    if not CHECKPOINT.is_file():
        raise FileNotFoundError(f"Checkpoint not found: {CHECKPOINT}")

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
    _predictor = SAM2ImagePredictor(model)
    _device = device


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(
    title="SAM 2 Segment API",
    description="Upload an image with optional prompts (JSON) for instance segmentation.",
    lifespan=lifespan,
)

# Allow local Vite dev server and typical LAN origins if you open the UI by IP.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _np_rgb(upload: UploadFile) -> np.ndarray:
    raw = upload.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty image upload")
    pil = Image.open(io.BytesIO(raw))
    return np.array(pil.convert("RGB"))


def _encode_png_b64(arr: np.ndarray, mode: str) -> str:
    buf = io.BytesIO()
    Image.fromarray(arr, mode=mode).save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _inpaint_remove_foreground(rgb: np.ndarray, mask_fg: np.ndarray) -> np.ndarray:
    """
    Remove the segmented foreground (mask == 1) and fill holes with OpenCV inpaint
    so the area is patched from nearby background colors (not flat black).
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected RGB image HxWx3")
    if mask_fg.shape[:2] != rgb.shape[:2]:
        raise ValueError("Mask shape must match image")
    if mask_fg.max() == 0:
        return rgb.copy()
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    inpaint_mask = (mask_fg > 0).astype(np.uint8) * 255
    # Radius scales mildly with resolution; clamp for stability.
    r = max(3, int(min(rgb.shape[0], rgb.shape[1]) * 0.012))
    r = min(r, 16)
    out_bgr = cv2.inpaint(bgr, inpaint_mask, r, cv2.INPAINT_NS)
    return cv2.cvtColor(out_bgr, cv2.COLOR_BGR2RGB)


def _parse_prompts_json(raw: str) -> dict[str, Any]:
    if not raw or raw.strip() == "":
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid prompts JSON: {e}") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="prompts_json must be a JSON object")
    return data


@app.get("/health")
def health():
    return {"status": "ok", "device": _device, "checkpoint": str(CHECKPOINT)}


@app.post("/segment")
async def segment(
    image: UploadFile = File(..., description="Input image (JPEG/PNG, RGB)"),
    prompts_json: str = Form(
        default="{}",
        description='JSON, e.g. {"foreground_points":[[x,y]], "background_points":[[x,y]], '
        '"box_xyxy":[x1,y1,x2,y2], "no_box": false}',
    ),
):
    """
    Run segmentation. Points and box are in pixel coordinates: x horizontal, y vertical, origin top-left.

    At least one of foreground_points, background_points, or box_xyxy must be provided.

    If box_xyxy is included in the JSON, the returned pixel mask is cropped to the box: pixels outside
    the box are forced to background (SAM may still predict leakage outside the rectangle).
    """
    data = _parse_prompts_json(prompts_json)
    if data.get("use_default_prompts"):
        raise HTTPException(
            status_code=400,
            detail="use_default_prompts is not supported; send explicit points and/or box_xyxy.",
        )

    fg: list[tuple[float, float]] = []
    bg: list[tuple[float, float]] = []
    fg_raw = data.get("foreground_points")
    bg_raw = data.get("background_points")
    if fg_raw is not None:
        if not isinstance(fg_raw, list):
            raise HTTPException(400, "foreground_points must be a list of [x,y]")
        fg = [(float(p[0]), float(p[1])) for p in fg_raw]
    if bg_raw is not None:
        if not isinstance(bg_raw, list):
            raise HTTPException(400, "background_points must be a list of [x,y]")
        bg = [(float(p[0]), float(p[1])) for p in bg_raw]

    box_t: tuple[float, float, float, float] | None = None
    bx = data.get("box_xyxy")
    if bx is not None:
        if not isinstance(bx, (list, tuple)) or len(bx) != 4:
            raise HTTPException(400, "box_xyxy must be [x1,y1,x2,y2]")
        box_t = (float(bx[0]), float(bx[1]), float(bx[2]), float(bx[3]))
    no_box = bool(data.get("no_box", False))

    if len(fg) == 0 and len(bg) == 0 and box_t is None:
        raise HTTPException(
            status_code=400,
            detail="Provide foreground_points, background_points, and/or box_xyxy.",
        )

    image_np = _np_rgb(image)
    assert _predictor is not None and _device is not None

    try:
        mask, score, overlay = run_segmentation_with_predictor(
            _predictor,
            image_np,
            _device,
            foreground_points=fg,
            background_points=bg,
            box_xyxy=box_t,
            no_box=no_box,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    h, w = mask.shape[:2]
    try:
        cutout_rgb = _inpaint_remove_foreground(image_np, mask)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Inpaint cutout failed: {e}",
        ) from e

    return {
        "width": w,
        "height": h,
        "score": score,
        "mask_png_base64": _encode_png_b64((mask * 255).astype(np.uint8), "L"),
        "overlay_png_base64": _encode_png_b64(overlay, "RGB"),
        "inpaint_cutout_png_base64": _encode_png_b64(cutout_rgb, "RGB"),
    }


def main():
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
