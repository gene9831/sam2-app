<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useEventListener } from '@vueuse/core'
import {
  fetchHealth,
  segmentImage,
  base64PngToDataUrl,
  type HealthResponse,
} from './api/segment'
import IconDownload from './components/icons/IconDownload.vue'

/** Image-space distance: below = click (place point); above = drag (box). */
const DRAG_THRESHOLD_PX = 8

/** Batch rapid prompt changes before calling /segment (ms). */
const SEGMENT_DEBOUNCE_MS = 500

const imageUrl = ref<string | null>(null)
const imageFile = ref<File | null>(null)
const imgRef = ref<HTMLImageElement | null>(null)

const fgPoints = ref<{ x: number; y: number }[]>([])
const bgPoints = ref<{ x: number; y: number }[]>([])
const boxRect = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)

const noBox = ref(false)

const stageWrapRef = ref<HTMLElement | null>(null)
const overlayStageRef = ref<HTMLElement | null>(null)
const overlayImgRef = ref<HTMLImageElement | null>(null)
/** Primary (0) or secondary/right (2) button stroke on the canvas. */
const brushActive = ref(false)
const brushButton = ref<number | null>(null)
const brushStart = ref<{ x: number; y: number } | null>(null)
const brushCurrent = ref<{ x: number; y: number } | null>(null)

useEventListener(stageWrapRef, 'contextmenu', (e) => e.preventDefault())
useEventListener(overlayStageRef, 'contextmenu', (e) => e.preventDefault())

const health = ref<HealthResponse | null>(null)
const healthError = ref<string | null>(null)

const isLoading = ref(false)
const lastError = ref<string | null>(null)
const lastScore = ref<number | null>(null)
const lastMs = ref<number | null>(null)
const lastAt = ref<string | null>(null)
const overlayUrl = ref<string | null>(null)
const maskUrl = ref<string | null>(null)
const cutoutUrl = ref<string | null>(null)
/** Foreground-only RGBA (client-side from source image + mask). */
const extractUrl = ref<string | null>(null)
/** Which output is shown in the Segmentation panel (all three come from one /segment call). */
const segViewMode = ref<'overlay' | 'mask' | 'inpaint' | 'extract'>('overlay')

/** Pending debounced /segment call (VueUse useDebounceFn has no cancel in v14). */
let segmentDebounceId: ReturnType<typeof setTimeout> | null = null

const fileInputRef = ref<HTMLInputElement | null>(null)

function cancelScheduledSegment() {
  if (segmentDebounceId !== null) {
    clearTimeout(segmentDebounceId)
    segmentDebounceId = null
  }
}

function triggerFilePick() {
  fileInputRef.value?.click()
}

/** Map screen position to image pixel coords using a displayed &lt;img&gt; (natural pixels). */
function getPixelFromImgEl(
  el: HTMLImageElement | null,
  clientX: number,
  clientY: number,
): { x: number; y: number } | null {
  if (!el?.naturalWidth) return null
  const rect = el.getBoundingClientRect()
  const u = (clientX - rect.left) / rect.width
  const v = (clientY - rect.top) / rect.height
  if (u < 0 || u > 1 || v < 0 || v > 1) return null
  return {
    x: Math.round(u * el.naturalWidth),
    y: Math.round(v * el.naturalHeight),
  }
}

function clientToImage(clientX: number, clientY: number): { x: number; y: number } | null {
  return getPixelFromImgEl(imgRef.value, clientX, clientY)
}

function dotStyle(p: { x: number; y: number }) {
  const el = imgRef.value
  if (!el?.naturalWidth) return {}
  return {
    left: `${(p.x / el.naturalWidth) * 100}%`,
    top: `${(p.y / el.naturalHeight) * 100}%`,
  }
}

const draftBox = computed(() => {
  if (!brushActive.value || !brushStart.value || !brushCurrent.value) return null
  const a = brushStart.value
  const b = brushCurrent.value
  return {
    x1: Math.min(a.x, b.x),
    y1: Math.min(a.y, b.y),
    x2: Math.max(a.x, b.x),
    y2: Math.max(a.y, b.y),
  }
})

