import { computed, nextTick, ref, type Ref } from 'vue'
import { useEventListener, useResizeObserver } from '@vueuse/core'

const MIN_SOURCE_ZOOM = 1
const MAX_SOURCE_ZOOM = 12

/**
 * Shared zoom/pan for the Source and Segmentation columns (same transform on both).
 * Wheel: Cmd/Ctrl + scroll zooms toward cursor; when zoomed, plain scroll pans.
 */
export function usePairedImageZoom(
  imgRef: Ref<HTMLImageElement | null>,
  overlayImgRef: Ref<HTMLImageElement | null>,
) {
  const stageWrapRef = ref<HTMLElement | null>(null)
  const sourceZoomFlexerRef = ref<HTMLElement | null>(null)
  const sourceZoomViewportRef = ref<HTMLElement | null>(null)
  const segmentationZoomViewportRef = ref<HTMLElement | null>(null)
  const segmentationZoomFlexerRef = ref<HTMLElement | null>(null)
  const overlayStageRef = ref<HTMLElement | null>(null)

  const sourceZoom = ref(1)
  const sourcePanX = ref(0)
  const sourcePanY = ref(0)

  useEventListener(stageWrapRef, 'contextmenu', (e) => e.preventDefault())
  useEventListener(overlayStageRef, 'contextmenu', (e) => e.preventDefault())

  const sharedZoomTransformStyle = computed(() => ({
    transform: `translate(${sourcePanX.value}px, ${sourcePanY.value}px) scale(${sourceZoom.value})`,
    transformOrigin: '0 0',
  }))

  function resetSourceZoom() {
    sourceZoom.value = 1
    sourcePanX.value = 0
    sourcePanY.value = 0
  }

  function clampSourcePanToViewport() {
    const vp = sourceZoomViewportRef.value
    const flexer = sourceZoomFlexerRef.value
    const img = imgRef.value
    if (!vp || !flexer || !img?.naturalWidth) return

    if (sourceZoom.value <= MIN_SOURCE_ZOOM) {
      sourcePanX.value = 0
      sourcePanY.value = 0
      return
    }

    const s = sourceZoom.value
    const Wc = img.offsetWidth
    const Hc = img.offsetHeight
    if (Wc < 1 || Hc < 1) return

    const scaledW = Wc * s
    const scaledH = Hc * s
    const Vw = vp.clientWidth
    const Vh = vp.clientHeight

    const vpR = vp.getBoundingClientRect()
    const flR = flexer.getBoundingClientRect()
    const flLeft = flR.left - vpR.left
    const flTop = flR.top - vpR.top

    let pxMin = Vw - flLeft - scaledW
    let pxMax = -flLeft
    let pyMin = Vh - flTop - scaledH
    let pyMax = -flTop

    if (pxMin > pxMax) {
      const c = (pxMin + pxMax) / 2
      pxMin = pxMax = c
    }
    if (pyMin > pyMax) {
      const c = (pyMin + pyMax) / 2
      pyMin = pyMax = c
    }

    sourcePanX.value = Math.min(pxMax, Math.max(pxMin, sourcePanX.value))
    sourcePanY.value = Math.min(pyMax, Math.max(pyMin, sourcePanY.value))
  }

  function scheduleClampSourcePan() {
    void nextTick(() => clampSourcePanToViewport())
  }

  useResizeObserver(sourceZoomViewportRef, () => clampSourcePanToViewport())
  useResizeObserver(segmentationZoomViewportRef, () => clampSourcePanToViewport())

  function wheelPixelsPerUnit(e: WheelEvent): number {
    return e.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : 1
  }

  function applyWheelPanWhenZoomed(e: WheelEvent): boolean {
    if (sourceZoom.value <= MIN_SOURCE_ZOOM) return false
    const scale = wheelPixelsPerUnit(e)
    if (e.shiftKey) {
      const dx = (e.deltaX !== 0 ? e.deltaX : e.deltaY) * scale
      sourcePanX.value -= dx
    } else {
      sourcePanY.value -= e.deltaY * scale
    }
    scheduleClampSourcePan()
    return true
  }

  function runZoomTowardCursor(e: WheelEvent, flexer: HTMLElement, img: HTMLImageElement) {
    if (!img.naturalWidth) return

    const flR = flexer.getBoundingClientRect()
    const mx = e.clientX - flR.left
    const my = e.clientY - flR.top

    const s0 = sourceZoom.value
    const step = e.deltaMode === WheelEvent.DOM_DELTA_LINE ? 0.12 : 0.002
    let s1 = s0 * Math.exp(-e.deltaY * step)
    s1 = Math.max(MIN_SOURCE_ZOOM, Math.min(MAX_SOURCE_ZOOM, s1))
    if (Math.abs(s1 - s0) < 1e-5) return

    const px = sourcePanX.value
    const py = sourcePanY.value
    const lx = (mx - px) / s0
    const ly = (my - py) / s0

    let newPx = mx - lx * s1
    let newPy = my - ly * s1

    if (s1 <= MIN_SOURCE_ZOOM) {
      s1 = MIN_SOURCE_ZOOM
      newPx = 0
      newPy = 0
    }

    sourcePanX.value = newPx
    sourcePanY.value = newPy
    sourceZoom.value = s1
    scheduleClampSourcePan()
  }

  function onSourceViewportWheel(e: WheelEvent) {
    if (!sourceZoomViewportRef.value || !sourceZoomFlexerRef.value || !imgRef.value?.naturalWidth) return

    if (e.metaKey || e.ctrlKey) {
      e.preventDefault()
      e.stopPropagation()
      const flexer = sourceZoomFlexerRef.value
      const img = imgRef.value
      if (flexer && img) runZoomTowardCursor(e, flexer, img)
      return
    }

    if (applyWheelPanWhenZoomed(e)) {
      e.preventDefault()
      e.stopPropagation()
    }
  }

  function onSegmentationViewportWheel(e: WheelEvent) {
    if (!segmentationZoomViewportRef.value || !segmentationZoomFlexerRef.value) return
    const ov = overlayImgRef.value
    if (!ov?.naturalWidth) return

    if (e.metaKey || e.ctrlKey) {
      e.preventDefault()
      e.stopPropagation()
      runZoomTowardCursor(e, segmentationZoomFlexerRef.value, ov)
      return
    }

    if (applyWheelPanWhenZoomed(e)) {
      e.preventDefault()
      e.stopPropagation()
    }
  }

  useEventListener(sourceZoomViewportRef, 'wheel', onSourceViewportWheel, { passive: false })
  useEventListener(segmentationZoomViewportRef, 'wheel', onSegmentationViewportWheel, { passive: false })

  return {
    stageWrapRef,
    sourceZoomFlexerRef,
    sourceZoomViewportRef,
    segmentationZoomViewportRef,
    segmentationZoomFlexerRef,
    overlayStageRef,
    sharedZoomTransformStyle,
    resetSourceZoom,
    scheduleClampSourcePan,
  }
}
