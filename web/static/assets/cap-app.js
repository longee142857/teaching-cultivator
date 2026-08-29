// app.js —— 能力概率 · Brain Prediction Console
// 手划翻页：封面 + 四叶注记；脑叶点选直达
const MOCK = window.MOCK;
const GATE_LABEL = window.GATE_LABEL;

const REGIONS = {
  frontal:   { panel:'card-eta',         domain:'calc',   cn:'额叶', en:'FRONTAL', page:0 },
  parietal:  { panel:'card-prob',        domain:null,     cn:'顶叶', en:'PARIETAL', page:1 },
  temporal:  { panel:'card-paths',       domain:'linalg', cn:'颞叶', en:'TEMPORAL', page:2 },
  occipital: { panel:'card-bottlenecks', domain:'prob',   cn:'枕叶', en:'OCCIPITAL', page:3 }
};
const DOMAIN_TO_REGION = { calc:'frontal', linalg:'temporal', prob:'occipital' };
const REGION_ORDER = ['frontal','parietal','temporal','occipital'];
const PAGE_MIN = -1; // 封面
const PAGE_MAX = 3;
const SWIPE_THRESHOLD = 56;

const $ = id => document.getElementById(id);
const stage = $('stage');
const leaders = $('leaders');
const boot = $('boot');
const folio = $('folio');

const f3 = v => (v>0 ? '+' : '−') + Math.abs(v).toFixed(3);
const pct = v => (v*100).toFixed(1) + '%';

let brain = null;
let anchorScreens = {};
let cardAnchors = {};
let pageIndex = PAGE_MIN; // -1 封面
let flipDir = 0; // -1 向左翻出 / 1 向右翻出
let prevPageIndex = PAGE_MIN;

function dismissBoot(){
  if (window.__capBootTimer) {
    clearTimeout(window.__capBootTimer);
    window.__capBootTimer = null;
  }
  if (!boot || !boot.isConnected) return;
  boot.classList.add('done');
  setTimeout(() => { if (boot.isConnected) boot.remove(); }, 600);
}

function renderEvent(){
  const sel = $('event-select');
  if (sel) {
    const cur = MOCK.event_id;
    sel.innerHTML = '';
    (window.EVENTS || []).forEach(function (ev) {
      const opt = document.createElement('option');
      opt.value = ev.id;
      const tag = (ev.domains || []).indexOf('comm') >= 0 || (ev.domains || []).indexOf('signals') >= 0
        ? '〔通〕' : ((ev.domains || []).indexOf('calc') >= 0 ? '〔数〕' : '');
      opt.textContent = tag + (ev.title || ev.id);
      sel.appendChild(opt);
    });
    if (cur) sel.value = cur;
  }
  $('eventTitle').textContent = MOCK.event_title;
  const blurb = $('eventBlurb');
  if (blurb) {
    const domains = (MOCK.event_domains || []).map(function (d) {
      return (window.DOMAIN_LABEL && window.DOMAIN_LABEL[d]) || d;
    }).join(' · ');
    blurb.textContent = [MOCK.event_blurb || '', domains ? ('域: ' + domains) : ''].filter(Boolean).join(' · ');
  }
  const learnerEl = $('learnerChip');
  if (learnerEl) {
    learnerEl.textContent = 'learner=' + (MOCK.learner_id || '—') +
      ' · LearnerParams=BKT(L2)+η · ' + (MOCK.source && String(MOCK.source).indexOf('VPS') >= 0 ? 'VPS live' : '本地 mock');
  }
}

