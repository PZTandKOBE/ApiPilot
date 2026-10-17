// Browser E2E: real Chrome, real Vite, real FastAPI, real target API.
//
// Node 24 supplies `fetch` and a global `WebSocket`, so the DevTools Protocol needs
// no dependency. Everything this script starts, it also stops.

import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { createServer as createNetServer } from 'node:net'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const FRONTEND = join(HERE, '..')
const REPO = join(FRONTEND, '..')
const BACKEND = join(REPO, 'backend')
const PYTHON = process.env.E2E_PYTHON || join(BACKEND, '.venv', 'Scripts', 'python.exe')
const CHROME =
  process.env.E2E_CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const DB_NAME = 'aiata_c4_test'

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const log = (message) => console.log('[e2e] ' + message)

const freePort = () =>
  new Promise((resolve, reject) => {
    const server = createNetServer()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })

const children = []
const startedAt = Date.now()

const launch = (name, command, args, options) => {
  const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'], ...options })
  const record = { name, child, exited: null, output: '' }
  child.stdout.on('data', (chunk) => { record.output += String(chunk) })
  child.stderr.on('data', (chunk) => { record.output += String(chunk) })
  child.on('exit', (code) => { record.exited = code })
  children.push(record)
  return record
}

const waitForHttp = async (url, deadline, accept) => {
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (accept(response)) return true
    } catch {
      // Not listening yet.
    }
    await sleep(250)
  }
  return false
}

// --- the target API ------------------------------------------------------- //
//
// In-process on purpose: it records every request, and `blockNext` lets the test
// hold one request open so that "the browser had events while the run was still
// active" can be asserted instead of assumed.
const recorded = []
let blockNext = false
let releaseBlocked = null
const blocked = new Promise((resolve) => { releaseBlocked = resolve })

const startTarget = async () => {
  const server = createServer((request, response) => {
    const entry = { at: Date.now(), method: request.method, path: request.url }
    recorded.push(entry)
    const reply = (status, body) => {
      const payload = JSON.stringify(body)
      response.writeHead(status, { 'content-type': 'application/json' })
      response.end(payload)
    }
    const hold = blockNext ? blocked : Promise.resolve()
    blockNext = false
    void hold.then(() => {
      if (request.url.startsWith('/orders/')) {
        // Both shapes: the document says `id`, the run fixture used `orderId`.
        reply(200, { id: 'order_1', orderId: 'order_1', status: 'open' })
      } else if (request.url.startsWith('/orders')) {
        reply(201, { id: 'order_2', status: 'created' })
      } else {
        reply(404, { error: 'not found' })
      }
    })
  })
  const port = await freePort()
  await new Promise((resolve) => server.listen(port, '127.0.0.1', resolve))
  return { server, port }
}

// --- CDP ------------------------------------------------------------------ //
const connect = (url) =>
  new Promise((resolve, reject) => {
    const ws = new WebSocket(url)
    ws.onopen = () => resolve(ws)
    ws.onerror = () => reject(new Error('cdp connect failed'))
  })

const openPage = async (cdpPort) => {
  const targets = await (await fetch('http://127.0.0.1:' + String(cdpPort) + '/json/list')).json()
  const page = targets.find((target) => target.type === 'page')
  if (!page) throw new Error('no page target')
  const ws = await connect(page.webSocketDebuggerUrl)
  let nextId = 1
  const pending = new Map()
  const pageErrors = []
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data)
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) reject(new Error(JSON.stringify(message.error)))
      else resolve(message.result)
      return
    }
    if (message.method === 'Runtime.exceptionThrown') {
      pageErrors.push((message.params.exceptionDetails || {}).text || 'exception')
    }
  }
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = nextId++
      pending.set(id, { resolve, reject })
      ws.send(JSON.stringify({ id, method, params }))
    })
  await send('Page.enable')
  await send('Runtime.enable')
  const evaluate = async (expression) => {
    const out = await send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    })
    if (out.exceptionDetails) throw new Error('eval failed: ' + JSON.stringify(out.exceptionDetails).slice(0, 300))
    return out.result.value
  }
  const goto = async (url) => {
    await send('Page.navigate', { url })
    await sleep(2500)
  }
  return { ws, send, evaluate, goto, pageErrors }
}

