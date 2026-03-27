import { computed, onUnmounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import { segmentImage, base64PngToDataUrl } from '../api/segment'

type SegViewMode = 'overlay' | 'mask' | 'inpaint' | 'extract'

export const SAM2_SEGMENT_DEBOUNCE_MS = 500

/** Build PNG data URL: original RGB, alpha from grayscale mask (segmented foreground only). */
async function buildForegroundExtractDataUrl(
  imageSrc: string,
  maskSrc: string,
): Promise<string | null> {
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

/**
 * Debounced `/segment` calls, result URLs, extract view, and download helper.
 */
export function useSegmentationRun(options: {
  imageFile: Ref<File | null>
  imageUrl: Ref<string | null>
  buildPrompts: () => Record<string, unknown>
  canSegment: ComputedRef<boolean>
}) {
  const { imageFile, imageUrl, buildPrompts, canSegment } = options

  const isLoading = ref(false)
  const lastError = ref<string | null>(null)
  const lastScore = ref<number | null>(null)
  const lastMs = ref<number | null>(null)
  const lastAt = ref<string | null>(null)
  const overlayUrl = ref<string | null>(null)
  const maskUrl = ref<string | null>(null)
  const cutoutUrl = ref<string | null>(null)
  const extractUrl = ref<string | null>(null)
  const segViewMode = ref<SegViewMode>('overlay')

  let segmentDebounceId: ReturnType<typeof setTimeout> | null = null

  function cancelScheduledSegment() {
    if (segmentDebounceId !== null) {
      clearTimeout(segmentDebounceId)
      segmentDebounceId = null
    }
  }

  function clearOutputs() {
    overlayUrl.value = null
    maskUrl.value = null
    cutoutUrl.value = null
    extractUrl.value = null
    lastScore.value = null
    lastMs.value = null
    lastError.value = null
    lastAt.value = null
    isLoading.value = false
  }

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
      clearOutputs()
      return
    }
    if (!imageFile.value) return
    segmentDebounceId = setTimeout(() => {
      segmentDebounceId = null
      void runSegment()
    }, SAM2_SEGMENT_DEBOUNCE_MS)
  }

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

  onUnmounted(() => {
    cancelScheduledSegment()
  })

  return {
    isLoading,
    lastError,
    lastScore,
    lastMs,
    lastAt,
    overlayUrl,
    maskUrl,
    cutoutUrl,
    extractUrl,
    segViewMode,
    hasSegmentationResult,
    segmentationDisplayUrl,
    runSegment,
    scheduleSegment,
    cancelScheduledSegment,
    downloadCurrentSegmentationView,
    clearOutputs,
  }
}