function renderEta(){
  const labels = window.DOMAIN_LABEL || { calc:'微积分', linalg:'线代', prob:'概率', comm:'通信' };
  const preferred = ['calc', 'linalg', 'prob', 'comm', 'signals'];
  const keys = Object.keys(MOCK.eta_hat || {});
  keys.sort(function (a, b) {
    const ia = preferred.indexOf(a), ib = preferred.indexOf(b);
    if (ia < 0 && ib < 0) return a.localeCompare(b);
    if (ia < 0) return 1;
    if (ib < 0) return -1;
    return ia - ib;
  });
  const rows = keys.map(function (key) {
    return { key: key, label: labels[key] || key };
  });
  if (!rows.length) {
    rows.push({ key: 'calc', label: '微积分' }, { key: 'linalg', label: '线代' }, { key: 'prob', label: '概率' });
  }
  const maxAbs = Math.max(...rows.map(r => Math.abs(Number(MOCK.eta_hat[r.key]) || 0)), 0.001);
  const body = $('eta-body');
  body.innerHTML = rows.map(r => {
    const v = Number(MOCK.eta_hat[r.key]) || 0;
    const w = (Math.abs(v)/maxAbs*50).toFixed(2);
    const pos = v >= 0;
    return `<div class="eta-row" data-domain="${r.key}">
      <div class="eta-head">
        <span class="eta-name">${r.label}</span><span class="eta-en">${r.key}</span>
        <span class="eta-val ${pos?'pos':'neg'}">${f3(v)}</span>
      </div>
      <div class="eta-track">
        <div class="eta-axis"></div>
        <div class="eta-bar ${pos?'pos':'neg'}" style="--w:${w}%"></div>
      </div>
    </div>`;
  }).join('');
  body.insertAdjacentHTML('beforeend',
    `<div class="eta-cap">零线 = 无净效应 · <b>正值</b>助成事 · <b>负值</b>示阻<br>${MOCK.eta_note || ''}</div>`);

  const bkt = MOCK.bkt_l2 || [];
  if (bkt.length) {
    const bktHtml = bkt.map(row => {
      const pm = Math.round((row.p_mastery || 0) * 100);
      const domainBit = row.domain ? (' · →' + row.domain) : ' · 未映射域';
      return `<div class="bkt-row">
        <div class="bkt-head"><span class="bkt-kp">${row.kp}</span><span class="bkt-slot">${row.slot}</span></div>
        <div class="bkt-track"><i style="--w:${pm}%"></i></div>
        <div class="bkt-meta">p_mastery ${Number(row.p_mastery).toFixed(2)}${domainBit}</div>
      </div>`;
    }).join('');
    body.insertAdjacentHTML('beforeend',
      `<div class="bkt-block">
        <div class="bkt-title mono">TEACHING · BKT L2 · ${bkt.length} KP</div>
        <div class="bkt-cap">练习选题用 · <b>≠</b> 事件 P̂ · 按掌握度升序</div>
        ${bktHtml}
      </div>`);
  }

  body.querySelectorAll('.eta-row').forEach(row => {
    row.addEventListener('pointerenter', () => {
      if (pageIndex !== 0) return;
      row.classList.add('is-hl');
      const region = DOMAIN_TO_REGION[row.dataset.domain];
      if (brain && region) brain.setRegionTint(region);
    });
    row.addEventListener('pointerleave', () => {
      row.classList.remove('is-hl');
      applyActive();
    });
  });
}

function renderProb(){
  const p = MOCK.p_hat, ci = MOCK.ci;
  const MIN = 0.20, MAX = 0.50;
  const X = v => 26 + (v-MIN)/(MAX-MIN)*(276-26);
  let ticks = '';
  for (let v = 0.20; v <= 0.5001; v += 0.05){
    const x = X(v).toFixed(1);
    ticks += `<line class="ci-tick" x1="${x}" y1="46" x2="${x}" y2="50"/>
      <text class="ci-ticklabel" x="${x}" y="61" text-anchor="middle">${v.toFixed(2)}</text>`;
  }
  const x1 = X(ci[0]).toFixed(1), x2 = X(ci[1]).toFixed(1), xp = X(p).toFixed(1);
  const width = (ci[1]-ci[0]).toFixed(3);
  const svg = `<svg viewBox="0 0 302 68" role="img" aria-label="Wilson 95% 置信区间">
    <line class="ci-tick" x1="26" y1="46" x2="276" y2="46"/>
    ${ticks}
    <line class="ci-line" x1="${x1}" y1="34" x2="${x2}" y2="34"/>
    <line class="ci-cap" x1="${x1}" y1="29" x2="${x1}" y2="39"/>
    <line class="ci-cap" x1="${x2}" y1="29" x2="${x2}" y2="39"/>
    <circle class="ci-dot" cx="${xp}" cy="34" r="3.4"/>
    <text class="ci-lbl" x="${x1}" y="24" text-anchor="middle">${ci[0].toFixed(3)}</text>
    <text class="ci-lbl" x="${x2}" y="24" text-anchor="middle">${ci[1].toFixed(3)}</text>
  </svg>`;
  $('prob-body').innerHTML = `
    <div class="prob-num"><span class="prob-hat">P̂</span>
      <span class="num">${p.toFixed(3)}<em>&thinsp;${(p*100).toFixed(1)}%</em></span></div>
    <div class="prob-meta">Wilson <b>95%</b> CI · 区间宽 <b class="n">${width}</b> · n=${MOCK.n_paths} 条路径</div>
    <div class="ci-plot">${svg}</div>`;
}

