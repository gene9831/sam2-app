/** API client; Vite dev server proxies `/api` to FastAPI (see vite.config.ts). */

const PREFIX = '/api'

export interface HealthResponse {
  status: string
  device: string | null
  checkpoint: string
}

export interface SegmentResponse {
  width: number
  height: number
  score: number
  mask_png_base64: string
  overlay_png_base64: string
  /** RGB: foreground removed, holes filled via OpenCV inpaint */
  inpaint_cutout_png_base64: string
}

export async function fetchHealth(): Promise<HealthResponse> {
  const r = await fetch(`${PREFIX}/health`)
  if (!r.ok) {
    throw new Error((await r.text()) || r.statusText)
  }
  return r.json()
}

export async function segmentImage(
  file: File,
  prompts: Record<string, unknown>,
): Promise<SegmentResponse> {
  const fd = new FormData()
  fd.append('image', file)
  fd.append('prompts_json', JSON.stringify(prompts))
  const r = await fetch(`${PREFIX}/segment`, { method: 'POST', body: fd })
  if (!r.ok) {
    throw new Error((await r.text()) || r.statusText)
  }
  return r.json()
}

export function base64PngToDataUrl(b64: string): string {
  return `data:image/png;base64,${b64}`
}
