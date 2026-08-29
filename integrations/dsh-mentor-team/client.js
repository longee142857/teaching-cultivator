const CSS = [
  '.mt-fab{position:fixed;right:16px;bottom:16px;z-index:1000}',
  '.mt-fab button{background:#2563eb;color:#fff;border:0;border-radius:999px;padding:10px 16px;font-size:14px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.25)}',
  '.mt-panel{position:fixed;right:16px;bottom:16px;width:380px;max-width:calc(100vw - 32px);max-height:72vh;display:flex;flex-direction:column;background:#ffffff;color:#1f2937;border:1px solid rgba(0,0,0,.14);border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.25);overflow:hidden;font-size:13px;line-height:1.5}',
  '.mt-head{display:flex;align-items:center;gap:8px;padding:10px 12px;font-weight:600;border-bottom:1px solid rgba(0,0,0,.08)}',
  '.mt-badge{font-size:11px;padding:2px 8px;border-radius:999px;background:#dcfce7;color:#166534}',
  '.mt-badge.is-detached{background:#fef3c7;color:#92400e}',
  '.mt-close{margin-left:auto;border:0;background:transparent;cursor:pointer;font-size:16px;color:#6b7280}',
  '.mt-roster{display:flex;flex-wrap:wrap;gap:6px;padding:8px 10px;border-bottom:1px solid rgba(0,0,0,.08)}',
  '.mt-chip{border:1px solid rgba(0,0,0,.18);background:transparent;border-radius:999px;padding:4px 10px;font-size:12px;cursor:pointer;color:#1f2937}',
  '.mt-chip.is-on{background:#2563eb;color:#fff;border-color:#2563eb}',
  '.mt-msgs{flex:1;overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column;gap:8px;min-height:120px}',
  '.mt-msg{max-width:92%}',
  '.mt-msg.is-user{align-self:flex-end}',
  '.mt-msg.is-sys{color:#b91c1c;font-size:12px}',
  '.mt-who{font-size:11px;color:#6b7280;margin-bottom:2px}',
  '.mt-body{white-space:pre-wrap;padding:8px 10px;border-radius:10px;background:rgba(0,0,0,.05)}',
  '.mt-msg.is-user .mt-body{background:#2563eb;color:#fff}',
  '.mt-cites{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px}',
  '.mt-cite{font-size:11px;color:#64748b;background:rgba(0,0,0,.05);padding:1px 6px;border-radius:4px;cursor:help}',
  '.mt-acts{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px}',
  '.mt-act{font-size:12px;border:1px solid #2563eb;color:#2563eb;background:transparent;border-radius:6px;padding:3px 8px;cursor:pointer}',
  '.mt-pending{font-size:12px;color:#94a3b8}',
  '.mt-composer{display:flex;gap:8px;padding:8px 10px;border-top:1px solid rgba(0,0,0,.08)}',
  '.mt-composer textarea{flex:1;border:1px solid rgba(0,0,0,.18);border-radius:8px;padding:6px 8px;font-size:13px;resize:none;background:#fff;color:#1f2937}',
  '.mt-send{border:0;background:#2563eb;color:#fff;border-radius:8px;padding:0 14px;cursor:pointer}',
  '.mt-send:disabled{opacity:.5}',
  '.mt-memory{border-top:1px solid rgba(0,0,0,.08);padding:8px 12px;font-size:12px;background:rgba(0,0,0,.03)}',
  '.mt-mem-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;font-weight:600}',
  '.mt-mem-ops{display:flex;gap:8px}',
  '.mt-exp{border:0;background:transparent;color:#2563eb;cursor:pointer;font-size:12px}',
  '.mt-clear{border:0;background:transparent;color:#b91c1c;cursor:pointer;font-size:12px}',
  '.mt-mem-notes{margin-top:4px;color:#64748b}',
].join('\n')

