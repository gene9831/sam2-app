<script setup lang="ts">
import IconDownload from './icons/IconDownload.vue'

export type SegViewMode = 'overlay' | 'mask' | 'inpaint' | 'extract'

defineProps<{
  hasSegmentationResult: boolean
  extractUrl: string | null
  canDownload: boolean
}>()

const segViewMode = defineModel<SegViewMode>('segViewMode', { required: true })

const emit = defineEmits<{ download: [] }>()
</script>

<template>
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
      :disabled="!canDownload"
      @click="emit('download')"
    >
      <IconDownload :size="18" />
    </button>
  </div>
</template>
