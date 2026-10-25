import { describe, expect, it } from 'vitest'

import { enUS } from '@/locales/en-US'
import { zhCN } from '@/locales/zh-CN'
import { isEnvironmentKind } from '@/types/project'

describe('environment kinds', () => {
  it('recognizes testing alongside the existing three kinds', () => {
    for (const kind of ['development', 'testing', 'staging', 'production']) {
      expect(isEnvironmentKind(kind)).toBe(true)
    }
  })

  it('has a distinct label for every kind in both languages', () => {
    expect(zhCN.console.environment).toMatchObject({
      development: '开发',
      testing: '测试',
      staging: '预发',
      production: '生产',
    })
    expect(enUS.console.environment).toMatchObject({
      development: 'Development',
      testing: 'Testing',
      staging: 'Staging',
      production: 'Production',
    })
  })
})
