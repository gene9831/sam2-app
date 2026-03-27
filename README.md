# sam2-env

Local toolkit and web UI around [SAM 2](https://github.com/facebookresearch/sam2): a FastAPI service for image segmentation (box + foreground/background points) and a Vue frontend with overlay, mask, and inpaint cutout views.

## Repository layout

| Path              | Purpose                                                                                                    |
| ----------------- | ---------------------------------------------------------------------------------------------------------- |
| `facebook-sam2/`  | Git submodule → [facebookresearch/sam2](https://github.com/facebookresearch/sam2) (model code and config). |
| `app.py`          | FastAPI app: loads the model once, exposes `/health` and `/segment`.                                       |
| `sam2_segment.py` | Segmentation helpers and CLI (`REPO_ROOT` points at `facebook-sam2`).                                      |
| `web/`            | Vite + Vue frontend; dev server proxies `/api` to the backend.                                             |

## Prerequisites

- **Python** 3.10+ (SAM 2 upstream recommends 3.10+; PyTorch must match your platform).
- **PyTorch** and **torchvision** — install from [pytorch.org](https://pytorch.org/get-started/locally/) for your CUDA / CPU / MPS setup.
- **Node.js** 20+ and **pnpm** (for the frontend).
- **Git** with submodule support.

## Clone and submodule

```bash
git clone --recurse-submodules <your-repo-url> sam2-env
cd sam2-env
```

If you already cloned without submodules:

```bash
git submodule update --init --recursive
```

## Install Python dependencies

Create and activate a virtual environment, install PyTorch (see link above), then:

```bash
cd facebook-sam2
pip install -e .
cd ..
pip install -r requirements-api.txt
```

`requirements-api.txt` covers FastAPI, Uvicorn, multipart uploads, and OpenCV (headless) for inpaint cutout encoding—not the full SAM 2 stack; the editable install from `facebook-sam2` pulls the rest (e.g. `numpy`, `PIL`) as defined upstream.

## Model checkpoint

The API expects this file (see `sam2_segment.py`):

`facebook-sam2/checkpoints/sam2.1_hiera_base_plus.pt`

Download it from Meta’s CDN (SAM 2.1 checkpoints, same path as upstream README):

```bash
cd facebook-sam2/checkpoints
./download_ckpts.sh
# or fetch only base_plus:
curl -L -O https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt
cd ../..
```

Weights are large (~300MB+); they are not committed in this repo or in the submodule by default.

## Run the backend

From the **repository root** (where `app.py` lives), with the virtual environment activated:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Or:

```bash
python app.py
```

On startup the app selects **CUDA**, **MPS** (Apple Silicon), or **CPU** in that order. First request loads the checkpoint into memory.

- **Health:** `GET http://127.0.0.1:8000/health`
- **Segment:** `POST http://127.0.0.1:8000/segment` (multipart: image file + JSON `prompts` for points/box; see `app.py` for fields).

## Run the frontend

```bash
cd web
pnpm install
pnpm dev
```

The Vite dev server maps `/api/*` to `http://127.0.0.1:8000/*`, so keep the API running on port **8000** while developing.

## CLI segmentation

For quick tests without the HTTP API:

```bash
python sam2_segment.py -i path/to/image.png --fg 200,300 --bg 500,400
```

Use `python sam2_segment.py --help` for box/CJK and `--no-box` options.

## License

Respect the licenses of [facebookresearch/sam2](https://github.com/facebookresearch/sam2) and of any checkpoints you download. This wrapper repo’s own code is provided as-is for local experimentation.
