<script setup lang="ts">
export type ImagePoint = { x: number; y: number }
export type ImageBox = { x1: number; y1: number; x2: number; y2: number }

const props = defineProps<{
  fgPoints: ImagePoint[]
  bgPoints: ImagePoint[]
  boxRect: ImageBox | null
  draftBox: ImageBox | null
  naturalWidth: number
  naturalHeight: number
}>()

function dotStyle(p: ImagePoint) {
  if (!props.naturalWidth) return {}
  return {
    left: `${(p.x / props.naturalWidth) * 100}%`,
    top: `${(p.y / props.naturalHeight) * 100}%`,
  }
}

function boxDivStyle(r: ImageBox) {
  if (!props.naturalWidth) return {}
  const nw = props.naturalWidth
  const nh = props.naturalHeight
  const x1 = Math.min(r.x1, r.x2)
  const y1 = Math.min(r.y1, r.y2)
  const x2 = Math.max(r.x1, r.x2)
  const y2 = Math.max(r.y1, r.y2)
  return {
    left: `${(x1 / nw) * 100}%`,
    top: `${(y1 / nh) * 100}%`,
    width: `${((x2 - x1) / nw) * 100}%`,
    height: `${((y2 - y1) / nh) * 100}%`,
  }
}
</script>

<template>
  <div class="markers">
    <div
      v-for="(p, i) in fgPoints"
      :key="'fg-' + i"
      class="dot fg"
      :title="'FG ' + p.x + ',' + p.y"
      :style="dotStyle(p)"
    />
    <div
      v-for="(p, i) in bgPoints"
      :key="'bg-' + i"
      class="dot bg"
      :title="'BG ' + p.x + ',' + p.y"
      :style="dotStyle(p)"
    />
    <div v-if="boxRect" class="box-rect" :style="boxDivStyle(boxRect)" />
    <div v-if="draftBox" class="box-rect" :style="boxDivStyle(draftBox)" style="opacity: 0.7" />
  </div>
</template>
