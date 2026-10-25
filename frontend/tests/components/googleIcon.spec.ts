import { renderToString } from 'vue/server-renderer'
import { createSSRApp, h } from 'vue'
import { describe, expect, it } from 'vitest'

import GoogleIcon from '@/components/common/GoogleIcon.vue'

const render = async (): Promise<string> => {
  const app = createSSRApp({ render: () => h(GoogleIcon, { size: 16 }) })
  return renderToString(app)
}

describe('GoogleIcon', () => {
  it('renders the four official Google brand colors', async () => {
    const html = await render()

    expect(html.toLowerCase()).toContain('viewbox="0 0 24 24"')
    expect(html).toContain('fill="#4285F4"')
    expect(html).toContain('fill="#34A853"')
    expect(html).toContain('fill="#FBBC05"')
    expect(html).toContain('fill="#EA4335"')
    expect(html.match(/<path/g)).toHaveLength(4)
  })

  it('is not the old single-red path', async () => {
    const html = await render()

    expect(html).not.toContain('fill="currentColor"')
    expect(html).not.toContain('d="M12 10.2v3.9h5.5')
  })
})
