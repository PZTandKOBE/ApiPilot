import { describe, expect, it } from 'vitest'

import type { ConsoleMessageSchema } from '@/i18n/console-schema'
import { consoleEnUS } from '@/locales/console/en-US'
import { consoleZhCN } from '@/locales/console/zh-CN'

/**
 * The executor failure vocabulary must have a sentence in every locale.
 *
 * The backend turns an error code into a LocalizedMessage key; a missing key
 * would render as the dotted path to the user.  TypeScript enforces the schema
 * at compile time, and this test pins the runtime strings too.
 */
const failureKey: keyof ConsoleMessageSchema['runs']['failure'] = 'emptyExecutionTree'

describe('run failure locale keys', () => {
  it('has an emptyExecutionTree sentence in English', () => {
    expect(consoleEnUS.runs.failure[failureKey]).toBeTruthy()
    expect(consoleEnUS.runs.failure[failureKey]).not.toContain('console.runs.failure')
  })

  it('has an emptyExecutionTree sentence in Chinese', () => {
    expect(consoleZhCN.runs.failure[failureKey]).toBeTruthy()
    expect(consoleZhCN.runs.failure[failureKey]).not.toContain('console.runs.failure')
  })
})