function detectLearner() {
  try {
    const q = new URLSearchParams(window.location.search || '')
    const fromQ = (q.get('learner') || '').trim()
    if (fromQ) return fromQ
  } catch (e) {}
  try {
    const raw = localStorage.getItem('teaching-shell-v2-state')
    if (raw) {
      const s = JSON.parse(raw)
      if (s && s.learner && s.learner !== 'stu_1024') return String(s.learner)
    }
  } catch (e) {}
  return ''
}

return {
  apply(ctx) {
    const slots = ctx.get('slots')
    if (slots === undefined) return
    styles.insert(CSS)

    function Panel() {
      const [open, setOpen] = React.useState(true)
      const [learner] = React.useState(detectLearner)
      const [roster, setRoster] = React.useState([])
      const [mentor, setMentor] = React.useState('auto')
      const [msgs, setMsgs] = React.useState([])
      const [input, setInput] = React.useState('')
      const [pending, setPending] = React.useState(false)
      const [card, setCard] = React.useState(null)
      const [detached, setDetached] = React.useState(false)
      const [conn, setConn] = React.useState('…')

      React.useEffect(function () {
        host.call('mentor.roster').then(function (r) { setRoster(r || []) }).catch(function () {})
        host.call('mentor.card', { learner: learner }).then(function (c) { setCard(c) }).catch(function () {})
        host.call('mentor.status', { learner: learner }).then(function (s) {
          setDetached(!s.connected)
          setConn(s.connected ? ('已连接 · ' + learner) : ('脱机演示 · ' + learner))
        }).catch(function () { setConn('未连接 · ' + learner) })
      }, [learner])

      function call(mentorId, text) {
        if (pending) return
        if (text) setMsgs(function (m) { return m.concat([{ role: 'user', text: text }]) })
        setPending(true)
        let item = null
        let push = null
        try {
          const q = new URLSearchParams(window.location.search || '')
          item = q.get('item')
          push = q.get('push')
        } catch (e) {}
        host.call('mentor.chat', {
          mentor: mentorId,
          learner: learner,
          message: text,
          item: item,
          push: push,
          threadId: item || 'general',
        })
          .then(function (res) {
            setMsgs(function (m) {
              return m.concat([{
                role: res.mentor.id,
                name: res.mentor.name,
                emoji: res.mentor.emoji,
                routedFrom: res.routedFrom,
                text: res.reply,
                citations: res.citations || [],
                actions: res.actions || [],
              }])
            })
            setCard(res.memoryCard)
            setDetached(res.detached)
            setPending(false)
          })
          .catch(function (e) {
            setMsgs(function (m) { return m.concat([{ role: 'sys', text: '调用失败：' + (e && e.message ? e.message : e) }]) })
            setPending(false)
          })
      }

      function send() {
        const t = (input || '').trim()
        if (!t || pending) return
        setInput('')
        call(mentor, t)
      }

      function onKey(e) {
        if (e && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
      }

      function pickM(id) { setMentor(id) }

      function clearCard() {
        host.call('mentor.clearCard', { learner: learner }).then(setCard).catch(function () {})
      }

      function exportMem() {
        host.call('mentor.export', { learner: learner }).then(function (ex) {
          const summary = {
            learnerId: ex.learnerId,
            exportedAt: ex.exportedAt,
            card: ex.card,
            threadCount: Object.keys(ex.threads || {}).length,
          }
          setMsgs(function (m) { return m.concat([{ role: 'sys', text: '📤 记忆导出：' + JSON.stringify(summary) }]) })
        }).catch(function () {})
      }

      if (!open) {
        return React.createElement('div', { className: 'mt-fab', style: { pointerEvents: 'auto' } },
          React.createElement('button', { onClick: function () { setOpen(true) }, title: '打开导师团' }, '🎓 导师团'),
        )
      }

      const header = React.createElement('div', { className: 'mt-head' },
        React.createElement('span', null, '🎓 导师团'),
        React.createElement('span', { className: 'mt-badge' + (detached ? ' is-detached' : '') }, conn),
        React.createElement('button', { className: 'mt-close', onClick: function () { setOpen(false) }, title: '收起' }, '—'),
      )

      const rosterEl = React.createElement('div', { className: 'mt-roster' },
        (roster || []).map(function (m) {
          return React.createElement('button', {
            key: m.id,
            className: 'mt-chip' + (m.id === mentor ? ' is-on' : ''),
            onClick: function () { pickM(m.id) },
            title: m.role,
          }, m.emoji + ' ' + m.name)
        }),
      )

      const msgNodes = msgs.map(function (m, i) {
        if (m.role === 'user') {
          return React.createElement('div', { key: i, className: 'mt-msg is-user' },
            React.createElement('div', { className: 'mt-who' }, '你'),
            React.createElement('div', { className: 'mt-body' }, m.text),
          )
        }
        if (m.role === 'sys') {
          return React.createElement('div', { key: i, className: 'mt-msg is-sys' }, m.text)
        }
        const cites = (m.citations || []).map(function (c) {
          return React.createElement('span', { key: c.n, className: 'mt-cite', title: c.quote }, '[' + c.n + '] ' + c.source)
        })
        const acts = (m.actions || []).map(function (a, j) {
          return React.createElement('button', { key: j, className: 'mt-act', onClick: function () { call('auto', a) } }, a)
        })
        return React.createElement('div', { key: i, className: 'mt-msg' },
          React.createElement('div', { className: 'mt-who' },
            (m.routedFrom === 'auto' ? '团长→' : '') + (m.emoji || '') + ' ' + (m.name || '导师')),
          React.createElement('div', { className: 'mt-body' }, m.text),
          cites.length ? React.createElement('div', { className: 'mt-cites' }, cites) : null,
          acts.length ? React.createElement('div', { className: 'mt-acts' }, acts) : null,
        )
      })
      if (pending) msgNodes.push(React.createElement('div', { key: 'pending', className: 'mt-pending' }, '导师思考中…'))
      const msgsEl = React.createElement('div', { className: 'mt-msgs' }, msgNodes)

      const composer = React.createElement('div', { className: 'mt-composer' },
        React.createElement('textarea', {
          value: input,
          onChange: function (e) { setInput(e.target.value) },
          onKeyDown: onKey,
          placeholder: '问导师…（Enter 发送，Shift+Enter 换行）',
          rows: 2,
        }),
        React.createElement('button', { className: 'mt-send', onClick: send, disabled: pending }, '发送'),
      )

      const memoryEl = React.createElement('div', { className: 'mt-memory' },
        React.createElement('div', { className: 'mt-mem-head' },
          React.createElement('span', null, '🧠 导师记得你'),
          React.createElement('div', { className: 'mt-mem-ops' },
            React.createElement('button', { className: 'mt-exp', onClick: exportMem }, '导出'),
            React.createElement('button', { className: 'mt-clear', onClick: clearCard }, '清空'),
          ),
        ),
        (card && card.weak && card.weak.length)
          ? React.createElement('div', { className: 'mt-mem-body' },
              React.createElement('div', null, '薄弱：' + card.weak.map(function (w) { return w.kp + '(' + w.p + ')' }).join('、')),
              (card.notes && card.notes.length) ? React.createElement('div', { className: 'mt-mem-notes' }, '最近：' + card.notes.slice(-2).join('；')) : null,
            )
          : React.createElement('div', { className: 'mt-mem-body' }, '（暂无长期记忆，聊几句后会自动沉淀）'),
      )

      return React.createElement('div', { className: 'mt-panel', style: { pointerEvents: 'auto' } },
        header, rosterEl, msgsEl, composer, memoryEl,
      )
    }

    slots.inject('shell.overlay', function () {
      return slots.register({ name: 'shell.overlay', id: 'mentor-team' }, function () {
        return React.createElement(Panel)
      })
    })
  },
}