function renderPaths(){
  const maxF = Math.max(...MOCK.top_paths.map(t => t.freq));
  const rows = MOCK.top_paths.map(t => {
    const gates = t.passed_gates.map(g => `<span class="gate ok">${GATE_LABEL[g]||g}</span>`)
      .concat(t.failed_gates.map(g => `<span class="gate bad">${GATE_LABEL[g]||g}</span>`));
    const w = (t.freq/maxF*100).toFixed(1);
    return `<div class="path-row">
      <div class="path-gates">${gates.join('<span class="gate-sep">→</span>')}</div>
      <div class="path-meta"><span class="path-freq">${t.freq.toFixed(3)}</span><div class="freq-track"><i style="--w:${w}%"></i></div></div>
    </div>`;
  }).join('');
  const shown = MOCK.top_paths.reduce((a,t) => a+t.freq, 0);
  const rest = (1-shown).toFixed(3);
  const restN = MOCK.n_paths - MOCK.top_paths.length;
  $('paths-body').innerHTML = rows +
    `<div class="path-other">其余 <b>${restN}</b> 条路径合计频率 <b>${rest}</b></div>`;
}

function renderBottlenecks(){
  const maxS = Math.max(...MOCK.bottlenecks.map(b => b.share));
  const rows = MOCK.bottlenecks.map((b, i) => {
    const w = (b.share/maxS*100).toFixed(1);
    return `<div class="bn-row">
      <span class="bn-rank">${String(i+1).padStart(2,'0')}</span>
      <div class="bn-main">
        <div class="bn-name">${GATE_LABEL[b.node]||b.node}<span class="bn-node">${b.node}</span></div>
        <div class="bn-bar"><i style="--w:${w}%"></i></div>
      </div>
      <div class="bn-num"><b>${pct(b.share)}</b><span class="bn-when">失败 ${b.when_fail} 例</span></div>
    </div>`;
  }).join('');
  $('bn-body').innerHTML = rows;
}

function renderAssumptions(){
  $('assume-count').textContent = MOCK.assumptions.length;
  $('assume-list').innerHTML = MOCK.assumptions
    .map((a, i) => `<li data-n="${String(i+1).padStart(2,'0')}">${a}</li>`).join('');
  const btn = $('assume-toggle'), panel = $('assumptions');
  btn.addEventListener('click', () => {
    const open = panel.hidden;
    panel.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
  });
}

function regionForPage(idx){
  if (idx < 0) return null;
  return REGION_ORDER[idx] || null;
}

function goPage(next, dir){
  const clamped = Math.max(PAGE_MIN, Math.min(PAGE_MAX, next));
  if (clamped === pageIndex) {
    applyActive();
    return;
  }
  flipDir = dir != null ? dir : (clamped > pageIndex ? -1 : 1);
  prevPageIndex = pageIndex;
  pageIndex = clamped;
  applyActive();
}

function stepPage(delta){
  goPage(pageIndex + delta, delta < 0 ? -1 : 1);
}

