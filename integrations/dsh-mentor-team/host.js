return {
  apply(ctx) {
    const fs = ctx.get('fs')
    const web = ctx.get('web')
    const webServer = ctx.get('webServer')
    const sandboxPolicy = ctx.get('sandboxPolicy')
    const workspaceRoot = (sandboxPolicy && typeof sandboxPolicy.workspaceRoot === 'string')
      ? sandboxPolicy.workspaceRoot
      : ''

    // 只保留练习台能用上的角色；tools 仅标注实际会打到的只读面
    const ROSTER = [
      { id: 'auto', name: '团长', role: '自动分派', emoji: '🧭', tools: [] },
      { id: 'lecturer', name: '讲师', role: '讲题 · Socratic · 记忆', emoji: '📖', tools: ['practice_bootstrap', 'practice_get_item'] },
      { id: 'assistant', name: '学习助教', role: '诊断 · 规划 · 事件写入', emoji: '🧑‍🏫', tools: ['practice_bootstrap', 'get_learner_params', 'capability_events'] },
    ]

    const PRACTICE_BASE = (typeof process !== 'undefined' && process.env && process.env.PRACTICE_API_BASE)
      ? String(process.env.PRACTICE_API_BASE).replace(/\/$/, '')
      : 'http://127.0.0.1:8768'

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
      { id: 'i1', pushId: 1, title: '极限 · 夹逼定理', kp: '极限 · 夹逼定理', subject: '高等数学', stem: '已知 1/n ≤ a_n ≤ (n+1)/n²，求 lim a_n。', explain: '两端夹逼同趋于 0。', solutionSteps: ['由 1/n ≤ a_n ≤ (n+1)/n²', '两端 n→∞ 均趋于 0，故 a_n → 0'] },
      { id: 'i2', pushId: 2, title: '信号与系统 · 卷积', kp: '卷积', subject: '通信', stem: '求输出 y(t)=x(t)*h(t) 的表达式要点。', explain: '输出为卷积，先定支撑再定限。', solutionSteps: ['输出为输入与冲激响应的卷积', '先画支撑再定积分限'] },
      { id: 'i3', pushId: 3, title: '导数 · 隐函数求导', kp: '导数 · 隐函数求导', subject: '高等数学', stem: 'x²+xy+y²=3，求 (1,1) 处 dy/dx。', explain: '隐函数求导后代入点。', solutionSteps: ['两边对 x 求导得 y′=−(2x+y)/(x+2y)', '点 (1,1) 处为 −1'] },
    ]
    const DEMO_KB = {
      '极限 · 夹逼定理': { def: '若 g(n) ≤ a_n ≤ h(n) 且 g、h 同趋于 L，则 a_n → L。关键：两端必须收敛到同一个值。', source: 'syllabus_math.json · 极限' },
      '导数 · 隐函数求导': { def: '对 F(x,y)=0 两边关于 x 求导，再解出 dy/dx（注意 y 是 x 的函数）。', source: 'syllabus_math.json · 微分' },
      '积分 · 换元': { def: '∫ f(g(x))g′(x)dx = F(g(x)) + C（凑微分/换元，注意换限）。', source: 'syllabus_math.json · 积分' },
      '卷积': { def: 'y(t)=∫ x(τ)h(t−τ)dτ；支撑区间决定积分上下限。', source: 'syllabus_comm.json · 卷积' },
    }

    function safe(s) { return String(s || '').replace(/[^\w\-.]/g, '_').slice(0, 64) || 'anon' }

    const mem = { cards: {}, threads: {} }
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

    async function fetchJson(url, headers) {
      if (!web) return null
      try {
        const r = await web.fetch({ url: url, headers: headers || {} })
        if (!(r && r.statusCode >= 200 && r.statusCode < 300 && r.body && typeof r.body.content === 'string')) return null
        return JSON.parse(r.body.content)
      } catch (e) {
        return null
      }
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

    async function enrichItem(learnerId, itemId, pushId, headers) {
      if (!itemId && !pushId) return null
      const q = []
      if (learnerId) q.push('learner=' + encodeURIComponent(learnerId))
      if (itemId) q.push('item=' + encodeURIComponent(itemId))
      if (pushId) q.push('push=' + encodeURIComponent(pushId))
      const data = await fetchJson(PRACTICE_BASE + '/api/v1/practice/item?' + q.join('&'), headers)
      if (data && data.ok && data.item) return mapItem(data.item)
      return null
    }

    async function tryLive(learnerId) {
      const lid = learnerId || 'demo1'
      const headers = { 'X-Learner-Id': lid }
      const boot = await fetchJson(PRACTICE_BASE + '/api/v1/practice/bootstrap?learner=' + encodeURIComponent(lid), headers)
      if (!(boot && boot.ok)) return null

      const items = (boot.items || []).map(mapItem).filter(Boolean)
      let mastery = mapMastery((boot.capability && boot.capability.masteryWeak) || [])
      let eta = mapEta((boot.capability && boot.capability.eta) || {})
      let assumptions = []

      const params = await fetchJson(PRACTICE_BASE + '/api/v1/practice/params?learner=' + encodeURIComponent(lid), headers)
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

    function compose(mentorId, message, g, opts) {
      const msg = String(message || '').trim()
      const learner = g.learner || DEMO_LEARNER
      const preferred = (opts && (opts.item || opts.itemId)) || ''
      let item = pickItem(g, msg, preferred)
      if (opts && opts.forcedItem) item = opts.forcedItem
      const weak = weakList(learner)
      let reply = ''
      let citations = []
      let actions = []
      let delta = null

      if (/批改|判分|对错|grade|判题|出题|命题|generate|变式|新题|再出一题/.test(msg)) {
        return {
          reply: '这块由教学运行时负责：批改请到练习台提交作答（教学系统会批改并回写 BKT/η）；命题/变式由教学系统的定时或人工确认流程完成。我这边只做讲解、诊断与规划建议，不直接批改、不出题。\n\n例外：Capability Brain 的「事件」可由导师团写入（说「写入事件：考研专业课通过」）。',
          citations: [{ n: 1, source: '边界约定', quote: '批改/命题硬闸在 teaching；事件目录可写' }],
          actions: ['写入事件：考研专业课通过', '讲这道题', '诊断薄弱点'],
          delta: null,
        }
      }

      // 导师团写入 Brain 事件（允许写 capability catalog，不写题库）
      if (/写入事件|新增事件|创建事件|登记事件|添加事件/.test(msg)) {
        return { __eventWrite: true, message: msg }
      }

      if (/列出事件|有哪些事件|事件目录|事件列表/.test(msg)) {
        return { __eventList: true, message: msg }
      }

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
          if (weak.length) {
            lines.push('')
            lines.push('建议顺序：先做最弱的「' + weak[0].kp + '」。')
          } else if (g.weakHint) {
            lines.push('')
            lines.push('薄弱提示：' + g.weakHint)
          }
          lines.push('⚠️ 以上是建议；实际推送/批改由教学运行时决定。')
          reply = lines.join('\n')
          citations = items.map(function (it, i) { return { n: i + 1, source: '今日推送 slot ' + (i + 1), quote: (it.title || '') + ' · ' + (it.kp || '') } })
          actions = ['诊断薄弱点', '讲这道题']
          delta = { note: '规划建议（只读）' }
        } else {
          const lines = ['你的薄弱知识点（BKT p_mastery 最低三项）：']
          if (!weak.length) {
            lines.push('（暂无 mastery 明细；' + (g.weakHint ? ('提示：' + g.weakHint) : '可先做今日题后再诊') + '）')
          } else {
            weak.forEach(function (w, i) { lines.push((i + 1) + '. ' + w.kp + ' — p=' + w.p) })
          }
          const eta = (learner.eta || []).slice().sort(function (a, b) { return a.eta - b.eta })
          if (eta.length) {
            lines.push('')
            lines.push('域潜特质 η（仅相对序）：')
            eta.forEach(function (e) { lines.push('· ' + e.domain + ' η=' + e.eta + (e.n ? '（观测 ' + e.n + ' 题）' : '（无观测）')) })
          }
          lines.push('')
          lines.push('⚠️ 诚实边界：' + ((learner.assumptions && learner.assumptions[0]) || 'BKT mastery 不直接作为事件成功概率'))
          if (weak.length) lines.push('建议：优先补齐最弱 KP，再轮转其它域。（此为建议，不写入任何权重/快照。）')
          reply = lines.join('\n')
          citations = weak.map(function (w, i) { return { n: i + 1, source: 'LearnerParams.mastery', quote: w.kp + ' p_mastery=' + w.p } })
          ;(learner.assumptions || []).forEach(function (s) { citations.push({ n: citations.length + 1, source: 'ParamAssumptions', quote: s }) })
          actions = ['今日计划', '讲这道题']
          delta = weak.length ? { weak: weak.map(function (w) { return { kp: w.kp, p: w.p } }) } : null
        }
      } else {
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
          reply = lines.join('\n')
          citations = [{ n: 1, source: '题目 ' + (item.id || '') + ' · ' + (item.kp || ''), quote: item.stem || '' }]
          if (entry) citations.push({ n: 2, source: entry.source, quote: entry.def })
          actions = wantFull ? ['给提示', '诊断薄弱点'] : ['给完整解', '诊断薄弱点']
          delta = { milestone: item.kp }
        } else {
          reply = '请先告诉我你想讨论哪道题/哪个知识点。当前为' + (g.detached ? '脱机演示' : '已连接教学系统') + '模式。'
        }
      }

      return { reply: reply, citations: citations, actions: actions, delta: delta }
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

    function parseEventWrite(message) {
      const msg = String(message || '')
      let title = ''
      const m1 = msg.match(/(?:写入|新增|创建|登记|添加)事件[：:\s]*([^\n]+)/)
      if (m1) title = m1[1].trim()
      // strip trailing kv pairs from title line
      title = title.replace(/\b(id|domains|domain|p_hat|p)\s*=\s*\S+/gi, '').trim()
      title = title.replace(/[，,]\s*$/, '').trim()
      const idM = msg.match(/\bid\s*=\s*([A-Za-z0-9_\-]+)/i)
      const domM = msg.match(/\bdomains?\s*=\s*([A-Za-z0-9_,\-]+)/i)
      const pM = msg.match(/\bp_hat\s*=\s*([0-9.]+)/i) || msg.match(/\bp\s*=\s*([0-9.]+)/i)
      let domains = []
      if (domM) domains = domM[1].split(/[,，]/).map(function (s) { return s.trim() }).filter(Boolean)
      if (!domains.length && /专业课|通信|OFDM|奈奎斯特|ISI|调制|信息论|信道/.test(msg + title)) {
        domains = ['comm', 'signals']
      }
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
      if (!web) return { ok: false, error: 'web_unavailable' }
      try {
        const body = Object.assign({}, payload || {}, { mentor: mentorId || 'assistant' })
        const r = await web.fetch({
          url: PRACTICE_BASE + '/api/v1/capability/events',
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!(r && r.body && typeof r.body.content === 'string')) return { ok: false, error: 'empty_response' }
        try { return JSON.parse(r.body.content) } catch (e) { return { ok: false, error: 'bad_json' } }
      } catch (e) {
        return { ok: false, error: String(e && e.message ? e.message : e) }
      }
    }

    async function runChat(args) {
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
        if (!forcedItem) forcedItem = await enrichItem(learnerId, itemId, pushId, { 'X-Learner-Id': learnerId })
        if (forcedItem) {
          const exists = (g.items || []).some(function (it) { return it.id === forcedItem.id })
          if (!exists) g.items = [forcedItem].concat(g.items || [])
        }
      }
      const out = compose(mentorId, msg, g, { item: itemId, forcedItem: forcedItem })
      if (out && out.__eventList) {
        const listed = await listCapabilityEvents()
        const lines = ['Capability Brain 事件目录（内置 + 导师写入）：']
        if (!listed.length) lines.push('（暂无远程写入；页面仍有内置事件）')
        listed.slice(0, 20).forEach(function (e, i) {
          lines.push((i + 1) + '. ' + (e.title || e.id) + '  [' + (e.id || '') + ']  域=' + ((e.domains || []).join(',') || '—') + (e.source === 'mentor' ? ' · mentor' : ''))
        })
        lines.push('')
        lines.push('写入示例：「写入事件：考研专业课通过 domains=comm,signals」')
        return {
          ok: true,
          mentor: { id: mentor.id, name: mentor.name, role: mentor.role, emoji: mentor.emoji },
          routedFrom: routedFrom,
          reply: lines.join('\n'),
          citations: [{ n: 1, source: 'GET /api/v1/capability/events', quote: 'count=' + listed.length }],
          actions: ['写入事件：考研专业课通过', '诊断薄弱点'],
          streaming: false,
          detached: !!g.detached,
          groundKind: g.kind,
          memoryCard: await loadCard(learnerId),
        }
      }
      if (out && out.__eventWrite) {
        const parsed = parseEventWrite(msg)
        const saved = await upsertCapabilityEvent(parsed, mentorId)
        if (!(saved && saved.ok)) {
          return {
            ok: true,
            mentor: { id: mentor.id, name: mentor.name, role: mentor.role, emoji: mentor.emoji },
            routedFrom: routedFrom,
            reply: '事件写入失败：' + ((saved && saved.error) || 'unknown') + '\n可再说：写入事件：考研专业课通过 domains=comm,signals p_hat=0.32',
            citations: [],
            actions: ['列出事件', '写入事件：通信核心模块就绪'],
            streaming: false,
            detached: !!g.detached,
            groundKind: g.kind,
            memoryCard: await loadCard(learnerId),
          }
        }
        const ev = saved.upserted || {}
        const reply = [
          (saved.replaced ? '已更新' : '已写入') + ' Brain 事件：',
          '· 标题：' + (ev.title || ''),
          '· id：' + (ev.id || ''),
          '· 域：' + ((ev.domains || []).join(' · ') || '—'),
          '· P̂(mock)：' + ev.p_hat,
          '',
          '打开：/capability-brain.html?event=' + encodeURIComponent(ev.id || ''),
          '说明：可写事件目录；仍不能批改/出题。',
        ].join('\n')
        const card = await loadCard(learnerId)
        applyDelta(card, { note: '写入事件 ' + (ev.title || ev.id) })
        card.updatedAt = Date.now()
        await saveCard(learnerId, card)
        pushThread(learnerId, threadId, 'user', msg)
        pushThread(learnerId, threadId, mentorId, reply)
        return {
          ok: true,
          mentor: { id: mentor.id, name: mentor.name, role: mentor.role, emoji: mentor.emoji },
          routedFrom: routedFrom,
          reply: reply,
          citations: [{ n: 1, source: 'POST /api/v1/capability/events', quote: ev.id || '' }],
          actions: ['列出事件', '讲这道题'],
          streaming: false,
          detached: !!g.detached,
          groundKind: g.kind,
          memoryCard: card,
        }
      }
      const card = await loadCard(learnerId)
      applyDelta(card, out.delta)
      if (out.delta) { card.updatedAt = Date.now(); await saveCard(learnerId, card) }
      pushThread(learnerId, threadId, 'user', msg)
      pushThread(learnerId, threadId, mentorId, out.reply)
      return {
        ok: true,
        mentor: { id: mentor.id, name: mentor.name, role: mentor.role, emoji: mentor.emoji },
        routedFrom: routedFrom,
        reply: out.reply,
        citations: out.citations,
        actions: out.actions,
        streaming: false,
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
      return { connected: !!live, workspaceRoot: workspaceRoot, mentorCount: ROSTER.length, threads: Object.keys(mem.threads).length, practiceBase: PRACTICE_BASE }
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
      return { exportedAt: new Date().toISOString(), learnerId: lid, card: card, threads: threads }
    }))

    disposers.push(harness.handle('mentor.chat', async function (args) {
      return await runChat(args || {})
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
              version: 2,
              readOnly: true,
              tutor: {
                chat: {
                  status: 'live',
                  request: { learner: 'str', item: 'str|null', push: 'str|null', message: 'str', threadId: 'str|null', mentor: 'str?' },
                  response: { reply: 'str', citations: 'list?', streaming: 'bool?' },
                },
              },
              mentors: ROSTER.map(function (m) { return { id: m.id, name: m.name, role: m.role } }),
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
              'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Practice-Token, X-Learner-Id',
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
          const headerLearner = (req.headers && (req.headers['x-learner-id'] || req.headers['X-Learner-Id'])) || ''
          const learner = body.learner || body.learner_id || body.user_id || headerLearner || ''
          const message = String(body.message || body.text || '').trim()
          const item = body.item || ''
          const push = body.push || ''
          const threadId = body.threadId || item || 'general'
          const out = await runChat({
            learner: learner || 'demo1',
            message: message,
            item: item,
            push: push,
            threadId: threadId,
            mentor: body.mentor || 'auto',
          })
          json(res, 200, {
            ok: true,
            mentor: { id: out.mentor.id, name: out.mentor.name },
            reply: out.reply,
            citations: out.citations,
            streaming: false,
            detached: !!out.detached,
          })
        },
      }))
    }
  },
}
