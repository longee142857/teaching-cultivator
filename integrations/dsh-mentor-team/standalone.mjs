#!/usr/bin/env node
/**
 * VPS / headless runner for DSH mentor-team host.js
 * (no DSH GUI — same chat logic + HTTP surface).
 *
 *   PRACTICE_API_BASE=http://127.0.0.1:8768 PORT=61900 node standalone.mjs
 */
import http from 'node:http'
import fs from 'node:fs/promises'
import { readFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PORT = Number(process.env.PORT || process.env.TUTOR_PORT || 61900)
const HOST = process.env.HOST || '127.0.0.1'
const MEM_ROOT = process.env.MENTOR_MEM_DIR || path.join(__dirname, '.mentor-data')
mkdirSync(MEM_ROOT, { recursive: true })

const routes = new Map()
const harnessHandlers = new Map()

const harness = {
  handle(name, fn) {
    harnessHandlers.set(name, fn)
    return () => harnessHandlers.delete(name)
  },
}

const webServer = {
  register({ path: p, handler }) {
    routes.set(p, handler)
    return () => routes.delete(p)
  },
}

const web = {
  async fetch({ url, headers, method, body, stream }) {
    const init = { method: method || 'GET', headers: headers || {} }
    if (body != null) init.body = typeof body === 'string' ? body : JSON.stringify(body)
    const r = await fetch(url, init)
    if (stream) return { statusCode: r.status, raw: r }
    const text = await r.text()
    return { statusCode: r.status, body: { content: text } }
  },
}

const fsApi = {
  async resolve(p) {
    return p
  },
  async stat(p) {
    try {
      await fs.stat(p)
      return { ok: true }
    } catch {
      return null
    }
  },
  async readText(p) {
    return fs.readFile(p, 'utf8')
  },
  async writeText(p, text) {
    await fs.mkdir(path.dirname(p), { recursive: true })
    await fs.writeFile(p, text, 'utf8')
  },
}

const ctx = {
  get(key) {
    if (key === 'fs') return fsApi
    if (key === 'web') return web
    if (key === 'webServer') return webServer
    if (key === 'sandboxPolicy') return { workspaceRoot: MEM_ROOT }
    return undefined
  },
  effect() {
    return () => {}
  },
}

const hostCode = readFileSync(path.join(__dirname, 'host.js'), 'utf8')
const plugin = new Function('harness', hostCode)(harness)
plugin.apply(ctx)

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${HOST}:${PORT}`)
  const handler = routes.get(url.pathname)
  if (!handler) {
    res.writeHead(404, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ ok: false, error: 'not_found' }))
    return
  }
  try {
    await handler(req, res)
  } catch (e) {
    res.writeHead(500, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ ok: false, error: String(e && e.message ? e.message : e) }))
  }
})

server.listen(PORT, HOST, () => {
  const base = process.env.PRACTICE_API_BASE || 'http://127.0.0.1:8768'
  console.log(`mentor-team standalone on http://${HOST}:${PORT}  PRACTICE_API_BASE=${base}`)
})
