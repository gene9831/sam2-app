<script setup lang="ts">
export type ImagePoint = { x: number; y: number }
export type ImageBox = { x1: number; y1: number; x2: number; y2: number }

defineProps<{
  fgPoints: ImagePoint[]
  bgPoints: ImagePoint[]
  boxRect: ImageBox | null
}>()

const noBox = defineModel<boolean>('noBox', { required: true })

const emit = defineEmits<{
  clearPrompts: []
  clearBox: []
  removeFg: [index: number]
  removeBg: [index: number]
}>()
</script>

<template>
  <div class="panel panel-meta-side">
    <h2>Prompts</h2>
    <div class="meta-panel-actions">
      <button type="button" class="btn btn-meta" @click="emit('clearPrompts')">Clear prompts</button>
      <button type="button" class="btn btn-meta" @click="emit('clearBox')" :disabled="!boxRect">Clear box</button>
      <label class="meta-option">
        <input type="checkbox" v-model="noBox" />
        No box (points only)
      </label>
    </div>
    <div class="panel-meta">
      <ul v-if="fgPoints.length" class="point-list">
        <li v-for="(p, i) in fgPoints" :key="'lfg' + i">
          FG ({{ p.x }}, {{ p.y }})
          <button type="button" class="rm" @click="emit('removeFg', i)">remove</button>
        </li>
      </ul>
      <ul v-if="bgPoints.length" class="point-list">
        <li v-for="(p, i) in bgPoints" :key="'lbg' + i">
          BG ({{ p.x }}, {{ p.y }})
          <button type="button" class="rm" @click="emit('removeBg', i)">remove</button>
        </li>
      </ul>
      <p v-if="boxRect" class="hint">
        Box: [{{ boxRect.x1 }}, {{ boxRect.y1 }}] → [{{ boxRect.x2 }}, {{ boxRect.y2 }}]
      </p>
      <p v-if="!fgPoints.length && !bgPoints.length && !boxRect" class="meta-empty">
        Place points or draw a box on the Source or Segmentation image above.
      </p>
    </div>
  </div>
</template>
