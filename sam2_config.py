#!/usr/bin/env python3
"""Paths and runtime helpers shared by app, CLI, and tools."""

from __future__ import annotations

from pathlib import Path

# SAM 2 repo (submodule) and checkpoint — Hydra resolves configs relative to REPO_ROOT.
REPO_ROOT = Path(__file__).resolve().parent / "facebook-sam2"
CHECKPOINT = REPO_ROOT / "checkpoints" / "sam2.1_hiera_base_plus.pt"
MODEL_CFG = "configs/sam2.1/sam2.1_hiera_b+.yaml"


def default_segment_device() -> str:
    """Prefer CUDA, then Apple MPS, else CPU (same policy as the HTTP service)."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"
