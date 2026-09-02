/**
 * 图片附件选择 / 压缩 / 预览（原单文件机械迁出）。
 */
import { ref } from 'vue'
import { compressImageFileToDataUrl, isImageFileForVision } from '../../utils/visionMultimodal'

export function useCustomerServiceImage() {
  const pendingImageDataUrl = ref<string | null>(null)
  const imagePickError = ref('')
  const imagePicking = ref(false)
  const imageInputRef = ref<HTMLInputElement | null>(null)

  function openImagePicker() {
    imagePickError.value = ''
    const input = imageInputRef.value
    if (!input) return
    input.value = ''
    input.click()
  }

  function clearPendingImage() {
    pendingImageDataUrl.value = null
    imagePickError.value = ''
    if (imageInputRef.value) imageInputRef.value.value = ''
  }

  async function onImagePicked(ev: Event) {
    const input = ev.target as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return
    imagePickError.value = ''
    if (!isImageFileForVision(file)) {
      imagePickError.value = '请选择图片文件（png/jpg/webp 等）'
      input.value = ''
      return
    }
    imagePicking.value = true
    try {
      pendingImageDataUrl.value = await compressImageFileToDataUrl(file, {
        maxEdge: 1600,
        maxBytes: 2.5 * 1024 * 1024,
      })
    } catch (e: unknown) {
      pendingImageDataUrl.value = null
      imagePickError.value = e instanceof Error ? e.message : '图片处理失败'
    } finally {
      imagePicking.value = false
      input.value = ''
    }
  }

  return {
    pendingImageDataUrl, imagePickError, imagePicking, imageInputRef,
    openImagePicker, clearPendingImage, onImagePicked,
  }
}

export type CustomerServiceImage = ReturnType<typeof useCustomerServiceImage>
