return {
  apply(ctx) {
    const fs = ctx.get('fs')
    const web = ctx.get('web')
    const webServer = ctx.get('webServer')
    const sandboxPolicy = ctx.get('sandboxPolicy')
    const workspaceRoot = (sandboxPolicy && typeof sandboxPolicy.workspaceRoot === 'string')
      ? sandboxPolicy.workspaceRoot
      : ''

    // ── 环境配置 ──
    // Node standalone（云端）：读 process.env；真实 DSH（process 不可用）：读 {workspace}/.mentor-team/config.json
    const IS_NODE = typeof process !== 'undefined' && !!process.env
    const subprocess = ctx.get('subprocess')
    const env = function (k, d) {
      if (IS_NODE && process.env && process.env[k]) return String(process.env[k])
      return d
    }
    const PRACTICE_BASE = env('PRACTICE_API_BASE', 'http://127.0.0.1:8768').replace(/\/$/, '')
    const SYSTEM_API_BASE = env('SYSTEM_API_BASE', 'http://127.0.0.1:8770').replace(/\/$/, '')
    const LLM_BASE = (env('LLM_BASE_URL', '') || env('DEEPSEEK_API_BASE', '') || 'https://api.deepseek.com/v1').replace(/\/$/, '')
    const TUTOR_MODEL = env('TUTOR_MODEL', 'deepseek-chat')
    const MAX_TOOL_ROUNDS = 4

    let cfgCache = null
    async function getCfg() {
      if (cfgCache) return cfgCache
      let token = ''
      let llmKey = ''
      if (IS_NODE) {
        token = env('SYSTEM_API_TOKEN', '')
        llmKey = env('DEEPSEEK_API_KEY', '') || env('LLM_API_KEY', '')
      } else if (fs && workspaceRoot) {
        try {
          const t = await fs.resolve(workspaceRoot + '/.mentor-team/config.json')
          const st = await fs.stat(t)
          if (st) {
            const p = JSON.parse(await fs.readText(t))
            if (p && typeof p === 'object') {
              if (p.SYSTEM_API_TOKEN) token = String(p.SYSTEM_API_TOKEN)
              if (p.DEEPSEEK_API_KEY || p.LLM_API_KEY) llmKey = String(p.DEEPSEEK_API_KEY || p.LLM_API_KEY)
            }
          }
        } catch (e) {}
      }
      cfgCache = { token: token, llmKey: llmKey }
      return cfgCache
    }

    // ── HTTP 助手（通用：Node=web.fetch 全功能；DSH=subprocess curl） ──
    async function httpRequest(url, opts) {
      if (IS_NODE) {
        if (!web) throw new Error('web_unavailable')
        const r = await web.fetch({ url: url, method: (opts && opts.method) || 'GET', headers: (opts && opts.headers) || {}, body: opts && opts.body, stream: !!(opts && opts.stream) })
        if (opts && opts.stream) return { stream: true, status: (r && r.statusCode) || 0, raw: r.raw || r.response || null }
        let data = null
        const text = (r && r.body && typeof r.body.content === 'string') ? r.body.content : ''
        if (text) { try { data = JSON.parse(text) } catch (e) { data = null } }
        return { status: (r && r.statusCode) || 0, data: data, raw: text, text: text }
      }
      return curlRequest(url, opts)
    }

    async function curlRequest(url, opts) {
      if (!subprocess) throw new Error('subprocess_unavailable')
      const method = (opts && opts.method) || 'GET'
      const baseArgv = ['-sS', '--max-time', '90', '-X', method]
      const headers = (opts && opts.headers) || {}
      Object.keys(headers).forEach(function (k) { baseArgv.push('-H', k + ': ' + headers[k]) })
      if (opts && opts.body != null) baseArgv.push('--data-binary', String(opts.body))
      baseArgv.push('-w', '\n__HTTP__%{http_code}')
      baseArgv.push(url)
      const mkSpec = function (bin) {
        return {
          argv: [bin].concat(baseArgv),
          cwd: '.',
          stdio: { stdin: 'ignore', stdout: { maxBytes: 4000000 }, stderr: { maxBytes: 200000 } },
          graceMs: 2000,
        }
      }
      let h = null
      try { h = subprocess.spawn(mkSpec('curl')) } catch (e) { h = null }
      if ((!h || h.pid === -1)) {
        try { h = subprocess.spawn(mkSpec('C:\\Windows\\System32\\curl.exe')) } catch (e) { h = null }
      }
      if (!h) throw new Error('curl_spawn_failed')
      const outcome = await h.done
      let text = ''
      if (h.collected && h.collected.stdout) { try { text = h.collected.stdout.readFrom(0).text || '' } catch (e) { text = '' } }
      const m = text.match(/__HTTP__(\d+)\s*$/)
      let status = m ? Number(m[1]) : (outcome.exitCode === 0 ? 200 : (outcome.exitCode || 500))
      let body = text
      if (m) body = text.slice(0, m.index)
      let data = null
      try { data = JSON.parse(body) } catch (e) { data = null }
      return { status: status, data: data, raw: body, text: body }
    }

    async function httpJson(url, opts) {
      try {
        const r = await httpRequest(url, opts || {})
        return { status: r.status, data: r.data, raw: r.raw || '' }
      } catch (e) {
        return { status: 0, data: null, raw: '' }
      }
    }

    // ── 角色（工具 = 只读白名单，按角色最小权限） ──
    const ROSTER = [
      { id: 'auto', name: '团长', role: '自动分派', emoji: '🧭', tools: [] },
      { id: 'lecturer', name: '讲师', role: '讲题 · Socratic · 记忆', emoji: '📖', tools: ['practice_get_item', 'show_solution', 'kb_query', 'list_knowledge_points'] },
      { id: 'assistant', name: '学习助教', role: '诊断 · 规划 · 事件写入', emoji: '🧑‍🏫', tools: ['get_learner_params', 'get_capability_evidence', 'get_learner_snapshot', 'list_today_questions', 'build_report', 'practice_bootstrap'] },
    ]

    // ── LLM ──
    async function llmConfig() {
      const c = await getCfg()
      if (c.llmKey) return { base: LLM_BASE, key: c.llmKey, model: c.model || TUTOR_MODEL, provider: 'deepseek' }
      return null
    }
    async function llmEnabled() {
      return !!await llmConfig() && !!web && typeof web.fetch === 'function'
    }

    // stream:true 仅 Node standalone 支持（返回原始 Response）；DSH 下按非流式处理
    async function llmChat(messages, tools, opts) {
      const cfg = await llmConfig()
      if (!cfg) throw new Error('no_llm_key')
      const wantsStream = !!(opts && opts.stream) && IS_NODE
      const body = { model: cfg.model, messages: messages, stream: wantsStream }
      if (tools && tools.length) body.tools = tools
      const r = await httpRequest(cfg.base + '/chat/completions', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + cfg.key, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        stream: wantsStream,
      })
      if (wantsStream) {
        let full = ''
        const raw = r && r.raw
        if (raw && raw.body && typeof raw.body.getReader === 'function') {
          const reader = raw.body.getReader()
          const decoder = new TextDecoder()
          let buf = ''
          for (;;) {
            const step = await reader.read()
            if (step.done) break
            buf += decoder.decode(step.value || new Uint8Array(0), { stream: true })
            let idx = buf.indexOf('\n')
            while (idx >= 0) {
              const line = buf.slice(0, idx).trim()
              buf = buf.slice(idx + 1)
              if (line.indexOf('data:') === 0) {
                const payload = line.slice(5).trim()
                if (payload === '[DONE]') continue
                try {
                  const j = JSON.parse(payload)
                  const delta = j.choices && j.choices[0] && j.choices[0].delta
                  const text = delta && (delta.content || '')
                  if (text) { full += text; if (opts.onDelta) opts.onDelta(text) }
                } catch (e) {}
              }
              idx = buf.indexOf('\n')
            }
          }
        }
        return { streamed: true, text: full }
      }
      if (!(r.status >= 200 && r.status < 300) || !r.data) {
        const err = (r.data && r.data.error && (r.data.error.message || r.data.error)) || (r.raw || '').slice(0, 240) || ('http_' + (r.status || '?'))
        throw new Error(String(err))
      }
      return r.data
    }

    // ── 工具注册表（只读；:8770 优先 → :8768 → demo） ──
    const TOOLS = {
      practice_get_item: {
        desc: '按公开题号/推送号读取一道题的题干（只读）',
        params: { item: { type: 'string', description: '公开题号，如 i12' }, push: { type: 'string' } },
        required: [],
      },
      show_solution: {
        desc: '读取当前/指定题的完整解题步骤与参考要点（只读）',
        params: { item: { type: 'string' }, push: { type: 'string' } },
        required: [],
      },
      kb_query: {
        desc: '检索教学知识库中某知识点的定义/公式（只读）',
        params: { kp: { type: 'string', description: '知识点关键词，如 夹逼定理' }, subject: { type: 'string' } },
        required: ['kp'],
      },
      list_knowledge_points: {
        desc: '列出教学大纲知识点目录（只读）',
        params: { subject: { type: 'string', description: 'math 或 comm' }, query: { type: 'string' } },
        required: [],
      },
      get_learner_params: {
        desc: '读取学员能力参数 LearnerParams（BKT mastery + 域 η + assumptions，只读）',
        params: {},
        required: [],
      },
      get_capability_evidence: {
        desc: '读取学员能力证据摘要（mastery/η/薄弱点，只读）',
        params: {},
        required: [],
      },
      get_learner_snapshot: {
        desc: '读取学员最近快照摘要（只读）',
        params: { days: { type: 'integer' } },
        required: [],
      },
      list_today_questions: {
        desc: '列出今日推送题目（只读）',
        params: { subject: { type: 'string' } },
        required: [],
      },
      build_report: {
        desc: '生成最近学习周报/摘要（只读）',
        params: { days: { type: 'integer' } },
        required: [],
      },
      practice_bootstrap: {
        desc: '读取今日练习台全量（槽位+题目+已答+薄弱提示，只读）',
        params: {},
        required: [],
      },
    }
    const SCHEMAS = {}
    Object.keys(TOOLS).forEach(function (name) {
      const t = TOOLS[name]
      SCHEMAS[name] = {
        type: 'function',
        function: { name: name, description: t.desc, parameters: { type: 'object', properties: t.params, required: t.required } },
      }
    })

    async function sysHeaders(lid) {
      const c = await getCfg()
      const h = { 'X-Learner-Id': lid || 'demo1' }
      if (c.token) h['X-System-Token'] = c.token
      return h
    }

    async function practiceFallback(name, args, lid) {
      const q = [ 'learner=' + encodeURIComponent(lid || 'demo1') ]
      if (args.item) q.push('item=' + encodeURIComponent(String(args.item)))
      if (args.push) q.push('push=' + encodeURIComponent(String(args.push)))
      const map = {
        practice_get_item: '/api/v1/practice/item',
        practice_bootstrap: '/api/v1/practice/bootstrap',
        get_learner_params: '/api/v1/practice/params',
      }
      const path = map[name]
      if (path) {
        const r = await httpJson(PRACTICE_BASE + path + '?' + q.join('&'), { headers: { 'X-Learner-Id': lid || 'demo1' } })
        if (r.data && r.data.ok) {
          const res = r.data.item || r.data.result || r.data.params || r.data
          return { ok: true, source: 'practice_web:' + name, text: JSON.stringify(res) }
        }
        return null
      }
      if (name === 'get_capability_evidence') {
        const r = await httpJson(PRACTICE_BASE + '/api/v1/practice/params?' + q.join('&'), { headers: { 'X-Learner-Id': lid || 'demo1' } })
        if (r.data && r.data.ok) {
          const full = r.data.params || r.data
          const ev = {
            mastery: mapMastery(full.mastery || full.masteryWeak || (r.data.capability && r.data.capability.masteryWeak)),
            eta: mapEta(full.eta || full.domain_eta || (r.data.capability && r.data.capability.eta)),
            assumptions: Array.isArray(full.assumptions) ? full.assumptions : [],
          }
          return { ok: true, source: 'practice_web:get_capability_evidence', text: JSON.stringify(ev) }
        }
        return null
      }
      return null
    }

    function demoFallback(name, args) {
      const DEMO_TAG = '【演示数据，非真实学情】'
      const findItem = function () {
        const it = DEMO_ITEMS.find(function (x) { return x.id === (args.item || '') || String(x.pushId) === String(args.push || '') }) || DEMO_ITEMS[0]
        return it
      }
      if (name === 'show_solution') {
        const it = findItem()
        return { ok: true, source: 'demo:show_solution', text: DEMO_TAG + (it ? it.title + '\n' + (it.solutionSteps || []).join('\n') : '无题') }
      }
      if (name === 'kb_query') {
        const kp = args.kp || args.query || ''
        const hit = kbFromDemo(kp)
        return { ok: true, source: 'demo:kb_query', text: hit ? (DEMO_TAG + hit.def + '（来源 ' + hit.source + '）') : (DEMO_TAG + '无匹配知识点') }
      }
      if (name === 'list_knowledge_points') {
        return { ok: true, source: 'demo:list_knowledge_points', text: DEMO_TAG + Object.keys(DEMO_KB).join('\n') }
      }
      if (name === 'get_learner_params' || name === 'get_capability_evidence') {
        return { ok: true, source: 'demo:learner', text: DEMO_TAG + JSON.stringify({ mastery: DEMO_LEARNER.mastery, eta: DEMO_LEARNER.eta, assumptions: DEMO_LEARNER.assumptions }) }
      }
      if (name === 'get_learner_snapshot') {
        return { ok: true, source: 'demo:snapshot', text: DEMO_TAG + JSON.stringify({ weak: DEMO_LEARNER.mastery.slice(0, 3) }) }
      }
      if (name === 'list_today_questions') {
        return { ok: true, source: 'demo:today', text: DEMO_TAG + DEMO_ITEMS.map(function (i) { return i.id + ' ' + i.title }).join('\n') }
      }
      if (name === 'build_report') {
        return { ok: true, source: 'demo:report', text: DEMO_TAG + '最近薄弱：' + DEMO_LEARNER.mastery.slice(0, 3).map(function (m) { return m.kp }).join('、') }
      }
      if (name === 'practice_bootstrap') {
        return { ok: true, source: 'demo:bootstrap', text: DEMO_TAG + JSON.stringify({ slots: DEMO_ITEMS.map(function (i) { return { itemId: i.id, title: i.title, kp: i.kp } }) }) }
      }
      return null
    }

    function kbFromDemo(kp) {
      if (!kp) return null
      if (DEMO_KB[kp]) return DEMO_KB[kp]
      const keys = Object.keys(DEMO_KB)
      for (let i = 0; i < keys.length; i++) {
        if (kp.indexOf(keys[i]) >= 0 || keys[i].indexOf(kp) >= 0) return DEMO_KB[keys[i]]
      }
      return null
    }

    async function execTool(name, args, lid) {
      const qs = Object.keys(args || {}).filter(function (k) { return args[k] !== undefined && args[k] !== null && String(args[k]) !== '' })
        .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(String(args[k])) }).join('&')
      // 1) system_api :8770
      const r1 = await httpJson(SYSTEM_API_BASE + '/v1/tools/' + name + (qs ? '?' + qs : ''), { headers: await sysHeaders(lid) })
      if (r1.data && r1.data.ok) {
        const res = r1.data.result
        const text = typeof res === 'string' ? res : JSON.stringify(res)
        return { ok: true, source: 'system_api:' + name, text: text }
      }
      // 2) practice_web :8768
      const pw = await practiceFallback(name, args, lid)
      if (pw) return pw
      // 3) demo
      const dm = demoFallback(name, args)
      if (dm) return dm
      return { ok: false, source: name, text: '工具 ' + name + ' 暂不可用（教学系统未连接）' }
    }

    // ── 演示数据 ──
    const DEMO_LEARNER = {
      id: 'demo1',
      mastery: [
        { kp: '极限 · 夹逼定理', p: 0.28, domain: 'calc' },
        { kp: '特征值', p: 0.31, domain: 'linalg' },
        { kp: '积分 · 换元', p: 0.42, domain: 'calc' },
        { kp: '导数 · 隐函数求导', p: 0.55, domain: 'calc' },
        { kp: '卷积', p: 0.63, domain: 'comm' },
      ],
      eta: [
        { domain: 'calc', eta: -0.4, n: 12 },
        { domain: 'linalg', eta: 0.2, n: 8 },
        { domain: 'prob', eta: 0.0, n: 0 },
      ],
      assumptions: [
        '题参未标定：a=1.0，d 由 difficulty 粗映射',
        'η̂ 仅相对序有意义（未联合标定前）',
        'BKT mastery 不直接作为事件成功概率',
      ],
    }
    const DEMO_ITEMS = [
      { id: 'i1', pushId: 1, title: '极限 · 夹逼定理', kp: '极限 · 夹逼定理', subject: '高等数学', stem: '已知 1/n ≤ a_n ≤ (n+1)/n²，求 lim a_n。', answer: '0', finalAnswer: '0', solutionSteps: ['由 1/n ≤ a_n ≤ (n+1)/n²', '两端 n→∞ 均趋于 0，故 a_n → 0'] },
      { id: 'i2', pushId: 2, title: '信号与系统 · 卷积', kp: '卷积', subject: '通信', stem: '求输出 y(t)=x(t)*h(t) 的表达式要点。', answer: 'y=x*h', finalAnswer: 'y(t)=x*h', solutionSteps: ['输出为输入与冲激响应的卷积', '先画支撑再定积分限'] },
      { id: 'i3', pushId: 3, title: '导数 · 隐函数求导', kp: '导数 · 隐函数求导', subject: '高等数学', stem: 'x²+xy+y²=3，求 (1,1) 处 dy/dx。', answer: '-1', finalAnswer: '-1', solutionSteps: ['两边对 x 求导得 y′=−(2x+y)/(x+2y)', '点 (1,1) 处为 −1'] },
    ]
    const DEMO_KB = {
      '极限 · 夹逼定理': { def: '若 g(n) ≤ a_n ≤ h(n) 且 g、h 同趋于 L，则 a_n → L。关键：两端必须收敛到同一个值。', source: 'syllabus_math.json · 极限' },
      '导数 · 隐函数求导': { def: '对 F(x,y)=0 两边关于 x 求导，再解出 dy/dx（注意 y 是 x 的函数）。', source: 'syllabus_math.json · 微分' },
      '积分 · 换元': { def: '∫ f(g(x))g′(x)dx = F(g(x)) + C（凑微分/换元，注意换限）。', source: 'syllabus_math.json · 积分' },
      '卷积': { def: 'y(t)=∫ x(τ)h(t−τ)dτ；支撑区间决定积分上下限。', source: 'syllabus_comm.json · 卷积' },
    }

    // ── 工具函数 ──
    function safe(s) { return String(s || '').replace(/[^\w\-.]/g, '_').slice(0, 64) || 'anon' }

    // ── 记忆：T0 工作状态 + T1 线程 + T2 语义卡 ──
    const mem = { cards: {}, threads: {}, states: {} }
    function cardPath(id) { return workspaceRoot ? (workspaceRoot + '/.mentor-team/learners/' + safe(id) + '/card.json') : '' }

    async function loadCard(id) {
      const lid = id || 'demo1'
      if (mem.cards[lid]) return mem.cards[lid]
      let card = { learnerId: lid, weak: [], strengths: [], notes: [], milestones: [], updatedAt: 0 }
      if (fs && cardPath(lid)) {
        try {
          const t = await fs.resolve(cardPath(lid))
          const st = await fs.stat(t)
          if (st) {
            const txt = await fs.readText(t)
            const p = JSON.parse(txt)
            if (p && typeof p === 'object') card = Object.assign(card, p)
          }
        } catch (e) {}
      }
      mem.cards[lid] = card
      return card
    }
    async function saveCard(id, card) {
      const lid = id || 'demo1'
      mem.cards[lid] = card
      if (fs && cardPath(lid)) {
        try {
          const t = await fs.resolve(cardPath(lid))
          await fs.writeText(t, JSON.stringify(card, null, 2))
        } catch (e) {}
      }
    }
    function pushThread(lid, tid, role, text) {
      const key = safe(lid) + '|' + safe(tid)
      const arr = mem.threads[key] || (mem.threads[key] = [])
      arr.push({ role: role, text: String(text || '').slice(0, 2000), ts: Date.now() })
      if (arr.length > 40) arr.splice(0, arr.length - 40)
    }

    // T0 工作记忆：phase + todos + 当前题（对齐 memory_blocks.py）
    function defaultState(lid) {
      return { learnerId: lid, phase: 'idle', todos: [], activeItemId: '', updatedAt: Date.now() }
    }
    function loadState(lid) {
      const key = safe(lid)
      if (!mem.states[key]) mem.states[key] = defaultState(lid)
      return mem.states[key]
    }
    function saveState(lid) {
      const st = loadState(lid)
      st.updatedAt = Date.now()
      mem.states[lid] = st
    }
    function stateLine(lid) {
      const st = loadState(lid)
      const todos = (st.todos || []).filter(function (t) { return t.status !== 'done' })
      const lines = []
      lines.push('phase=' + st.phase + (st.activeItemId ? ' activeItem=' + st.activeItemId : ''))
      if (todos.length) lines.push('todos=' + todos.map(function (t) { return t.content }).join(';'))
      return lines.join(' | ')
    }
    function applyToolState(name, args, lid) {
      const st = loadState(lid)
      if (name === 'practice_get_item' || name === 'show_solution') {
        st.activeItemId = args.item || args.push || st.activeItemId || ''
        st.phase = 'awaiting_answer'
        st.todos = [{ id: 'await', content: '等待学员作答/追问当前题', status: 'pending' }]
      } else if (name === 'get_learner_params' || name === 'get_capability_evidence' || name === 'get_learner_snapshot' || name === 'build_report') {
        st.phase = 'reviewing'
        st.todos = []
      } else if (name === 'practice_bootstrap' || name === 'list_today_questions') {
        st.phase = 'planning'
        st.todos = []
      }
      saveState(lid)
    }

    // ── 接地（bootstrap+params 上下文，供 LLM system 注入与 demo 兜底） ──
    async function fetchJson(url, headers) {
      if (IS_NODE && !web) return null
      try {
        const r = await httpRequest(url, { headers: headers || {} })
        if (!(r.status >= 200 && r.status < 300) || r.data === null) return null
        return r.data
      } catch (e) { return null }
    }
    function mapMastery(raw) {
      const out = []
      if (!raw) return out
      if (Array.isArray(raw)) {
        raw.forEach(function (w) {
          if (!w) return
          const kp = w.kp || w.knowledge_point || w.id
          const p = Number(w.p != null ? w.p : (w.p_mastery != null ? w.p_mastery : NaN))
          if (kp && !Number.isNaN(p)) out.push({ kp: String(kp), p: p, domain: w.domain || null })
        })
        return out
      }
      if (typeof raw === 'object') {
        Object.keys(raw).forEach(function (kp) {
          const v = raw[kp]
          if (typeof v === 'number') out.push({ kp: kp, p: v, domain: null })
          else if (v && typeof v === 'object') {
            const p = Number(v.p_mastery != null ? v.p_mastery : (v.p != null ? v.p : NaN))
            if (!Number.isNaN(p)) out.push({ kp: kp, p: p, domain: v.domain || null })
          }
        })
      }
      return out
    }
    function mapEta(raw) {
      const out = []
      if (!raw) return out
      if (Array.isArray(raw)) {
        raw.forEach(function (e) {
          if (!e || e.domain == null) return
          out.push({ domain: String(e.domain), eta: Number(e.eta || 0), n: Number(e.n || 0) })
        })
        return out
      }
      if (typeof raw === 'object') {
        Object.keys(raw).forEach(function (domain) {
          const v = raw[domain]
          if (typeof v === 'number') out.push({ domain: domain, eta: v, n: 0 })
          else if (v && typeof v === 'object') out.push({ domain: domain, eta: Number(v.eta != null ? v.eta : v), n: Number(v.n || 0) })
        })
      }
      return out
    }
    function mapItem(it) {
      if (!it) return null
      return {
        id: it.id || (it.itemId != null ? ('i' + it.itemId) : ''),
        pushId: it.pushId,
        title: it.title || '',
        kp: it.kp || '未分类',
        subject: it.subject || '',
        stem: it.stem || '',
        explain: it.explain || '',
        answered: !!it.answered,
        solutionSteps: it.solutionSteps || (it.explain ? [String(it.explain)] : []),
      }
    }
    async function enrichItem(learnerId, itemId, pushId) {
      if (!itemId && !pushId) return null
      const q = []
      if (learnerId) q.push('learner=' + encodeURIComponent(learnerId))
      if (itemId) q.push('item=' + encodeURIComponent(itemId))
      if (pushId) q.push('push=' + encodeURIComponent(pushId))
      const data = await fetchJson(PRACTICE_BASE + '/api/v1/practice/item?' + q.join('&'), { 'X-Learner-Id': learnerId })
      if (data && data.ok && data.item) return mapItem(data.item)
      return null
    }
    async function tryLive(learnerId) {
      const lid = learnerId || 'demo1'
      const boot = await fetchJson(PRACTICE_BASE + '/api/v1/practice/bootstrap?learner=' + encodeURIComponent(lid), { 'X-Learner-Id': lid })
      if (!(boot && boot.ok)) return null
      const items = (boot.items || []).map(mapItem).filter(Boolean)
      let mastery = mapMastery((boot.capability && boot.capability.masteryWeak) || [])
      let eta = mapEta((boot.capability && boot.capability.eta) || {})
      let assumptions = []
      const params = await fetchJson(PRACTICE_BASE + '/api/v1/practice/params?learner=' + encodeURIComponent(lid), { 'X-Learner-Id': lid })
      if (params && params.ok) {
        const full = params.params || params
        const m2 = mapMastery(full.mastery || full.masteryWeak || (params.capability && params.capability.masteryWeak))
        if (m2.length) mastery = m2
        const e2 = mapEta(full.eta || full.domain_eta || (params.capability && params.capability.eta))
        if (e2.length) eta = e2
        if (Array.isArray(full.assumptions)) assumptions = full.assumptions
        else if (full.assumptions && typeof full.assumptions === 'object') {
          assumptions = Object.keys(full.assumptions).map(function (k) { return k + ': ' + full.assumptions[k] })
        }
      }
      return {
        kind: 'live',
        detached: false,
        learner: {
          id: boot.learner || lid,
          mastery: mastery,
          eta: eta,
          assumptions: assumptions.length ? assumptions : ['BKT mastery 不直接作为事件成功概率'],
        },
        items: items,
        kb: DEMO_KB,
        weakHint: boot.weakHint || '',
        sources: [{ source: 'practice_web ' + PRACTICE_BASE, ref: 'live bootstrap+params' }],
      }
    }
    async function ground(learnerId) {
      const live = await tryLive(learnerId)
      if (live) return live
      return {
        kind: 'demo',
        detached: true,
        learner: DEMO_LEARNER,
        items: DEMO_ITEMS,
        kb: DEMO_KB,
        weakHint: '近期易错：极限 · 夹逼定理',
        sources: [{ source: '本地演示数据（教学系统未连接）', ref: 'demo' }],
      }
    }

    function cap(arr, n) { while (arr.length > n) arr.shift(); return arr }
    function weakList(learner) {
      const m = (learner && learner.mastery) || []
      return m.slice().sort(function (a, b) { return a.p - b.p }).slice(0, 3)
    }
    function pickItem(g, msg, preferredId) {
      const items = (g && g.items) || []
      if (!items.length) return null
      if (preferredId) {
        for (let i = 0; i < items.length; i++) {
          if (items[i].id === preferredId || String(items[i].pushId) === String(preferredId)) return items[i]
        }
      }
      for (let i = 0; i < items.length; i++) {
        const it = items[i]
        if (msg && ((it.kp && msg.indexOf(it.kp) >= 0) || (it.title && msg.indexOf(it.title) >= 0))) return it
      }
      for (let i = 0; i < items.length; i++) { if (!items[i].answered) return items[i] }
      return items[0]
    }
    function kbFor(g, kp) {
      const kb = (g && g.kb) || {}
      if (!kp) return null
      if (kb[kp]) return kb[kp]
      const keys = Object.keys(kb)
      for (let i = 0; i < keys.length; i++) { if (kp.indexOf(keys[i]) >= 0 || keys[i].indexOf(kp) >= 0) return kb[keys[i]] }
      return null
    }

    // ── 规则路径：边界闸 + 事件写/列（保留；LLM 主路径在其后） ──
    function compose(mentorId, message, g) {
      const msg = String(message || '').trim()
      const learner = g.learner || DEMO_LEARNER
      const item = pickItem(g, msg, '')
      const weak = weakList(learner)

      if (/批改|判分|对错|grade|判题|出题|命题|generate|变式|新题|再出一题/.test(msg)) {
        return {
          __ruleOnly: true,
          reply: '这块由教学运行时负责：批改请到练习台提交作答（教学系统会批改并回写 BKT/η）；命题/变式由教学系统的定时或人工确认流程完成。我这边只做讲解、诊断与规划建议，不直接批改、不出题。\n\n例外：Capability Brain 的「事件」可由导师团写入（说「写入事件：考研专业课通过」）。',
          citations: [{ n: 1, source: '边界约定', quote: '批改/命题硬闸在 teaching；事件目录可写' }],
          actions: ['写入事件：考研专业课通过', '讲这道题', '诊断薄弱点'],
          delta: null,
        }
      }
      if (/写入事件|新增事件|创建事件|登记事件|添加事件/.test(msg)) return { __eventWrite: true, message: msg }
      if (/列出事件|有哪些事件|事件目录|事件列表/.test(msg)) return { __eventList: true, message: msg }

      if (mentorId === 'assistant') {
        const isPlan = /计划|今日|复习|周报|安排|节奏|下一题|规划/.test(msg)
        if (isPlan) {
          const items = g.items || []
          const slots = [
            { label: '高等数学', win: '08:00–12:00' },
            { label: '通信', win: '14:00–18:00' },
            { label: '复习', win: '20:00–22:00' },
          ]
          const lines = ['今日计划建议（只读参考，不替你排入系统）：']
          if (!items.length) lines.push('· 今日暂无推送题（或教学系统未返回 items）。')
          items.forEach(function (it, i) {
            const s = slots[i] || { label: '补位', win: '机动' }
            lines.push('· ' + s.label + '（' + s.win + '）— ' + (it.title || it.kp) + (it.answered ? '（已答✓）' : ''))
          })
          if (weak.length) lines.push('')
          if (weak.length) lines.push('建议顺序：先做最弱的「' + weak[0].kp + '」。')
          else if (g.weakHint) lines.push('薄弱提示：' + g.weakHint)
          lines.push('⚠️ 以上是建议；实际推送/批改由教学运行时决定。')
          return {
            reply: lines.join('\n'),
            citations: items.map(function (it, i) { return { n: i + 1, source: '今日推送 slot ' + (i + 1), quote: (it.title || '') + ' · ' + (it.kp || '') } }),
            actions: ['诊断薄弱点', '讲这道题'],
            delta: { note: '规划建议（只读）' },
          }
        }
        const lines = ['你的薄弱知识点（BKT p_mastery 最低三项）：']
        if (!weak.length) lines.push('（暂无 mastery 明细；' + (g.weakHint ? ('提示：' + g.weakHint) : '可先做今日题后再诊') + '）')
        else weak.forEach(function (w, i) { lines.push((i + 1) + '. ' + w.kp + ' — p=' + w.p) })
        const eta = (learner.eta || []).slice().sort(function (a, b) { return a.eta - b.eta })
        if (eta.length) {
          lines.push('')
          lines.push('域潜特质 η（仅相对序）：')
          eta.forEach(function (e) { lines.push('· ' + e.domain + ' η=' + e.eta + (e.n ? '（观测 ' + e.n + ' 题）' : '（无观测）')) })
        }
        lines.push('')
        lines.push('⚠️ 诚实边界：' + ((learner.assumptions && learner.assumptions[0]) || 'BKT mastery 不直接作为事件成功概率'))
        if (weak.length) lines.push('建议：优先补齐最弱 KP，再轮转其它域。（此为建议，不写入任何权重/快照。）')
        return {
          reply: lines.join('\n'),
          citations: weak.map(function (w, i) { return { n: i + 1, source: 'LearnerParams.mastery', quote: w.kp + ' p_mastery=' + w.p } }).concat((learner.assumptions || []).map(function (s, i) { return { n: weak.length + i + 1, source: 'ParamAssumptions', quote: s } })),
          actions: ['今日计划', '讲这道题'],
          delta: weak.length ? { weak: weak.map(function (w) { return { kp: w.kp, p: w.p } }) } : null,
        }
      }

      // lecturer（规则回落）
      if (item) {
        const entry = kbFor(g, item.kp)
        const wantFull = /完整|全解|看全|答案|全步骤|solution/.test(msg)
        const lines = ['我们看「' + (item.title || item.kp) + '」（' + (item.kp || '') + '）。']
        if (entry) { lines.push(''); lines.push('先确认概念：' + entry.def) }
        if (wantFull) {
          if (item.solutionSteps && item.solutionSteps.length) {
            lines.push(''); lines.push('讲解：')
            item.solutionSteps.forEach(function (s, i) { lines.push((i + 1) + '. ' + s) })
          } else if (item.explain) {
            lines.push(''); lines.push('讲解：' + item.explain)
          } else {
            lines.push(''); lines.push('当前条目没有可公开的完整解字段；请结合题干自己推一步，或到练习台看批改回写。')
          }
        } else {
          if (item.solutionSteps && item.solutionSteps[0]) {
            lines.push(''); lines.push('提示（先想思路，不代算）：' + item.solutionSteps[0])
          } else if (item.stem) {
            lines.push(''); lines.push('题干要点：' + String(item.stem).slice(0, 180))
          }
          lines.push(''); lines.push('你先自己写一步，卡住再问我；也可以让我给更完整讲解。')
        }
        return {
          reply: lines.join('\n'),
          citations: [{ n: 1, source: '题目 ' + (item.id || '') + ' · ' + (item.kp || ''), quote: item.stem || '' }].concat(entry ? [{ n: 2, source: entry.source, quote: entry.def }] : []),
          actions: wantFull ? ['给提示', '诊断薄弱点'] : ['给完整解', '诊断薄弱点'],
          delta: { milestone: item.kp },
        }
      }
      return {
        reply: '请先告诉我你想讨论哪道题/哪个知识点。当前为' + (g.detached ? '脱机演示' : '已连接教学系统') + '模式。',
        citations: [],
        actions: ['诊断薄弱点'],
        delta: null,
      }
    }

    function applyDelta(card, delta) {
      if (!delta) return
      if (delta.weak) card.weak = delta.weak
      if (delta.note) { card.notes.push(delta.note); cap(card.notes, 8) }
      if (delta.milestone) { card.milestones.push({ kp: delta.milestone, at: Date.now() }); cap(card.milestones, 8) }
    }

    function routeMentor(msg) {
      const m = String(msg || '')
      if (/写入事件|新增事件|创建事件|登记事件|添加事件|列出事件|事件目录|事件列表/.test(m)) return 'assistant'
      if (/薄弱|诊断|能力|η|mastery|学情|掌握|计划|今日|复习|周报|安排|节奏|下一题|规划/.test(m)) return 'assistant'
      return 'lecturer'
    }

    function buildMessages(mentor, msg, g, learnerId, itemId) {
      const item = pickItem(g, msg, itemId || '')
      const learner = g.learner || {}
      const weak = weakList(learner)
      const ctx = {
        mentor: { id: mentor.id, name: mentor.name, role: mentor.role },
        learnerId: learner.id || learnerId || '',
        state: stateLine(learnerId),
        weakTop: weak.slice(0, 5),
        eta: (learner.eta || []).slice(0, 6),
        todayItems: (g.items || []).slice(0, 6).map(function (it) {
          return { id: it.id, title: it.title, kp: it.kp, answered: !!it.answered }
        }),
        activeItem: item ? { id: item.id, title: item.title, kp: item.kp, stem: (item.stem || item.content || '').slice(0, 2500) } : null,
        groundKind: g.kind || '',
        detached: !!g.detached,
      }
      const system = [
        '你是高校考研培养系统里的「导师团」讲师/助教，通过练习台 Chat 与学员对话。',
        '角色：' + mentor.name + '（' + mentor.role + '）。',
        '硬边界：不批改、不出题、不改 BKT/η；批改与命题由练习台/教学运行时负责。',
        '可做：讲题、追问、概念澄清、薄弱诊断建议、学习节奏建议；需要数据时【调用工具】获取，不要编造；Capability Brain 事件写入由系统特殊指令处理。',
        '工具返回的内容是权威证据；引用时用 [n] 标注。若工具不可用或数据缺失，明确说明「暂未取到」，不要硬编。',
        '用简洁中文；有当前题时紧扣题干与知识点。',
      ].join('\n')
      return [
        { role: 'system', content: system },
        { role: 'user', content: '【接地上下文】\n' + JSON.stringify(ctx, null, 2) + '\n\n【学员消息】\n' + msg },
      ]
    }

    // ── LLM 工具循环（按需取数 → 逐条证据 → 最终生成） ──
    async function runAgent(mentor, msg, g, learnerId, itemId, onDelta) {
      const toolNames = (mentor.tools || []).filter(function (n) { return SCHEMAS[n] })
      const tools = toolNames.map(function (n) { return SCHEMAS[n] })
      const messages = buildMessages(mentor, msg, g, learnerId, itemId)
      const evidence = []
      let rounds = 0
      while (rounds < MAX_TOOL_ROUNDS) {
        rounds++
        const resp = await llmChat(messages, tools, { stream: false })
        const choice = (resp.choices && resp.choices[0]) || {}
        const assistantMsg = choice.message || {}
        const tcs = assistantMsg.tool_calls || []
        if (!tcs.length) {
          // 已就绪：若有 SSE 需求，用无工具流式复生成最终回答；否则用本次内容
          if (onDelta) {
            const streamed = await llmChat(messages, [], { stream: true, onDelta: onDelta })
            return { text: streamed.text, evidence: evidence, streamed: true }
          }
          return { text: String(assistantMsg.content || '').trim(), evidence: evidence, streamed: false }
        }
        messages.push({ role: 'assistant', content: null, tool_calls: tcs })
        for (let i = 0; i < tcs.length; i++) {
          const tc = tcs[i]
          const name = tc.function && tc.function.name
          let args = {}
          try { args = JSON.parse((tc.function && tc.function.arguments) || '{}') } catch (e) { args = {} }
          const res = await execTool(name, args, learnerId)
          evidence.push({ n: evidence.length + 1, source: res.source || name, quote: String(res.text || '').slice(0, 200) })
          applyToolState(name, args, learnerId)
          messages.push({ role: 'tool', tool_call_id: tc.id, content: String(res.text || '工具不可用').slice(0, 4000) })
        }
      }
      throw new Error('tool_loop_exhausted')
    }

    // ── 事件写/列（沿用） ──
    function parseEventWrite(message) {
      const msg = String(message || '')
      let title = ''
      const m1 = msg.match(/(?:写入|新增|创建|登记|添加)事件[：:\s]*([^\n]+)/)
      if (m1) title = m1[1].trim()
      title = title.replace(/\b(id|domains|domain|p_hat|p)\s*=\s*\S+/gi, '').trim()
      title = title.replace(/[，,]\s*$/, '').trim()
      const idM = msg.match(/\bid\s*=\s*([A-Za-z0-9_\-]+)/i)
      const domM = msg.match(/\bdomains?\s*=\s*([A-Za-z0-9_,\-]+)/i)
      const pM = msg.match(/\bp_hat\s*=\s*([0-9.]+)/i) || msg.match(/\bp\s*=\s*([0-9.]+)/i)
      let domains = []
      if (domM) domains = domM[1].split(/[,，]/).map(function (s) { return s.trim() }).filter(Boolean)
      if (!domains.length && /专业课|通信|OFDM|奈奎斯特|ISI|调制|信息论|信道/.test(msg + title)) domains = ['comm', 'signals']
      if (!domains.length && /数学|微积分|线代/.test(msg + title)) domains = ['calc', 'linalg', 'prob']
      if (!domains.length) domains = ['comm']
      if (!title) title = /专业课/.test(msg) ? '考研专业课通过' : '导师写入事件'
      const out = { title: title, domains: domains, author: 'mentor' }
      if (idM) out.id = idM[1]
      if (pM) out.p_hat = Number(pM[1])
      if (/专业课/.test(title) && !idM) out.id = 'grad_exam_major_pass'
      return out
    }
    async function listCapabilityEvents() {
      const data = await fetchJson(PRACTICE_BASE + '/api/v1/capability/events', {})
      if (data && data.ok && Array.isArray(data.events)) return data.events
      return []
    }
    async function upsertCapabilityEvent(payload, mentorId) {
      if (IS_NODE && !web) return { ok: false, error: 'web_unavailable' }
      try {
        const body = Object.assign({}, payload || {}, { mentor: mentorId || 'assistant' })
        const r = await httpRequest(PRACTICE_BASE + '/api/v1/capability/events', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (r.data) return r.data
        if (r.text) { try { return JSON.parse(r.text) } catch (e) { return { ok: false, error: 'bad_json' } } }
        return { ok: false, error: 'empty_response' }
      } catch (e) {
        return { ok: false, error: String(e && e.message ? e.message : e) }
      }
    }

    // ── 主对话 ──
    async function runChat(args, sse) {
      const msg = String((args && args.message) || '').trim()
      const learnerId = (args && args.learner) || 'demo1'
      const threadId = (args && args.threadId) || (args && args.item) || 'general'
      const itemId = (args && args.item) || ''
      const pushId = (args && args.push) || ''
      let mentorId = (args && args.mentor) || 'auto'
      let routedFrom = null
      if (mentorId === 'auto' || !ROSTER.some(function (m) { return m.id === mentorId })) {
        routedFrom = 'auto'
        mentorId = routeMentor(msg)
      }
      const mentor = ROSTER.find(function (m) { return m.id === mentorId }) || ROSTER[0]
      const g = await ground(learnerId)
      let forcedItem = null
      if (itemId || pushId) {
        forcedItem = pickItem(g, '', itemId)
        if (!forcedItem) forcedItem = await enrichItem(learnerId, itemId, pushId)
        if (forcedItem) {
          const exists = (g.items || []).some(function (it) { return it.id === forcedItem.id })
          if (!exists) g.items = [forcedItem].concat(g.items || [])
        }
      }
      const special = compose(mentorId, msg, g)

      if (special && special.__ruleOnly) {
        return { mentor: mentor, routedFrom: routedFrom, reply: special.reply, citations: special.citations, actions: special.actions, detached: !!g.detached, groundKind: g.kind, memoryCard: await loadCard(learnerId) }
      }
      if (special && special.__eventList) {
        const listed = await listCapabilityEvents()
        const lines = ['Capability Brain 事件目录（内置 + 导师写入）：']
        if (!listed.length) lines.push('（暂无远程写入；页面仍有内置事件）')
        listed.slice(0, 20).forEach(function (e, i) {
          lines.push((i + 1) + '. ' + (e.title || e.id) + '  [' + (e.id || '') + ']  域=' + ((e.domains || []).join(',') || '—') + (e.source === 'mentor' ? ' · mentor' : ''))
        })
        lines.push('')
        lines.push('写入示例：「写入事件：考研专业课通过 domains=comm,signals」')
        return { mentor: mentor, routedFrom: routedFrom, reply: lines.join('\n'), citations: [{ n: 1, source: 'GET /api/v1/capability/events', quote: 'count=' + listed.length }], actions: ['写入事件：考研专业课通过', '诊断薄弱点'], detached: !!g.detached, groundKind: g.kind, memoryCard: await loadCard(learnerId) }
      }
      if (special && special.__eventWrite) {
        const parsed = parseEventWrite(msg)
        const saved = await upsertCapabilityEvent(parsed, mentorId)
        if (!(saved && saved.ok)) {
          return { mentor: mentor, routedFrom: routedFrom, reply: '事件写入失败：' + ((saved && saved.error) || 'unknown') + '\n可再说：写入事件：考研专业课通过 domains=comm,signals p_hat=0.32', citations: [], actions: ['列出事件', '写入事件：通信核心模块就绪'], detached: !!g.detached, groundKind: g.kind, memoryCard: await loadCard(learnerId) }
        }
        const ev = saved.upserted || {}
        const reply = [
          (saved.replaced ? '已更新' : '已写入') + ' Brain 事件：',
          '· 标题：' + (ev.title || ''),
          '· id：' + (ev.id || ''),
          '· 域：' + ((ev.domains || []).join(' · ') || '—'),
          '· P̂：' + ev.p_hat + (ev.estimate === 'placeholder' ? '（占位）' : '（口述）'),
          '',
          '打开：/capability-brain.html?event=' + encodeURIComponent(ev.id || '') + '&tab=events',
          '说明：已登记目录项；P̂ 为占位/口述，不会按当前 BKT 重算。',
        ].join('\n')
        const card = await loadCard(learnerId)
        applyDelta(card, { note: '写入事件 ' + (ev.title || ev.id) })
        card.updatedAt = Date.now()
        await saveCard(learnerId, card)
        pushThread(learnerId, threadId, 'user', msg)
        pushThread(learnerId, threadId, mentorId, reply)
        return { mentor: mentor, routedFrom: routedFrom, reply: reply, citations: [{ n: 1, source: 'POST /api/v1/capability/events', quote: ev.id || '' }], actions: ['列出事件', '讲这道题'], detached: !!g.detached, groundKind: g.kind, memoryCard: card }
      }

      // 主路径：LLM 按需调工具（先接地后润色）
      let out = null
      if (await llmEnabled()) {
        try {
          out = await runAgent(mentor, msg, g, learnerId, itemId, sse ? function (d) { sse.send('delta', { text: d }) } : null)
        } catch (e) {
          out = null
        }
        if (out) {
          const card = await loadCard(learnerId)
          if (out.evidence && out.evidence.length) applyDelta(card, { note: '已取数 ' + out.evidence.map(function (c) { return c.source }).join(',') })
          card.updatedAt = Date.now()
          await saveCard(learnerId, card)
          pushThread(learnerId, threadId, 'user', msg)
          pushThread(learnerId, threadId, mentorId, out.text)
          return {
            mentor: mentor,
            routedFrom: routedFrom,
            reply: out.text,
            citations: out.evidence.length ? out.evidence : [{ n: 1, source: 'deepseek/' + TUTOR_MODEL, quote: 'stream=' + (out.streamed ? 'true' : 'false') }],
            actions: ['讲这道题', '诊断薄弱点', '列出事件'],
            detached: !!g.detached,
            groundKind: g.kind,
            memoryCard: card,
            llm: { provider: 'deepseek', model: TUTOR_MODEL },
            streamed: !!out.streamed,
          }
        }
      }

      // 规则回落
      const rule = special || { reply: '…', citations: [], actions: [] }
      const card = await loadCard(learnerId)
      applyDelta(card, rule.delta)
      if (rule.delta) { card.updatedAt = Date.now(); await saveCard(learnerId, card) }
      pushThread(learnerId, threadId, 'user', msg)
      pushThread(learnerId, threadId, mentorId, rule.reply)
      return {
        mentor: mentor,
        routedFrom: routedFrom,
        reply: rule.reply,
        citations: rule.citations || [],
        actions: rule.actions || [],
        detached: !!g.detached,
        groundKind: g.kind,
        memoryCard: await loadCard(learnerId),
      }
    }

    const disposers = []
    ctx.effect(() => () => { disposers.forEach((d) => { try { d() } catch (e) {} }) })

    disposers.push(harness.handle('mentor.roster', function () {
      return ROSTER.map(function (m) { return { id: m.id, name: m.name, role: m.role, emoji: m.emoji, tools: m.tools } })
    }))

    disposers.push(harness.handle('mentor.status', async function (args) {
      const lid = (args && args.learner) || 'demo1'
      const live = await tryLive(lid)
      return { connected: !!live, workspaceRoot: workspaceRoot, mentorCount: ROSTER.length, threads: Object.keys(mem.threads).length, practiceBase: PRACTICE_BASE, systemApiBase: SYSTEM_API_BASE, tools: Object.keys(TOOLS) }
    }))

    disposers.push(harness.handle('mentor.card', async function (args) {
      return await loadCard((args && args.learner) || 'demo1')
    }))

    disposers.push(harness.handle('mentor.clearCard', async function (args) {
      const lid = (args && args.learner) || 'demo1'
      const card = { learnerId: lid, weak: [], strengths: [], notes: [], milestones: [], updatedAt: Date.now() }
      await saveCard(lid, card)
      return card
    }))

    disposers.push(harness.handle('mentor.export', async function (args) {
      const lid = (args && args.learner) || 'demo1'
      const card = await loadCard(lid)
      const prefix = safe(lid) + '|'
      const threads = {}
      Object.keys(mem.threads).forEach(function (k) { if (k.indexOf(prefix) === 0) threads[k.slice(prefix.length)] = mem.threads[k] })
      return { exportedAt: new Date().toISOString(), learnerId: lid, card: card, threads: threads, state: loadState(lid) }
    }))

    disposers.push(harness.handle('mentor.chat', async function (args) {
      return await runChat(args || {}, null)
    }))

    function json(res, code, obj) {
      const body = JSON.stringify(obj)
      const bytes = new TextEncoder().encode(body)
      res.writeHead(code, {
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Length': String(bytes.length),
        'Cache-Control': 'no-store',
        'Access-Control-Allow-Origin': '*',
      })
      res.end(body)
    }
    function readBody(req) {
      return new Promise(function (resolve) {
        const parts = []
        let total = 0
        req.on('data', function (c) {
          const u = c instanceof Uint8Array ? c : new Uint8Array(c)
          parts.push(u); total += u.length
        })
        req.on('end', function () {
          const all = new Uint8Array(total)
          let off = 0
          for (let i = 0; i < parts.length; i++) { all.set(parts[i], off); off += parts[i].length }
          try { resolve(new TextDecoder().decode(all)) } catch (e) { resolve('') }
        })
        req.on('error', function () { resolve('') })
      })
    }

    if (webServer) {
      disposers.push(webServer.register({
        kind: 'exact',
        path: '/api/v1/agent/manifest',
        handler: function (req, res) {
          json(res, 200, {
            ok: true,
            manifest: {
              service: 'mentor-team-dsh',
              version: 3,
              readOnly: true,
              llm: { provider: 'deepseek', model: TUTOR_MODEL, tools: true, streaming: true },
              tutor: {
                chat: {
                  status: 'live',
                  request: { learner: 'str', item: 'str|null', push: 'str|null', message: 'str', threadId: 'str|null', mentor: 'str?' },
                  response: { reply: 'str', citations: 'list?', streaming: 'bool?' },
                },
              },
              mentors: ROSTER.map(function (m) { return { id: m.id, name: m.name, role: m.role, tools: m.tools } }),
              tools: Object.keys(TOOLS),
            },
          })
        },
      }))

      disposers.push(webServer.register({
        kind: 'exact',
        path: '/api/v1/tutor/chat',
        handler: async function (req, res) {
          if (req.method === 'OPTIONS') {
            res.writeHead(204, {
              'Access-Control-Allow-Origin': '*',
              'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Practice-Token, X-Learner-Id, Accept',
              'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
            })
            res.end()
            return
          }
          if (req.method !== 'POST') {
            json(res, 405, { ok: false, error: 'method_not_allowed' })
            return
          }
          const bodyText = await readBody(req)
          let body = {}
          try { body = JSON.parse(bodyText || '{}') || {} } catch (e) { body = {} }
          const accept = (req.headers && (req.headers.accept || '')) || ''
          const wantsSse = accept.indexOf('text/event-stream') >= 0 || body.stream === true
          const headerLearner = (req.headers && (req.headers['x-learner-id'] || req.headers['X-Learner-Id'])) || ''
          const learner = body.learner || body.learner_id || body.user_id || headerLearner || ''
          const args = {
            learner: learner || 'demo1',
            message: String(body.message || body.text || '').trim(),
            item: body.item || '',
            push: body.push || '',
            threadId: body.threadId || body.item || 'general',
            mentor: body.mentor || 'auto',
          }

          if (wantsSse) {
            res.writeHead(200, {
              'Content-Type': 'text/event-stream; charset=utf-8',
              'Cache-Control': 'no-cache',
              'Access-Control-Allow-Origin': '*',
              Connection: 'keep-alive',
            })
            const send = function (event, data) {
              try { res.write('event: ' + event + '\ndata: ' + JSON.stringify(data) + '\n\n') } catch (e) {}
            }
            try {
              const out = await runChat(args, { send: send })
              send('done', { reply: out.reply, citations: out.citations || [], mentor: { id: out.mentor.id, name: out.mentor.name, role: out.mentor.role, emoji: out.mentor.emoji }, actions: out.actions || [], detached: !!out.detached, groundKind: out.groundKind, streamed: !!out.streamed })
            } catch (e) {
              send('error', { message: String(e && e.message ? e.message : e) })
            }
            try { res.end() } catch (e) {}
            return
          }

          const out = await runChat(args, null)
          json(res, 200, {
            ok: true,
            mentor: { id: out.mentor.id, name: out.mentor.name, role: out.mentor.role, emoji: out.mentor.emoji },
            reply: out.reply,
            citations: out.citations,
            actions: out.actions,
            streaming: !!out.streamed,
            detached: !!out.detached,
            groundKind: out.groundKind,
            llm: out.llm || null,
          })
        },
      }))
    }
  },
}