function boxDivStyle(r: { x1: number; y1: number; x2: number; y2: number }) {
  const el = imgRef.value
  if (!el?.naturalWidth) return {}
  const nw = el.naturalWidth
  const nh = el.naturalHeight
  const x1 = Math.min(r.x1, r.x2)
  const y1 = Math.min(r.y1, r.y2)
  const x2 = Math.max(r.x1, r.x2)
  const y2 = Math.max(r.y1, r.y2)
  return {
    left: `${(x1 / nw) * 100}%`,
    top: `${(y1 / nh) * 100}%`,
    width: `${((x2 - x1) / nw) * 100}%`,
    height: `${((y2 - y1) / nh) * 100}%`,
  }
}

function sameImagePoint(a: { x: number; y: number }, b: { x: number; y: number }) {
  return a.x === b.x && a.y === b.y
}

/** Click same-type point at the same pixel again to remove it (toggle). */
function toggleFgPoint(p: { x: number; y: number }) {
  const i = fgPoints.value.findIndex((q) => sameImagePoint(q, p))
  if (i >= 0) fgPoints.value = fgPoints.value.filter((_, j) => j !== i)
  else fgPoints.value = [...fgPoints.value, { ...p }]
}

function toggleBgPoint(p: { x: number; y: number }) {
  const i = bgPoints.value.findIndex((q) => sameImagePoint(q, p))
  if (i >= 0) bgPoints.value = bgPoints.value.filter((_, j) => j !== i)
  else bgPoints.value = [...bgPoints.value, { ...p }]
}

function resetBrush(e: PointerEvent) {
  brushActive.value = false
  brushButton.value = null
  brushStart.value = null
  brushCurrent.value = null
  try {
    ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {
    /* ignore */
  }
}

function onPointerDown(e: PointerEvent) {
  if (!imageFile.value) return
  if (e.button !== 0 && e.button !== 2) return
  if (e.button === 2) e.preventDefault()

  const p = clientToImage(e.clientX, e.clientY)
  if (!p) return

  brushActive.value = true
  brushButton.value = e.button
  brushStart.value = p
  brushCurrent.value = p
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!brushActive.value) return
  const p = clientToImage(e.clientX, e.clientY)
  if (p) brushCurrent.value = p
}

function onPointerCancel(e: PointerEvent) {
  if (brushActive.value) resetBrush(e)
}

function finishBrushStroke(e: PointerEvent, coordEl: HTMLImageElement | null) {
  if (!brushActive.value || brushButton.value === null) {
    if (brushActive.value) resetBrush(e)
    return
  }

  const start = brushStart.value
  const end =
    getPixelFromImgEl(coordEl, e.clientX, e.clientY) ?? brushCurrent.value ?? start

  if (start && end) {
    const dist = Math.hypot(end.x - start.x, end.y - start.y)
    if (dist >= DRAG_THRESHOLD_PX) {
      const x1 = Math.min(start.x, end.x)
      const y1 = Math.min(start.y, end.y)
      const x2 = Math.max(start.x, end.x)
      const y2 = Math.max(start.y, end.y)
      if (x2 - x1 > 3 && y2 - y1 > 3) {
        boxRect.value = { x1, y1, x2, y2 }
        scheduleSegment()
      } else if (brushButton.value === 0) {
        toggleFgPoint(start)
        scheduleSegment()
      } else if (brushButton.value === 2) {
        toggleBgPoint(start)
        scheduleSegment()
      }
    } else {
      if (brushButton.value === 0) {
        toggleFgPoint(start)
        scheduleSegment()
      } else if (brushButton.value === 2) {
        toggleBgPoint(start)
        scheduleSegment()
      }
    }
  }

  resetBrush(e)
}

function onPointerUp(e: PointerEvent) {
  finishBrushStroke(e, imgRef.value)
}