function applyActive(){
  const region = regionForPage(pageIndex);
  const domain = region ? REGIONS[region].domain : null;
  const isCover = pageIndex < 0;

  if (brain) brain.setRegionTint(region);
  stage.classList.toggle('is-cover', isCover);
  stage.classList.toggle('is-reading', !isCover);
  if (folio) folio.classList.toggle('is-empty', isCover);

  const hint = $('stage-hint');
  if (hint) {
    if (isCover) {
      hint.hidden = false;
      hint.innerHTML = '<span class="hint-key">SWIPE</span> 左右滑动翻页 · 点脑叶可直达';
    } else {
      hint.hidden = true;
    }
  }

  document.querySelectorAll('.card.page').forEach(card => {
    const idx = +card.dataset.page;
    const open = idx === pageIndex;
    const exiting = idx === prevPageIndex && prevPageIndex !== pageIndex && prevPageIndex >= 0;
    card.classList.remove('is-open', 'is-hl', 'is-exit-left', 'is-exit-right', 'is-enter-left', 'is-enter-right');
    if (open) {
      // 先放到入场位，再在下一帧翻到打开态（点击与手划都能看见翻页）
      if (prevPageIndex !== pageIndex) {
        card.classList.add(flipDir < 0 ? 'is-enter-right' : 'is-enter-left');
      }
      card.classList.add('is-open', 'is-hl');
      card.setAttribute('aria-hidden', 'false');
      if (prevPageIndex !== pageIndex) {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            if (+card.dataset.page !== pageIndex) return;
            card.classList.remove('is-enter-left', 'is-enter-right');
          });
        });
      }
    } else if (exiting) {
      card.classList.add(flipDir < 0 ? 'is-exit-left' : 'is-exit-right');
      window.setTimeout(() => {
        if (+card.dataset.page !== pageIndex) {
          card.classList.remove('is-exit-left', 'is-exit-right');
        }
      }, 480);
      card.setAttribute('aria-hidden', 'true');
    } else {
      card.setAttribute('aria-hidden', 'true');
    }
  });

  document.querySelectorAll('.eta-row').forEach(row => {
    row.classList.toggle('is-hl', domain && row.dataset.domain === domain);
  });

  document.querySelectorAll('#leaders .leader, #leaders .leader-dot').forEach(el => {
    const r = el.dataset.region;
    const on = !!(region && r === region);
    el.classList.toggle('is-on', on);
    el.classList.toggle('is-active', on);
  });

  // chrome
  const prevBtn = $('page-prev');
  const nextBtn = $('page-next');
  if (prevBtn) prevBtn.disabled = pageIndex <= PAGE_MIN;
  if (nextBtn) nextBtn.disabled = pageIndex >= PAGE_MAX;

  document.querySelectorAll('.page-dot').forEach(dot => {
    const on = +dot.dataset.page === pageIndex;
    dot.classList.toggle('is-on', on);
    dot.setAttribute('aria-selected', String(on));
  });

  const indexEl = $('page-index');
  if (indexEl) {
    indexEl.textContent = isCover
      ? '封面'
      : String(pageIndex + 1).padStart(2, '0') + ' / 04';
  }

  requestAnimationFrame(() => {
    computeCardAnchors();
    updateLeaders();
  });
}

function cardAttachPoint(rel){
  // 书页固定在底部/右侧，引导线接到卡片左上内侧
  return { x: rel.left + 18, y: rel.top + Math.min(36, rel.height * 0.2) };
}
function computeCardAnchors(){
  const sr = stage.getBoundingClientRect();
  REGION_ORDER.forEach(region => {
    const cardEl = $(REGIONS[region].panel);
    if (!cardEl) return;
    const r = cardEl.getBoundingClientRect();
    cardAnchors[region] = cardAttachPoint(
      { left: r.left-sr.left, top: r.top-sr.top, width: r.width, height: r.height });
  });
}
function buildLeaders(){
  leaders.setAttribute('viewBox', `0 0 ${stage.clientWidth} ${stage.clientHeight}`);
  leaders.innerHTML = REGION_ORDER.map(region => `
    <line class="leader" data-region="${region}" x1="0" y1="0" x2="0" y2="0"/>
    <circle class="leader-dot" data-region="${region}" cx="0" cy="0" r="3"/>`).join('');
}
function updateLeaders(){
  REGION_ORDER.forEach(region => {
    const a = cardAnchors[region], b = anchorScreens[region];
    const line = leaders.querySelector(`.leader[data-region="${region}"]`);
    const dot = leaders.querySelector(`.leader-dot[data-region="${region}"]`);
    if (!a || !b) return;
    const show = regionForPage(pageIndex) === region && !b.hidden;
    if (line){
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
      line.style.opacity = show ? '' : 0;
    }
    if (dot){
      dot.setAttribute('cx', b.x); dot.setAttribute('cy', b.y);
      dot.style.opacity = show ? '' : 0;
    }
  });
}

