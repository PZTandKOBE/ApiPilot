import { onScopeDispose, ref, type Ref } from 'vue'

/** How long the "copied" acknowledgement stays up. */
const FEEDBACK_MS = 1600

/**
 * `navigator.clipboard` is unavailable outside secure contexts — which
 * includes a dev server reached over plain HTTP on a LAN address, exactly the
 * situation this console is likely to be used in. The deprecated
 * `execCommand` path is the fallback for that case.
 */
const legacyCopy = (text: string): boolean => {
  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '-1000px'
    area.style.opacity = '0'

    document.body.appendChild(area)
    area.select()

    const succeeded = document.execCommand('copy')
    document.body.removeChild(area)

    return succeeded
  } catch {
    return false
  }
}

export interface Clipboard {
  /** Resolves to whether the text made it to the clipboard. */
  readonly copy: (text: string) => Promise<boolean>
  /** True for a moment after a successful copy; drives the button label. */
  readonly copied: Ref<boolean>
}

export const useClipboard = (): Clipboard => {
  const copied = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  const copy = async (text: string): Promise<boolean> => {
    let succeeded = false

    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard !== undefined) {
        await navigator.clipboard.writeText(text)
        succeeded = true
      }
    } catch {
      // Denied or unavailable — fall through to the legacy path.
    }

    if (!succeeded) succeeded = legacyCopy(text)

    if (succeeded) {
      copied.value = true
      if (timer !== null) clearTimeout(timer)
      timer = setTimeout(() => {
        copied.value = false
      }, FEEDBACK_MS)
    }

    return succeeded
  }

  onScopeDispose(() => {
    if (timer !== null) clearTimeout(timer)
  })

  return { copy, copied }
}
