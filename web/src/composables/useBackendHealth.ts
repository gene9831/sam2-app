import { onMounted, ref } from 'vue'
import { fetchHealth, type HealthResponse } from '../api/segment'

/** Fetch `/health` once on mount for the status banner. */
export function useBackendHealth() {
  const health = ref<HealthResponse | null>(null)
  const healthError = ref<string | null>(null)

  onMounted(async () => {
    try {
      health.value = await fetchHealth()
    } catch (e) {
      healthError.value = e instanceof Error ? e.message : String(e)
    }
  })

  return { health, healthError }
}
