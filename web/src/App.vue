<script setup lang="ts">
import { ref, useTemplateRef, watch } from 'vue'
import { useBackendHealth } from './composables/useBackendHealth'
import { usePairedImageZoom } from './composables/usePairedImageZoom'
import { useSam2Annotations } from './composables/useSam2Annotations'
import { useSegmentationRun } from './composables/useSegmentationRun'
import { useWorkbenchImage } from './composables/useWorkbenchImage'
import HealthStatus from './components/HealthStatus.vue'
import PageHeader from './components/PageHeader.vue'
import PromptsPanel from './components/PromptsPanel.vue'
import RunInfoPanel from './components/RunInfoPanel.vue'
import SegmentationToolbar from './components/SegmentationToolbar.vue'
import SourceMarkersOverlay from './components/SourceMarkersOverlay.vue'
import UploadLanding from './components/UploadLanding.vue'
import WorkspaceAnnotationHint from './components/WorkspaceAnnotationHint.vue'
import WorkspaceFileBar from './components/WorkspaceFileBar.vue'

const { health, healthError } = useBackendHealth()

const fileInputRef = useTemplateRef<HTMLInputElement>('sam2-file-input')
const workbench = useWorkbenchImage(fileInputRef)
const { imageUrl, imageFile, triggerFilePick, loadFileFromInput, clearObjectUrlAndFile } = workbench

const imgRef = ref<HTMLImageElement | null>(null)
const overlayImgRef = ref<HTMLImageElement | null>(null)

const zoom = usePairedImageZoom(imgRef, overlayImgRef)
const { sharedZoomTransformStyle } = zoom

/** Bridges overlay hit-testing to the current display URL before `useSegmentationRun` exists. */
const segmentationDisplayUrlBridge = ref<string | null>(null)

const segmentHooks = {
  scheduleSegment: () => {},
  cancelScheduledSegment: () => {},
}

const annotations = useSam2Annotations({
  imageFile,
  imgRef,
  overlayImgRef,
  segmentationDisplayUrl: segmentationDisplayUrlBridge,
  onRequestSegment: () => segmentHooks.scheduleSegment(),
})

const segmentation = useSegmentationRun({
  imageFile,
  imageUrl,
  buildPrompts: () => annotations.buildPrompts(),
  canSegment: annotations.canSegment,
})

segmentHooks.scheduleSegment = segmentation.scheduleSegment
segmentHooks.cancelScheduledSegment = segmentation.cancelScheduledSegment

watch(
  () => segmentation.segmentationDisplayUrl.value,
  (v) => {
    segmentationDisplayUrlBridge.value = v
  },
  { immediate: true },
)

const {
  fgPoints,
  bgPoints,
  boxRect,
  noBox,
  draftBox,
  canSegment,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onOverlayPointerDown,
  onOverlayPointerMove,
  onOverlayPointerUp,
  onOverlayPointerCancel,
  removeFg,
  removeBg,
  resetPromptGeometry,
  clearBox,
} = annotations

const {
  isLoading,
  lastError,
  lastScore,
  lastMs,
  lastAt,
  extractUrl,
  segViewMode,
  hasSegmentationResult,
  segmentationDisplayUrl,
  runSegment,
  cancelScheduledSegment,
  downloadCurrentSegmentationView,
  clearOutputs,
} = segmentation

function resetWorkspaceForNewImage() {
  resetPromptGeometry()
  clearOutputs()
  zoom.resetSourceZoom()
  cancelScheduledSegment()
}

function onFileChange(e: Event) {
  loadFileFromInput(e, resetWorkspaceForNewImage)
}

function clearImage() {
  clearObjectUrlAndFile()
  resetWorkspaceForNewImage()
}

function clearPrompts() {
  resetPromptGeometry()
  clearOutputs()
  cancelScheduledSegment()
}
</script>

