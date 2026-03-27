<script setup lang="ts">
defineProps<{
  canSegment: boolean
  isLoading: boolean
  lastScore: number | null
  lastMs: number | null
  lastAt: string | null
  lastError: string | null
}>()

const emit = defineEmits<{ run: [] }>()
</script>

<template>
  <div class="panel panel-meta-side">
    <h2>Run info</h2>
    <div class="meta-panel-actions meta-panel-actions--run">
      <button type="button" class="btn btn-meta primary" :disabled="!canSegment || isLoading" @click="emit('run')">
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
</template>
