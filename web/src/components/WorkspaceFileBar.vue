<script setup lang="ts">
defineProps<{
  fileName: string
  imageWidth: number
  imageHeight: number
}>()

const emit = defineEmits<{
  replace: []
  remove: []
}>()
</script>

<template>
  <div class="replace-bar">
    <button type="button" class="btn" @click="emit('replace')">Replace image</button>
    <span class="file-name" :title="fileName">{{ fileName }}</span>
    <span v-if="imageWidth > 0 && imageHeight > 0" class="file-meta">
      {{ imageWidth }}×{{ imageHeight }} px
    </span>
    <button type="button" class="btn btn-text" @click="emit('remove')">Remove</button>
  </div>
</template>
