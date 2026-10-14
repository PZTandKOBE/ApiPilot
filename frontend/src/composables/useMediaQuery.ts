import { onBeforeUnmount, onMounted, readonly, ref, type Ref } from 'vue'

/**
 * Reactive `matchMedia`, resolved eagerly on mount.
 *
 * Used to gate the CardSwap stage: mounting it behind `v-show` would leave
 * GSAP holding a layout measured at a size that is never displayed, so the
 * stage is created only when the viewport can host it.
 */
export const useMediaQuery = (query: string): Readonly<Ref<boolean>> => {
  const matches = ref(false)

  let media: MediaQueryList | null = null
  const update = (event: MediaQueryList | MediaQueryListEvent) => {
    matches.value = event.matches
  }

  onMounted(() => {
    media = window.matchMedia(query)
    update(media)
    media.addEventListener('change', update)
  })

  onBeforeUnmount(() => {
    media?.removeEventListener('change', update)
    media = null
  })

  return readonly(matches) as Readonly<Ref<boolean>>
}