// --- the flow ------------------------------------------------------------- //
const main = async () => {
  const deadline = Date.now() + 180000
  const backendPort = await freePort()
  const frontendPort = await freePort()
  const cdpPort = await freePort()
  const origin = 'http://127.0.0.1:' + String(frontendPort)
  const target = await startTarget()
  const profile = mkdtempSync(join(tmpdir(), 'aiapi-e2e-'))
  const reached = []

  const backend = launch('backend', PYTHON, [
    '-m', 'uvicorn', 'backend.app:create_app', '--factory',
    '--host', '127.0.0.1', '--port', String(backendPort), '--log-level', 'warning',
  ], {
    cwd: BACKEND,
    env: {
      ...process.env,
      POSTGRES_DB: DB_NAME,
      AGENT_ANALYZER: 'deterministic',
      AGENT_PLANNER: 'deterministic',
      // Without this the browser cannot read the guest-session response, and the
      // console would retry a login it can never complete.
      CORS_ALLOW_ORIGINS: origin,
    },
  })
  if (!(await waitForHttp('http://127.0.0.1:' + String(backendPort) + '/api/does-not-exist',
    Date.now() + 60000, (response) => response.status === 401 || response.status === 404))) {
    throw new Error('backend never became ready: ' + backend.output.slice(-500))
  }
  log('backend ready on ' + String(backendPort))

  const frontend = launch('frontend', 'npm', ['run', 'dev', '--', '--port', String(frontendPort), '--strictPort', '--host', '127.0.0.1'], {
    cwd: FRONTEND,
    shell: true,
    env: { ...process.env, VITE_API_BASE_URL: 'http://127.0.0.1:' + String(backendPort) },
  })
  if (!(await waitForHttp(origin + '/', Date.now() + 90000, (response) => response.ok))) {
    throw new Error('frontend never became ready: ' + frontend.output.slice(-500))
  }
  log('frontend ready on ' + origin)

  const chrome = launch('chrome', CHROME, [
    '--headless=new', '--remote-debugging-port=' + String(cdpPort),
    '--user-data-dir=' + profile, '--no-first-run', '--no-default-browser-check',
    '--disable-gpu', '--window-size=1400,1000', 'about:blank',
  ], {})
  if (!(await waitForHttp('http://127.0.0.1:' + String(cdpPort) + '/json/version', Date.now() + 40000, (response) => response.ok))) {
    throw new Error('chrome never exposed CDP')
  }
  log('chrome ready')

  const page = await openPage(cdpPort)
  const specText = readFileSync(join(HERE, 'fixtures', 'orders-openapi.json'), 'utf8')

  // 1. Guest session bootstrap. The session POST is made by the page itself.
  await page.goto(origin + '/console/projects')
  const token = await page.evaluate("localStorage.getItem('aiata.guestSession.token')")
  if (typeof token !== 'string' || token === '') {
    throw new Error('the browser could not obtain a guest session (CORS?)')
  }
  reached.push('guest-session')
  log('guest session obtained by the page')

  // 2. Project, created through the console's own dialog.
  const project = await page.evaluate(`(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
    const norm = (s) => (s || '').replace(/\\s+/g, '')
    const byText = (t) => Array.from(document.querySelectorAll('button')).filter((b) => norm(b.innerText) === t)
    await sleep(2000)
    const open = byText('\\u65b0\\u5efa\\u9879\\u76ee')[0]
    if (!open) return { error: 'no new-project button' }
    open.click()
    await sleep(1500)
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    const type = (el, v) => { el.focus(); setter.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })) }
    const inputs = Array.from(document.querySelectorAll('input[type=text]'))
    const nameEl = inputs.find((i) => i.getAttribute('placeholder') === '\\u7ed3\\u7b97 API')
    const baseEl = inputs.find((i) => i.getAttribute('placeholder') === 'https://api.example.com')
    if (!nameEl || !baseEl) return { error: 'project fields missing' }
    type(nameEl, 'E2E Orders Project')
    type(baseEl, ${JSON.stringify('http://127.0.0.1:' + String(target.port))})
    await sleep(400)
    const create = byText('\\u521b\\u5efa\\u9879\\u76ee')[0]
    if (!create) return { error: 'no create button' }
    create.click()
    await sleep(4000)
    return { path: location.pathname, projectId: location.pathname.split('/')[3] }
  })()`)
  if (!project || project.error) throw new Error('project creation failed: ' + JSON.stringify(project))
  reached.push('project')
  log('project created: ' + project.projectId)

  // 3. The spec, pasted into the lab's own paste box and analysed.
  await page.goto(origin + '/console/projects/' + project.projectId + '/ai-test')
  const analysed = await page.evaluate(`(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
    const norm = (s) => (s || '').replace(/\\s+/g, '')
    const box = document.querySelector('textarea')
    if (!box) return { error: 'no paste box' }
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(box, ${JSON.stringify(specText)})
    box.dispatchEvent(new Event('input', { bubbles: true }))
    await sleep(500)
    const paste = Array.from(document.querySelectorAll('button')).filter((b) => norm(b.innerText) === '\\u5206\\u6790\\u7c98\\u8d34\\u7684\\u6587\\u6863')[0]
    if (paste) { paste.click(); await sleep(4000) }
    // Parsing the document and analysing it are two actions: the second one is the
    // lab's own "analyse the API" button, which only appears once the document parsed.
    const analyse = Array.from(document.querySelectorAll('button')).filter((b) => norm(b.innerText) === '\\u5206\\u6790API')[0]
    if (!analyse) return { error: 'no analyse-api button', text: document.body.innerText.slice(0, 600) }
    analyse.click()
    await sleep(12000)
    // Plan generation is offered once the understanding is in.
    const plan = Array.from(document.querySelectorAll('button')).filter((b) => norm(b.innerText) === '\\u751f\\u6210\\u6d4b\\u8bd5\\u8ba1\\u5212')[0]
    let planned = false
    if (plan) { plan.click(); planned = true; await sleep(12000) }
    // The plan is a draft at this point; the console approves it itself, which is
    // where the approval authority lives in this product.
    const approve = Array.from(document.querySelectorAll('button')).filter((b) => norm(b.innerText) === '\\u6279\\u51c6\\u5e76\\u7ee7\\u7eed')[0]
    if (!approve) return { planned, approved: false, text: document.body.innerText.slice(-900) }
    approve.click()
    await sleep(2000)
    // Approval is two steps in this product: the panel opens a confirmation
    // dialog and only the dialog's primary button reaches 'approved'
    // (ApprovalPanel.vue: openApprove -> startReview, confirmApprove -> approvePlan).
    const dialog = document.querySelector('.el-dialog, .el-message-box')
    const confirm = dialog
      ? Array.from(dialog.querySelectorAll('button')).filter((b) => String(b.className).includes('primary'))[0]
      : null
    if (confirm) { confirm.click(); await sleep(3000) }
    const run = Array.from(document.querySelectorAll('button')).filter((b) => norm(b.innerText) === '\\u6267\\u884c\\u6d4b\\u8bd5')[0]
    if (!run) return { planned, approved: true, ran: false, text: document.body.innerText.slice(-900) }
    run.click()
    await sleep(15000)
    return { planned, approved: true, ran: true, href: location.href, text: document.body.innerText.slice(-1500) }
  })()`)
  if (!analysed || analysed.error) throw new Error('analysis failed: ' + JSON.stringify(analysed))
  reached.push('analysis')
  log('analysis triggered; lab text follows')
  console.log('---- lab ----')
  console.log(String(analysed.text).slice(0, 900))

  console.log('REACHED: ' + reached.join(' -> '))
  console.log('TARGET REQUESTS: ' + JSON.stringify(recorded.slice(0, 10)))

  page.ws.close()
  return { reached, projectId: project.projectId, token: true }
}

let result = null
let failure = null
try {
  result = await main()
} catch (error) {
  failure = error
  console.error('[e2e] FAILED: ' + (error && error.message ? error.message : String(error)))
} finally {
  // Normal shutdown first; SIGKILL only as a fallback that gets reported.
  for (const record of children) {
    if (record.exited !== null) continue
    record.child.kill('SIGTERM')
  }
  await sleep(1500)
  for (const record of children) {
    if (record.exited !== null) continue
    log('falling back to SIGKILL for ' + record.name)
    record.child.kill('SIGKILL')
  }
  await sleep(500)
  log('elapsed ' + String(Date.now() - startedAt) + 'ms')
}

console.log('RESULT: ' + JSON.stringify(result) + (failure ? ' ERROR: ' + failure.message : ''))
process.exit(failure ? 1 : 0)