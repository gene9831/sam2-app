<script setup lang="ts">
const emit = defineEmits<{ pick: [] }>()

function onPick() {
  emit('pick')
}
</script>

<template>
  <div class="landing">
    <div
      class="upload upload-hero"
      role="button"
      tabindex="0"
      @click="onPick"
      @keydown.enter.prevent="onPick"
      @keydown.space.prevent="onPick"
    >
      Click or tap to choose an image (JPEG / PNG)
    </div>
    <p class="landing-hint">Then annotate on the canvas — the large drop zone hides once an image is loaded.</p>
  </div>
</template>
