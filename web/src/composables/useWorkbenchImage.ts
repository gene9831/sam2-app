import { onUnmounted, ref, type ShallowRef } from 'vue'

/** Local file pick: object URL, hidden file input helpers, revoke on unmount. */
export function useWorkbenchImage(fileInputRef: ShallowRef<HTMLInputElement | null>) {
  const imageUrl = ref<string | null>(null)
  const imageFile = ref<File | null>(null)

  function triggerFilePick() {
    fileInputRef.value?.click()
  }

  function revokeCurrentObjectUrl() {
    if (imageUrl.value) {
      URL.revokeObjectURL(imageUrl.value)
      imageUrl.value = null
    }
  }

  /**
   * Set image from a file input change event (clears input value after read).
   * Call `onAfterLoad` for resetting prompts, segmentation state, zoom, etc.
   */
  function loadFileFromInput(e: Event, onAfterLoad?: () => void) {
    const input = e.target as HTMLInputElement
    const f = input.files?.[0]
    if (!f) return
    imageFile.value = f
    revokeCurrentObjectUrl()
    imageUrl.value = URL.createObjectURL(f)
    onAfterLoad?.()
    input.value = ''
  }

  function clearObjectUrlAndFile() {
    revokeCurrentObjectUrl()
    imageFile.value = null
    const input = fileInputRef.value
    if (input) input.value = ''
  }

  onUnmounted(() => {
    revokeCurrentObjectUrl()
  })

  return {
    imageUrl,
    imageFile,
    triggerFilePick,
    loadFileFromInput,
    clearObjectUrlAndFile,
    revokeCurrentObjectUrl,
  }
}