function onOverlayPointerDown(e: PointerEvent) {
  if (!imageFile.value || !segmentationDisplayUrl.value) return
  if (e.button !== 0 && e.button !== 2) return
  if (e.button === 2) e.preventDefault()

  const p = getPixelFromImgEl(overlayImgRef.value, e.clientX, e.clientY)
  if (!p) return

  brushActive.value = true
  brushButton.value = e.button
  brushStart.value = p
  brushCurrent.value = p
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onOverlayPointerMove(e: PointerEvent) {
  if (!brushActive.value) return
  const p = getPixelFromImgEl(overlayImgRef.value, e.clientX, e.clientY)
  if (p) brushCurrent.value = p
}

function onOverlayPointerCancel(e: PointerEvent) {
  if (brushActive.value) resetBrush(e)
}

function onOverlayPointerUp(e: PointerEvent) {
  finishBrushStroke(e, overlayImgRef.value)
}

function removeFg(i: number) {
  fgPoints.value = fgPoints.value.filter((_, j) => j !== i)
  scheduleSegment()
}

function removeBg(i: number) {
  bgPoints.value = bgPoints.value.filter((_, j) => j !== i)
  scheduleSegment()
}

/** Build PNG data URL: original RGB, alpha from grayscale mask (segmented foreground only). */
async function buildForegroundExtractDataUrl(imageSrc: string, maskSrc: string): Promise<string | null> {
  const img = new Image()
  const msk = new Image()
  img.decoding = 'async'
  msk.decoding = 'async'
  try {
    await Promise.all([
      new Promise<void>((resolve, reject) => {
        img.onload = () => resolve()
        img.onerror = () => reject(new Error('image load failed'))
        img.src = imageSrc
      }),
      new Promise<void>((resolve, reject) => {
        msk.onload = () => resolve()
        msk.onerror = () => reject(new Error('mask load failed'))
        msk.src = maskSrc
      }),
    ])
  } catch {
    return null
  }

  const w = img.naturalWidth
  const h = img.naturalHeight
  if (!w || !h || msk.naturalWidth !== w || msk.naturalHeight !== h) return null

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return null

  ctx.drawImage(img, 0, 0)
  const rgb = ctx.getImageData(0, 0, w, h)

  const mCanvas = document.createElement('canvas')
  mCanvas.width = w
  mCanvas.height = h
  const mctx = mCanvas.getContext('2d')
  if (!mctx) return null
  mctx.drawImage(msk, 0, 0)
  const maskPixels = mctx.getImageData(0, 0, w, h)

  const out = rgb.data
  const m = maskPixels.data
  for (let i = 0; i < out.length; i += 4) {
    out[i + 3] = m[i]
  }
  ctx.putImageData(rgb, 0, 0)
  return canvas.toDataURL('image/png')
}

function clearPrompts() {
  fgPoints.value = []
  bgPoints.value = []
  boxRect.value = null
  overlayUrl.value = null
  maskUrl.value = null
  cutoutUrl.value = null
  extractUrl.value = null
  lastScore.value = null
  lastMs.value = null
  lastError.value = null
  lastAt.value = null
}

function clearBox() {
  boxRect.value = null
  scheduleSegment()
}

function buildPrompts(): Record<string, unknown> {
  const o: Record<string, unknown> = {
    foreground_points: fgPoints.value.map((p) => [p.x, p.y]),
    background_points: bgPoints.value.map((p) => [p.x, p.y]),
    no_box: noBox.value,
  }
  if (boxRect.value) {
    o.box_xyxy = [boxRect.value.x1, boxRect.value.y1, boxRect.value.x2, boxRect.value.y2]
  }
  return o
}

const canSegment = computed(() => {
  if (!imageFile.value) return false
  if (fgPoints.value.length + bgPoints.value.length > 0) return true
  if (boxRect.value) return true
  return false
})

const hasSegmentationResult = computed(
  () => !!overlayUrl.value && !!maskUrl.value && !!cutoutUrl.value,
)

const segmentationDisplayUrl = computed(() => {
  if (!hasSegmentationResult.value) return null
  if (segViewMode.value === 'mask') return maskUrl.value
  if (segViewMode.value === 'inpaint') return cutoutUrl.value
  if (segViewMode.value === 'extract') return extractUrl.value
  return overlayUrl.value
})

/** Save the currently selected segmentation view (overlay / mask / inpaint) as PNG. */
function downloadCurrentSegmentationView() {
  const url = segmentationDisplayUrl.value
  if (!url || !imageFile.value || !hasSegmentationResult.value) return
  const kind =
    segViewMode.value === 'mask'
      ? 'mask'
      : segViewMode.value === 'inpaint'
        ? 'inpaint'
        : segViewMode.value === 'extract'
          ? 'extract'
          : 'overlay'
  const stem = imageFile.value.name.replace(/\.[^.]+$/i, '') || 'image'
  const filename = `${stem}_sam2_${kind}.png`
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

async function runSegment() {
  if (!imageFile.value || !canSegment.value) return
  cancelScheduledSegment()
  isLoading.value = true
  lastError.value = null
  const t0 = performance.now()
  try {
    const res = await segmentImage(imageFile.value, buildPrompts())
    lastScore.value = res.score
    lastMs.value = Math.round(performance.now() - t0)
    lastAt.value = new Date().toLocaleTimeString()
    overlayUrl.value = base64PngToDataUrl(res.overlay_png_base64)
    maskUrl.value = base64PngToDataUrl(res.mask_png_base64)
    cutoutUrl.value = base64PngToDataUrl(res.inpaint_cutout_png_base64)
    // Keep previous extractUrl until the new one is ready — clearing early triggers a watch that forces overlay.
    if (imageUrl.value) {
      extractUrl.value = await buildForegroundExtractDataUrl(imageUrl.value, maskUrl.value)
    } else {
      extractUrl.value = null
    }
  } catch (e) {
    lastError.value = e instanceof Error ? e.message : String(e)
    overlayUrl.value = null
    maskUrl.value = null
    cutoutUrl.value = null
    extractUrl.value = null
  } finally {
    isLoading.value = false
  }
}

function scheduleSegment() {
  cancelScheduledSegment()
  if (!canSegment.value) {
    // No prompts: drop stale overlay so the panel resets instead of keeping the last run.
    overlayUrl.value = null
    maskUrl.value = null
    cutoutUrl.value = null
    extractUrl.value = null
    lastScore.value = null
    lastMs.value = null
    lastError.value = null
    lastAt.value = null
    isLoading.value = false
    return
  }
  if (!imageFile.value) return
  segmentDebounceId = setTimeout(() => {
    segmentDebounceId = null
    void runSegment()
  }, SEGMENT_DEBOUNCE_MS)
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  imageFile.value = f
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = URL.createObjectURL(f)
  fgPoints.value = []
  bgPoints.value = []
  boxRect.value = null
  overlayUrl.value = null
  maskUrl.value = null
  cutoutUrl.value = null
  extractUrl.value = null
  lastScore.value = null
  lastMs.value = null
  lastError.value = null
  lastAt.value = null
  input.value = ''
}

function clearImage() {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = null
  imageFile.value = null
  fgPoints.value = []
  bgPoints.value = []
  boxRect.value = null
  overlayUrl.value = null
  maskUrl.value = null
  cutoutUrl.value = null
  extractUrl.value = null
  lastScore.value = null
  lastMs.value = null
  lastError.value = null
  lastAt.value = null
  cancelScheduledSegment()
  if (fileInputRef.value) fileInputRef.value.value = ''
}

watch(
  () => [...fgPoints.value, ...bgPoints.value],
  () => {
    if (imageFile.value) scheduleSegment()
  },
)

watch(boxRect, () => {
  if (imageFile.value) scheduleSegment()
})

watch(noBox, () => {
  if (imageFile.value) scheduleSegment()
})

watch([hasSegmentationResult, segmentationDisplayUrl, extractUrl], () => {
  if (!hasSegmentationResult.value && segViewMode.value !== 'overlay') {
    segViewMode.value = 'overlay'
  }
  if (
    hasSegmentationResult.value &&
    segViewMode.value === 'extract' &&
    !extractUrl.value &&
    !isLoading.value
  ) {
    segViewMode.value = 'overlay'
  }
})

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch (e) {
    healthError.value = e instanceof Error ? e.message : String(e)
  }
})