function setPresetButton(name){
  document.querySelectorAll('.preset').forEach(b => {
    const on = name ? b.dataset.preset === name : false;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-pressed', String(on));
  });
}
function bindPresets(){
  document.querySelectorAll('.preset').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.dataset.preset;
      if (brain) brain.applyView(name);
      setPresetButton(name);
    });
  });
}

function bindEventSelect(){
  const sel = $('event-select');
  if (!sel || sel.dataset.bound === '1') return;
  sel.dataset.bound = '1';
  sel.addEventListener('change', function () {
    if (typeof window.applyEventToMock === 'function') window.applyEventToMock(sel.value);
    try {
      const q = new URLSearchParams(window.location.search || '');
      q.set('event', sel.value);
      window.history.replaceState({}, '', window.location.pathname + '?' + q.toString());
    } catch (e) {}
    renderEvent(); renderEta(); renderProb(); renderPaths(); renderBottlenecks(); renderAssumptions();
    computeCardAnchors();
  });
}

function preferEventFromUrl(){
  try {
    const q = new URLSearchParams(window.location.search || '');
    const ev = (q.get('event') || '').trim();
    if (ev && typeof window.applyEventToMock === 'function') window.applyEventToMock(ev);
  } catch (e) {}
}

function bindPageChrome(){
  const prevBtn = $('page-prev');
  const nextBtn = $('page-next');
  if (prevBtn) prevBtn.addEventListener('click', () => stepPage(-1));
  if (nextBtn) nextBtn.addEventListener('click', () => stepPage(1));
  document.querySelectorAll('.page-dot').forEach(dot => {
    dot.addEventListener('click', () => {
      const target = +dot.dataset.page;
      goPage(target, target > pageIndex ? -1 : 1);
    });
  });
}