<template>
  <div class="app-layout">
    <PageHeader />

    <HealthStatus :health="health" :health-error="healthError" />

    <input
      id="image-file"
      ref="sam2-file-input"
      type="file"
      accept="image/*"
      class="sr-only"
      @change="onFileChange"
    />

    <UploadLanding v-if="!imageFile" @pick="triggerFilePick" />

    <!-- After image: compact file row + tools + split view (replaces landing) -->
    <div v-else class="workspace">
      <WorkspaceFileBar
        :file-name="imageFile.name"
        :image-width="imgRef?.naturalWidth ?? 0"
        :image-height="imgRef?.naturalHeight ?? 0"
        @replace="triggerFilePick"
        @remove="clearImage"
      />

      <WorkspaceAnnotationHint />

      <div class="workspace-pair">
        <!-- Top row: only the two image areas (equal height); prompts/stats sit below -->
        <div class="stages-grid">
          <div class="panel panel-stage">
            <div class="panel-stage-title-row">
              <h2>Source</h2>
            </div>
            <div class="preview-stage">
              <div class="canvas-hold">
                <div :ref="zoom.sourceZoomViewportRef" class="paired-zoom-viewport">
                  <div :ref="zoom.sourceZoomFlexerRef" class="paired-zoom-flexer">
                    <div
                      :ref="zoom.stageWrapRef"
                      class="stage-wrap"
                      :style="sharedZoomTransformStyle"
                      @pointerdown="onPointerDown"
                      @pointermove="onPointerMove"
                      @pointerup="onPointerUp"
                      @pointercancel="onPointerCancel"
                    >
                      <img ref="imgRef" :src="imageUrl!" alt="input" class="preview" draggable="false" />
                      <SourceMarkersOverlay
                        :fg-points="fgPoints"
                        :bg-points="bgPoints"
                        :box-rect="boxRect"
                        :draft-box="draftBox"
                        :natural-width="imgRef?.naturalWidth ?? 0"
                        :natural-height="imgRef?.naturalHeight ?? 0"
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="panel panel-stage panel-segmentation">
            <div class="panel-stage-title-row">
              <h2>Segmentation</h2>
              <SegmentationToolbar
                v-model:seg-view-mode="segViewMode"
                :has-segmentation-result="hasSegmentationResult"
                :extract-url="extractUrl"
                :can-download="hasSegmentationResult && !!segmentationDisplayUrl"
                @download="downloadCurrentSegmentationView"
              />
            </div>
            <div class="segmentation-stage">
              <div class="segmentation-visual">
                <div
                  v-show="isLoading"
                  class="segmentation-loading-bar"
                  role="progressbar"
                  aria-valuetext="Segmentation in progress"
                />
                <div v-if="segmentationDisplayUrl" :ref="zoom.segmentationZoomViewportRef" class="paired-zoom-viewport">
                  <div :ref="zoom.segmentationZoomFlexerRef" class="paired-zoom-flexer">
                    <div
                      :ref="zoom.overlayStageRef"
                      class="overlay-stage-wrap"
                      :style="sharedZoomTransformStyle"
                      @pointerdown="onOverlayPointerDown"
                      @pointermove="onOverlayPointerMove"
                      @pointerup="onOverlayPointerUp"
                      @pointercancel="onOverlayPointerCancel"
                    >
                      <img
                        ref="overlayImgRef"
                        :src="segmentationDisplayUrl"
                        :alt="
                          segViewMode === 'mask'
                            ? 'Segmentation mask'
                            : segViewMode === 'inpaint'
                              ? 'Cutout: subject removed, inpaint fill'
                              : segViewMode === 'extract'
                                ? 'Segmented foreground with transparency'
                                : 'Segmentation overlay'
                        "
                        class="result-img"
                        :class="{
                          'result-img--mask': segViewMode === 'mask',
                          'result-img--extract': segViewMode === 'extract',
                        }"
                        draggable="false"
                      />
                    </div>
                  </div>
                </div>
                <div v-else-if="!canSegment" class="result-placeholder empty-state">
                  Add foreground/background points or draw a box, then run segmentation.
                </div>
                <div v-else class="result-placeholder empty-state result-placeholder--compact">
                  Segmentation will appear here after the model runs.
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="meta-grid">
          <PromptsPanel
            v-model:no-box="noBox"
            :fg-points="fgPoints"
            :bg-points="bgPoints"
            :box-rect="boxRect"
            @clear-prompts="clearPrompts"
            @clear-box="clearBox"
            @remove-fg="removeFg"
            @remove-bg="removeBg"
          />
          <RunInfoPanel
            :can-segment="canSegment"
            :is-loading="isLoading"
            :last-score="lastScore"
            :last-ms="lastMs"
            :last-at="lastAt"
            :last-error="lastError"
            @run="runSegment"
          />
        </div>
      </div>
    </div>
  </div>
</template>
