import { computed, ref, type ComputedRef, type Ref } from 'vue'

import { useProjectStore } from '@/stores/project'

/**
 * The new-project form, as one piece of behaviour.
 *
 * Kept out of the dialog for two reasons, and neither of them is tidiness.
 *
 * **It is the part worth testing.** Whether a name is usable, whether a second
 * click can become a second project, whether a refusal leaves the store alone —
 * those are rules, and they are the same rules whichever control draws them. The
 * dialog below is then thin enough to read in one screen.
 *
 * **The store is the only thing that creates.** Nothing here builds a request,
 * touches \`fetch\`, or knows a URL: it validates, it defers, and it reports. A
 * component that reached the service itself would be a second way to create a
 * project, and the second way is always the one that skips a check.
 */
export interface ProjectCreationForm {
  readonly name: Ref<string>
  readonly baseUrl: Ref<string>
  /** What would be sent, trimmed — the value every check below is about. */
  readonly trimmedName: ComputedRef<string>
  /** Whether the confirm control may act: a usable name, and nothing in flight. */
  readonly canSubmit: ComputedRef<boolean>
  /** Whether a create is in flight, so a form can disable itself. */
  readonly submitting: ComputedRef<boolean>
  readonly submit: () => Promise<string | null>
}

/** The wire's own limits, mirrored here so the form cannot overrun them. */
export const PROJECT_NAME_MAX = 200
export const PROJECT_BASE_URL_MAX = 1000

export const useProjectCreationForm = (): ProjectCreationForm => {
  const store = useProjectStore()

  const name = ref('')
  const baseUrl = ref('')

  const trimmedName = computed(() => name.value.trim())
  const submitting = computed(() => store.creating)
  const canSubmit = computed(() => trimmedName.value !== '' && !store.creating)

  /**
   * Create the project, or say why not.
   *
   * Returns the new id, or \`null\` — the caller decides what a failure looks
   * like.  The store's refusal and the server's refusal are the same answer here
   * on purpose: both mean "there is no project", and the sentence shown for
   * either is the one this console owns.
   */
  const submit = async (): Promise<string | null> => {
    if (!canSubmit.value) return null

    const created = await store.createProject(trimmedName.value, baseUrl.value)

    return created?.id ?? null
  }

  return { name, baseUrl, trimmedName, canSubmit, submitting, submit }
}
