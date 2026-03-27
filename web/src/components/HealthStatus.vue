<script setup lang="ts">
import type { HealthResponse } from '../api/segment'

defineProps<{
  health: HealthResponse | null
  healthError: string | null
}>()
</script>

<template>
  <div v-if="health" class="panel status-panel">
    <p class="status-line">
      Backend device: <code>{{ health.device ?? 'unknown' }}</code>
      · Status: <code>{{ health.status }}</code>
    </p>
  </div>
  <p v-else-if="healthError" class="err err-inline">
    Health check failed: {{ healthError }} — is the API running on port 8000?
  </p>
</template>
