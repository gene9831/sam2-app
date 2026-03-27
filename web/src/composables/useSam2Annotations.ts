import { computed, ref, watch, type Ref } from 'vue'

export const SAM2_DRAG_THRESHOLD_PX = 8

export type ImagePoint = { x: number; y: number }
export type ImageBox = { x1: number; y1: number; x2: number; y2: number }

/** Map screen position to image pixel coords using a displayed &lt;img&gt; (natural pixels). */
export function getPixelFromImgEl(
  el: HTMLImageElement | null,
  clientX: number,
  clientY: number,
): ImagePoint | null {
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

/**
 * Foreground/background points, optional box, brush gestures on source/overlay images.
 * Call `onRequestSegment` after geometry changes so the parent can debounce `/segment`.
 */
export function useSam2Annotations(options: {
  imageFile: Ref<File | null>
  imgRef: Ref<HTMLImageElement | null>
  overlayImgRef: Ref<HTMLImageElement | null>
  /** Keeps overlay pointer guard in sync with the active segmentation view URL. */
  segmentationDisplayUrl: Ref<string | null>
  onRequestSegment: () => void
}) {
  const { imageFile, imgRef, overlayImgRef, segmentationDisplayUrl, onRequestSegment } = options

  const fgPoints = ref<ImagePoint[]>([])
  const bgPoints = ref<ImagePoint[]>([])
  const boxRect = ref<ImageBox | null>(null)
  const noBox = ref(false)

  const brushActive = ref(false)
  const brushButton = ref<number | null>(null)
  const brushStart = ref<ImagePoint | null>(null)
  const brushCurrent = ref<ImagePoint | null>(null)

  const canSegment = computed(() => {
    if (!imageFile.value) return false
    if (fgPoints.value.length + bgPoints.value.length > 0) return true
    if (boxRect.value) return true
    return false
  })

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

  function clientToImage(clientX: number, clientY: number): ImagePoint | null {
    return getPixelFromImgEl(imgRef.value, clientX, clientY)
  }

  const draftBox = computed((): ImageBox | null => {
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

  function sameImagePoint(a: ImagePoint, b: ImagePoint) {
    return a.x === b.x && a.y === b.y
  }

  function toggleFgPoint(p: ImagePoint) {
    const i = fgPoints.value.findIndex((q) => sameImagePoint(q, p))
    if (i >= 0) fgPoints.value = fgPoints.value.filter((_, j) => j !== i)
    else fgPoints.value = [...fgPoints.value, { ...p }]
  }

  function toggleBgPoint(p: ImagePoint) {
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
      if (dist >= SAM2_DRAG_THRESHOLD_PX) {
        const x1 = Math.min(start.x, end.x)
        const y1 = Math.min(start.y, end.y)
        const x2 = Math.max(start.x, end.x)
        const y2 = Math.max(start.y, end.y)
        if (x2 - x1 > 3 && y2 - y1 > 3) {
          boxRect.value = { x1, y1, x2, y2 }
          onRequestSegment()
        } else if (brushButton.value === 0) {
          toggleFgPoint(start)
          onRequestSegment()
        } else if (brushButton.value === 2) {
          toggleBgPoint(start)
          onRequestSegment()
        }
      } else {
        if (brushButton.value === 0) {
          toggleFgPoint(start)
          onRequestSegment()
        } else if (brushButton.value === 2) {
          toggleBgPoint(start)
          onRequestSegment()
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
    onRequestSegment()
  }

  function removeBg(i: number) {
    bgPoints.value = bgPoints.value.filter((_, j) => j !== i)
    onRequestSegment()
  }

  /** Clear points and box only (does not touch API output URLs). */
  function resetPromptGeometry() {
    fgPoints.value = []
    bgPoints.value = []
    boxRect.value = null
  }

  function clearBox() {
    boxRect.value = null
    onRequestSegment()
  }

  watch(
    () => [...fgPoints.value, ...bgPoints.value],
    () => {
      if (imageFile.value) onRequestSegment()
    },
  )

  watch(boxRect, () => {
    if (imageFile.value) onRequestSegment()
  })

  watch(noBox, () => {
    if (imageFile.value) onRequestSegment()
  })

  return {
    fgPoints,
    bgPoints,
    boxRect,
    noBox,
    draftBox,
    canSegment,
    buildPrompts,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    onOverlayPointerDown,
    onOverlayPointerMove,
    onOverlayPointerUp,
    onOverlayPointerCancel,
    removeFg,
    removeBg,
    resetPromptGeometry,
    clearBox,
  }
}