onUnmounted(() => {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  cancelScheduledSegment()
})
</script>

<template>
  <div class="app-layout">
    <header class="page-header">
      <h1>SAM 2 segmentation</h1>
      <p class="sub">
        Upload an image, then annotate on the canvas. Results refresh after a short debounce.
      </p>
    </header>

    <div v-if="health" class="panel status-panel">
      <p class="status-line">
        Backend device: <code>{{ health.device ?? 'unknown' }}</code>
        · Status: <code>{{ health.status }}</code>
      </p>
    </div>
    <p v-else-if="healthError" class="err err-inline">
      Health check failed: {{ healthError }} — is the API running on port 8000?
    </p>

    <input
      id="image-file"
      ref="fileInputRef"
      type="file"
      accept="image/*"
      class="sr-only"
      @change="onFileChange"
    />

    <!-- Before image: only hero upload (no empty twin columns) -->
    <div v-if="!imageFile" class="landing">
      <div
        class="upload upload-hero"
        role="button"
        tabindex="0"
        @click="triggerFilePick"
        @keydown.enter.prevent="triggerFilePick"
        @keydown.space.prevent="triggerFilePick"
      >
        Click or tap to choose an image (JPEG / PNG)
      </div>
      <p class="landing-hint">Then annotate on the canvas — the large drop zone hides once an image is loaded.</p>
    </div>

    <!-- After image: compact file row + tools + split view (replaces landing) -->
    <div v-else class="workspace">
      <div class="replace-bar">
        <button type="button" class="btn" @click="triggerFilePick">Replace image</button>
        <span class="file-name" :title="imageFile.name">{{ imageFile.name }}</span>
        <span v-if="imgRef && imgRef.naturalWidth" class="file-meta">
          {{ imgRef.naturalWidth }}×{{ imgRef.naturalHeight }} px
        </span>
        <button type="button" class="btn btn-text" @click="clearImage">Remove</button>
      </div>

      <p class="hint-banner hint-banner--compact">
        <strong>Source / Segmentation images:</strong> left → FG, right → BG, longer drag → box (dots/box drawn only on
        Source). Coords: x →, y ↓.
      </p>

      <div class="workspace-pair">
        <!-- Top row: only the two image areas (equal height); prompts/stats sit below -->
        <div class="stages-grid">
          <div class="panel panel-stage">
            <div class="panel-stage-title-row">
              <h2>Source</h2>
            </div>
            <div class="preview-stage">
              <div class="canvas-hold">
                <div
                  ref="stageWrapRef"
                  class="stage-wrap"
                  @pointerdown="onPointerDown"
                  @pointermove="onPointerMove"
                  @pointerup="onPointerUp"
                  @pointercancel="onPointerCancel"
                >
                  <img ref="imgRef" :src="imageUrl!" alt="input" class="preview" draggable="false" />
                  <div class="markers">
                    <div
                      v-for="(p, i) in fgPoints"
                      :key="'fg-' + i"
                      class="dot fg"
                      :title="'FG ' + p.x + ',' + p.y"
                      :style="dotStyle(p)"
                    />
                    <div
                      v-for="(p, i) in bgPoints"
                      :key="'bg-' + i"
                      class="dot bg"
                      :title="'BG ' + p.x + ',' + p.y"
                      :style="dotStyle(p)"
                    />
                    <div v-if="boxRect" class="box-rect" :style="boxDivStyle(boxRect)" />
                    <div v-if="draftBox" class="box-rect" :style="boxDivStyle(draftBox)" style="opacity: 0.7" />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="panel panel-stage panel-segmentation">
            <div class="panel-stage-title-row">
              <h2>Segmentation</h2>
              <div class="segmentation-head-actions">
                <div class="segmentation-view-toggle" role="group" aria-label="Segmentation output view">
                  <button
                    type="button"
                    class="btn btn-meta btn-seg-toggle"
                    :class="{ active: segViewMode === 'overlay' }"
                    title="Blended segmentation on the image"
                    :disabled="!hasSegmentationResult"
                    @click="segViewMode = 'overlay'"
                  >
                    分割效果
                  </button>
                  <button
                    type="button"
                    class="btn btn-meta btn-seg-toggle"
                    :class="{ active: segViewMode === 'extract' }"
                    title="Foreground only: original colors with transparent background (from mask)"
                    :disabled="!hasSegmentationResult || !extractUrl"
                    @click="segViewMode = 'extract'"
                  >
                    分割图
                  </button>
                  <button
                    type="button"
                    class="btn btn-meta btn-seg-toggle"
                    :class="{ active: segViewMode === 'mask' }"
                    title="Binary mask (grayscale)"
                    :disabled="!hasSegmentationResult"
                    @click="segViewMode = 'mask'"
                  >
                    Mask
                  </button>
                  <button
                    type="button"
                    class="btn btn-meta btn-seg-toggle"
                    :class="{ active: segViewMode === 'inpaint' }"
                    title="Remove segmented subject; fill with OpenCV inpaint from edges"
                    :disabled="!hasSegmentationResult"
                    @click="segViewMode = 'inpaint'"
                  >
                    智能填底
                  </button>
                </div>
                <button
                  type="button"
                  class="btn btn-meta btn-seg-download"
                  title="Download current view as PNG (switch tab for overlay / mask / inpaint / 分割图)"
                  aria-label="Download current segmentation view as PNG"
                  :disabled="!hasSegmentationResult || !segmentationDisplayUrl"
                  @click="downloadCurrentSegmentationView"
                >
                  <IconDownload :size="18" />
                </button>
              </div>
            </div>
            <div class="segmentation-stage">
              <div class="segmentation-visual">
                <div
                  v-show="isLoading"
                  class="segmentation-loading-bar"
                  role="progressbar"
                  aria-valuetext="Segmentation in progress"
                />
                <div
                  v-if="segmentationDisplayUrl"
                  ref="overlayStageRef"
                  class="overlay-stage-wrap"
                  @pointerdown="onOverlayPointerDown"
                  @pointermove="onOverlayPointerMove"
                  @pointerup="onOverlayPointerUp"
                  @pointercancel="onOverlayPointerCancel"
                >
                  <img
                    ref="overlayImgRef"
                    :src="segmentationDisplayUrl"
                    :alt="
                      segViewMode === 'mask'
                        ? 'Segmentation mask'
                        : segViewMode === 'inpaint'
                          ? 'Cutout: subject removed, inpaint fill'
                          : segViewMode === 'extract'
                            ? 'Segmented foreground with transparency'
                            : 'Segmentation overlay'
                    "
                    class="result-img"
                    :class="{
                      'result-img--mask': segViewMode === 'mask',
                      'result-img--extract': segViewMode === 'extract',
                    }"
                    draggable="false"
                  />
                </div>
                <div v-else-if="!canSegment" class="result-placeholder empty-state">
                  Add foreground/background points or draw a box, then run segmentation.
                </div>
                <div v-else class="result-placeholder empty-state result-placeholder--compact">
                  Segmentation will appear here after the model runs.
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="meta-grid">
          <div class="panel panel-meta-side">
            <h2>Prompts</h2>
            <div class="meta-panel-actions">
              <button type="button" class="btn btn-meta" @click="clearPrompts">Clear prompts</button>
              <button type="button" class="btn btn-meta" @click="clearBox" :disabled="!boxRect">Clear box</button>
              <label class="meta-option">
                <input type="checkbox" v-model="noBox" />
                No box (points only)
              </label>
            </div>
            <div class="panel-meta">
              <ul v-if="fgPoints.length" class="point-list">
                <li v-for="(p, i) in fgPoints" :key="'lfg' + i">
                  FG ({{ p.x }}, {{ p.y }})
                  <button type="button" class="rm" @click="removeFg(i)">remove</button>
                </li>
              </ul>
              <ul v-if="bgPoints.length" class="point-list">
                <li v-for="(p, i) in bgPoints" :key="'lbg' + i">
                  BG ({{ p.x }}, {{ p.y }})
                  <button type="button" class="rm" @click="removeBg(i)">remove</button>
                </li>
              </ul>
              <p v-if="boxRect" class="hint">
                Box: [{{ boxRect.x1 }}, {{ boxRect.y1 }}] → [{{ boxRect.x2 }}, {{ boxRect.y2 }}]
              </p>
              <p
                v-if="!fgPoints.length && !bgPoints.length && !boxRect"
                class="meta-empty"
              >
                Place points or draw a box on the Source or Segmentation image above.
              </p>
            </div>
          </div>
          <div class="panel panel-meta-side">
            <h2>Run info</h2>
            <div class="meta-panel-actions meta-panel-actions--run">
              <button type="button" class="btn btn-meta primary" :disabled="!canSegment || isLoading" @click="runSegment">
                Run now
              </button>
            </div>
            <div class="meta-run-body">
              <div v-if="lastScore !== null || lastMs !== null" class="stats">
                <span v-if="lastScore !== null">Score <code>{{ lastScore.toFixed(4) }}</code></span>
                <span v-if="lastMs !== null">Latency <code>{{ lastMs }} ms</code></span>
                <span v-if="lastAt">Time <code>{{ lastAt }}</code></span>
              </div>
              <p v-else class="meta-empty">Scores and timing appear after segmentation runs.</p>
              <p v-if="lastError" class="err err-in-meta">{{ lastError }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
