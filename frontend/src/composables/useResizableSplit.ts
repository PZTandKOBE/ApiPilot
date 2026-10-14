import { onBeforeUnmount, ref, type Ref } from 'vue'

interface SplitOptions {
  /** Starting size of the first pane, as a fraction of the container. */
  readonly initial: number
  readonly min: number
  readonly max: number
}

export interface ResizableSplit {
  /** Size of the first pane, 0–1. */
  readonly ratio: Ref<number>
  readonly dragging: Ref<boolean>
  readonly onPointerDown: (event: PointerEvent) => void
}

/**
 * Draggable divider between two stacked panes.
 *
 * The request/response split is the one place in the console where a fixed
 * ratio is wrong for somebody: a long body needs room to be written, a long
 * response needs room to be read, and those are different sessions.
 *
 * Listeners live on `window` rather than the handle so the drag survives the
 * pointer leaving the 6px handle, which it does immediately in normal use.
 */
export const useResizableSplit = (
  /** The flex container the two panes divide; owned by the caller so it can
   *  be bound with a template ref. */
  containerRef: Ref<HTMLElement | null>,
  options: SplitOptions,
): ResizableSplit => {
  const ratio = ref(options.initial)
  const dragging = ref(false)

  const onPointerMove = (event: PointerEvent): void => {
    const container = containerRef.value
    if (container === null) return

    const rect = container.getBoundingClientRect()
    if (rect.height === 0) return

    const next = (event.clientY - rect.top) / rect.height
    ratio.value = Math.min(options.max, Math.max(options.min, next))
  }

  const stop = (): void => {
    dragging.value = false
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
  }

  const onPointerDown = (event: PointerEvent): void => {
    event.preventDefault()
    dragging.value = true

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
  }

  onBeforeUnmount(stop)

  return { ratio, dragging, onPointerDown }
}
