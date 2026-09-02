import { nextTick } from 'vue'

/** 目录缩略图懒加载：观察 .lazy-thumb，进入视口后再赋真实 src */
export function useTmLazyImages() {
  let lazyObserver: IntersectionObserver | null = null

  function initLazyObserver() {
    destroyLazyObserver()
    lazyObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          const img = entry.target as HTMLImageElement
          const src = img.dataset.src
          if (src && !img.src) {
            img.src = src
            lazyObserver?.unobserve(img)
          }
        }
      }
    }, { rootMargin: '80px' })
    nextTick(() => {
      document.querySelectorAll('.lazy-thumb').forEach((el) => lazyObserver?.observe(el))
    })
  }

  function destroyLazyObserver() {
    if (lazyObserver) {
      lazyObserver.disconnect()
      lazyObserver = null
    }
  }

  return { initLazyObserver, destroyLazyObserver }
}
