import { onMounted, ref } from 'vue'
import { YUANGONG_DESK_PNG, YUANGONG_DESK_SVG } from '@/constants/yuangongAssets'
import { YUANGONG_CANVAS_H, YUANGONG_CANVAS_W } from '@/constants/yuangongComposedTrim'

function probeImage(url: string): Promise<{ w: number; h: number }> {
  return new Promise((resolve, reject) => {
    const im = new Image()
    im.onload = () => {
      const w = im.naturalWidth
      const h = im.naturalHeight
      if (w > 0 && h > 0) resolve({ w, h })
      else reject(new Error('invalid natural size'))
    }
    im.onerror = () => reject(new Error('load failed'))
    im.src = url
  })
}

/**
 * 运行时读取 desk 素材实际像素尺寸（与 `<img>` naturalWidth/Height 一致），
 * 供全景横拼格宽与 YuangongStation 对齐。失败时保持 96×64（desk.svg）回退。
 */
export function useYuangongDeskIntrinsicSize() {
  const deskW = ref(YUANGONG_CANVAS_W)
  const deskH = ref(YUANGONG_CANVAS_H)
  const deskIntrinsicReady = ref(false)

  onMounted(() => {
    void (async () => {
      const urls = [YUANGONG_DESK_SVG, YUANGONG_DESK_PNG]
      for (const u of urls) {
        try {
          const { w, h } = await probeImage(u)
          deskW.value = w
          deskH.value = h
          deskIntrinsicReady.value = true
          return
        } catch {
          /* try next */
        }
      }
      deskIntrinsicReady.value = true
    })()
  })

  return { deskW, deskH, deskIntrinsicReady }
}