function bindSwipe(){
  let tracking = false;
  let startX = 0;
  let startY = 0;
  let dx = 0;
  let axis = null; // 'x' | 'y' | null
  let pointerId = null;
  let captured = false;

  function scrub(deltaX){
    if (!folio || pageIndex < 0) return;
    const current = folio.querySelector(`.card.page[data-page="${pageIndex}"]`);
    if (!current) return;
    folio.classList.add('is-dragging');
    const t = Math.max(-1, Math.min(1, deltaX / 180));
    const rot = t * 55;
    const shift = t * 36;
    current.style.transform = `translateX(${shift}%) rotateY(${rot}deg) scale(${1 - Math.abs(t) * 0.03})`;
    current.style.opacity = String(1 - Math.abs(t) * 0.35);
  }

  function clearScrub(){
    if (!folio) return;
    folio.classList.remove('is-dragging');
    const current = folio.querySelector(`.card.page.is-open`);
    if (current) {
      current.style.transform = '';
      current.style.opacity = '';
    }
  }

  function onDown(e){
    if (e.button != null && e.button !== 0) return;
    if (e.target.closest('.page-nav, .page-dot, .preset, .assume-btn, #assumptions, .studio-bar, a, input, select, textarea, button, .sv-region')) return;
    tracking = true;
    pointerId = e.pointerId;
    startX = e.clientX;
    startY = e.clientY;
    dx = 0;
    axis = null;
    captured = false;
    // 不在按下时 capture，避免吞掉脑叶 / 控件的 click
  }

  function onMove(e){
    if (!tracking || e.pointerId !== pointerId) return;
    const mx = e.clientX - startX;
    const my = e.clientY - startY;
    if (!axis) {
      if (Math.abs(mx) < 8 && Math.abs(my) < 8) return;
      axis = Math.abs(mx) > Math.abs(my) * 1.15 ? 'x' : 'y';
      if (axis === 'x') {
        stage.classList.add('is-swiping');
        if (!captured) {
          try { stage.setPointerCapture(pointerId); captured = true; } catch (_) {}
        }
        e.preventDefault();
      }
    }
    if (axis !== 'x') return;
    e.preventDefault();
    dx = mx;
    scrub(dx);
  }

  function onUp(e){
    if (!tracking || (pointerId != null && e.pointerId !== pointerId)) return;
    tracking = false;
    stage.classList.remove('is-swiping');
    clearScrub();
    if (captured) {
      try { stage.releasePointerCapture(pointerId); } catch (_) {}
    }
    captured = false;
    pointerId = null;

    if (axis === 'x' && Math.abs(dx) >= SWIPE_THRESHOLD) {
      if (dx < 0) stepPage(1);      // 向左滑 → 下一页
      else stepPage(-1);            // 向右滑 → 上一页
    }
    axis = null;
    dx = 0;
  }

  stage.addEventListener('pointerdown', onDown);
  stage.addEventListener('pointermove', onMove, { passive: false });
  stage.addEventListener('pointerup', onUp);
  stage.addEventListener('pointercancel', onUp);

  window.addEventListener('keydown', (e) => {
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
      e.preventDefault();
      stepPage(-1);
    } else if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') {
      e.preventDefault();
      stepPage(1);
    } else if (e.key === 'Home' || e.key === 'Escape') {
      e.preventDefault();
      goPage(PAGE_MIN, 1);
    }
  });
}

function onResize(){
  computeCardAnchors();
  leaders.setAttribute('viewBox', `0 0 ${stage.clientWidth} ${stage.clientHeight}`);
}

function frameLoop(){
  if (brain) anchorScreens = brain.getAnchors();
  updateLeaders();
  requestAnimationFrame(frameLoop);
}

function init(){
  try {
    const start = function () {
      preferEventFromUrl();
      renderEvent(); renderEta(); renderProb(); renderPaths(); renderBottlenecks(); renderAssumptions();
      buildLeaders();
      computeCardAnchors();
      bindPageChrome();
      bindSwipe();
      bindPresets();
      bindEventSelect();

      brain = window.createBrainPlate($('brain-plate'), {
        onSelect: region => {
          const meta = REGIONS[region];
          if (!meta) return;
          // 再点当前叶 → 回封面
          if (pageIndex === meta.page) goPage(PAGE_MIN, 1);
          else goPage(meta.page, meta.page > pageIndex ? -1 : 1);
        },
        onViewChange: setPresetButton
      });
      setPresetButton('left');
      applyActive();

      window.addEventListener('resize', onResize);
      if (document.fonts && document.fonts.ready) {
        Promise.race([
          document.fonts.ready,
          new Promise(resolve => setTimeout(resolve, 2500))
        ]).then(computeCardAnchors);
      }
      requestAnimationFrame(frameLoop);
    };

    start();
    setTimeout(dismissBoot, 400);

    const live = (typeof window.loadLiveCapability === 'function')
      ? Promise.race([
          window.loadLiveCapability(),
          new Promise(function (_, reject) {
            setTimeout(function () { reject(new Error('live timeout')); }, 2000);
          })
        ]).catch(function (err) {
          console.warn('[capability-prob] live params fallback to mock', err);
          return null;
        })
      : Promise.resolve(null);

    live.then(function (ok) {
      if (!ok) return;
      preferEventFromUrl();
      renderEvent(); renderEta(); renderProb(); renderPaths(); renderBottlenecks(); renderAssumptions();
      computeCardAnchors();
    }).catch(function (err) {
      console.warn('[capability-prob] live refresh skipped', err);
    }).finally(function () { dismissBoot(); });
    return;
  } catch (err){
    console.error('[capability-prob] init failed', err);
    dismissBoot();
  }
}

init();
