// brain-draw.js —— 平面手绘墨线解剖脑（四视图）
(function (root) {
'use strict';

const REGION_KEYS = ['frontal', 'parietal', 'temporal', 'occipital'];

const CEREBRUM_L = 'M 72 130 C 64 108, 70 80, 90 60 C 104 48, 122 42, 140 40 C 152 38, 162 46, 176 40 C 192 32, 210 36, 226 32 C 244 28, 258 36, 274 32 C 292 26, 310 32, 326 30 C 346 28, 366 40, 380 56 C 396 74, 410 94, 416 116 C 424 140, 424 164, 414 186 C 406 204, 388 216, 366 218 C 350 220, 338 214, 328 218 C 336 238, 328 260, 306 272 C 280 286, 246 290, 214 282 C 186 298, 148 302, 118 282 C 100 266, 90 242, 86 216 C 84 196, 108 180, 152 172 C 122 166, 88 154, 76 136 C 72 130 Z';

const CEREB_L = 'M 292 266 C 316 254, 348 258, 368 274 C 386 288, 390 310, 374 324 C 356 340, 322 344, 298 332 C 278 322, 272 300, 280 284 C 284 274, 288 268, 292 266 Z';

const STEM_L = 'M 236 278 C 242 296, 240 318, 232 338 L 252 340 C 264 318, 268 296, 260 278 Z';

const SULCI_L = [
  { cls: 'sv-sulcus', d: 'M 248 38 C 242 84, 236 126, 246 164 C 252 182, 262 192, 278 198' },
  { cls: 'sv-sulcus', d: 'M 152 172 C 190 164, 230 164, 258 170 C 292 178, 318 196, 330 222' },
  { cls: 'sv-sulcus-soft', d: 'M 216 42 C 210 88, 206 128, 218 162' },
  { cls: 'sv-sulcus-soft', d: 'M 278 40 C 274 82, 270 122, 280 156' },
  { cls: 'sv-sulcus-soft', d: 'M 128 218 C 172 204, 224 200, 274 212 C 302 220, 322 236, 332 254' },
  { cls: 'sv-sulcus-soft', d: 'M 98 88 C 140 74, 184 78, 226 70' },
  { cls: 'sv-sulcus-soft', d: 'M 90 138 C 122 124, 154 128, 178 146' },
  { cls: 'sv-sulcus-soft', d: 'M 132 66 C 156 86, 166 110, 158 140' },
  { cls: 'sv-sulcus-soft', d: 'M 304 68 C 314 100, 322 130, 326 158' },
  { cls: 'sv-sulcus-soft', d: 'M 358 56 C 350 98, 346 138, 356 176' },
  { cls: 'sv-sulcus-soft', d: 'M 398 138 C 378 148, 360 162, 350 182' },
  { cls: 'sv-sulcus-soft', d: 'M 380 88 C 392 110, 396 132, 388 156' },
  { cls: 'sv-sulcus-soft', d: 'M 400 176 C 384 188, 370 202, 364 220' },
  { cls: 'sv-gyrus', d: 'M 108 58 C 118 72, 116 88, 108 102' },
  { cls: 'sv-gyrus', d: 'M 148 44 C 156 60, 154 76, 146 92' },
  { cls: 'sv-gyrus', d: 'M 188 38 C 196 56, 194 74, 186 90' },
  { cls: 'sv-gyrus', d: 'M 328 48 C 338 68, 344 90, 346 112' },
  { cls: 'sv-gyrus', d: 'M 230 48 C 238 68, 236 88, 228 108' },
  { cls: 'sv-gyrus', d: 'M 260 44 C 268 64, 266 86, 258 106' },
  { cls: 'sv-gyrus', d: 'M 160 210 C 188 200, 220 202, 248 212' },
  { cls: 'sv-gyrus', d: 'M 100 160 C 118 148, 138 150, 152 162' },
  { cls: 'sv-gyrus', d: 'M 350 70 C 360 90, 364 112, 360 134' }
];

const FOLIA_L = [
  'M 286 278 C 318 268, 348 272, 370 286',
  'M 284 290 C 316 280, 346 284, 366 298',
  'M 282 302 C 312 294, 340 298, 358 310',
  'M 286 314 C 312 308, 334 312, 348 322',
  'M 312 268 C 320 292, 318 314, 308 330'
];

const REGIONS_L = [
  { key: 'frontal',   d: 'M 72 130 C 64 108, 70 80, 90 60 C 104 48, 122 42, 140 40 C 152 38, 162 46, 176 40 C 192 32, 210 36, 226 32 C 238 30, 248 32, 248 38 L 246 164 C 240 170, 210 174, 152 172 C 122 166, 88 154, 76 136 Z' },
  { key: 'parietal',  d: 'M 248 38 C 274 32, 310 30, 346 28 C 364 40, 376 50, 380 56 C 370 90, 362 130, 356 176 L 246 164 C 242 84, 248 38, 248 38 Z' },
  { key: 'temporal',  d: 'M 152 172 C 180 164, 220 162, 258 170 C 280 176, 302 188, 318 206 L 306 272 C 280 286, 246 290, 214 282 C 186 298, 148 302, 118 282 C 100 266, 90 242, 86 216 C 84 196, 108 180, 152 172 Z' },
  { key: 'occipital', d: 'M 380 56 C 396 74, 410 94, 416 116 C 424 140, 424 164, 414 186 C 406 204, 388 216, 366 218 C 350 220, 338 214, 328 218 C 330 200, 338 186, 350 182 C 362 130, 370 90, 380 56 Z' }
];

const ANCHORS_L = {
  frontal:   [118, 112],
  parietal:  [292, 64],
  temporal:  [158, 236],
  occipital: [388, 142]
};

const LABELS_L = [
  { x: 108, y: 118, t: '额' },
  { x: 286, y: 72,  t: '顶' },
  { x: 154, y: 248, t: '颞' },
  { x: 392, y: 148, t: '枕' }
];

const CEREBRUM_U = 'M 64 200 C 58 132, 90 72, 168 52 C 228 38, 312 40, 380 64 C 428 84, 456 132, 454 200 C 400 190, 320 186, 240 186 C 160 186, 90 190, 64 200 Z';
const CEREBRUM_D = 'M 64 200 C 58 268, 90 328, 168 348 C 228 362, 312 360, 380 336 C 428 316, 456 268, 454 200 C 400 210, 320 214, 240 214 C 160 214, 90 210, 64 200 Z';

const SULCI_TOP = [
  { cls: 'sv-sulcus', d: 'M 72 200 C 160 192, 320 192, 448 200' },
  { cls: 'sv-sulcus', d: 'M 248 188 C 246 136, 258 88, 270 56' },
  { cls: 'sv-sulcus', d: 'M 248 212 C 246 264, 258 312, 270 344' },
  { cls: 'sv-sulcus-soft', d: 'M 198 186 C 196 140, 206 96, 218 64' },
  { cls: 'sv-sulcus-soft', d: 'M 198 214 C 196 260, 206 304, 218 336' },
  { cls: 'sv-sulcus-soft', d: 'M 298 188 C 302 142, 314 98, 328 70' },
  { cls: 'sv-sulcus-soft', d: 'M 298 212 C 302 258, 314 302, 328 330' },
  { cls: 'sv-sulcus-soft', d: 'M 120 168 C 160 148, 210 142, 248 148' },
  { cls: 'sv-sulcus-soft', d: 'M 120 232 C 160 252, 210 258, 248 252' },
  { cls: 'sv-sulcus-soft', d: 'M 140 120 C 180 108, 230 106, 280 118' },
  { cls: 'sv-sulcus-soft', d: 'M 140 280 C 180 292, 230 294, 280 282' },
  { cls: 'sv-gyrus', d: 'M 100 176 C 130 160, 150 150, 168 148' },
  { cls: 'sv-gyrus', d: 'M 100 224 C 130 240, 150 250, 168 252' },
  { cls: 'sv-gyrus', d: 'M 360 100 C 380 120, 392 148, 396 176' },
  { cls: 'sv-gyrus', d: 'M 360 300 C 380 280, 392 252, 396 224' }
];

const REGIONS_TOP = [
  { key: 'frontal',   d: 'M 64 200 C 58 132, 90 72, 168 52 C 198 46, 228 44, 248 48 L 248 188 C 200 186, 140 188, 64 200 C 58 268, 90 328, 168 348 C 198 354, 228 356, 248 352 L 248 212 C 200 214, 140 212, 64 200 Z' },
  { key: 'parietal',  d: 'M 248 48 C 280 42, 320 44, 352 54 L 328 70 C 314 98, 302 142, 298 188 L 248 188 C 246 136, 258 88, 270 56 Z M 248 352 C 280 358, 320 356, 352 346 L 328 330 C 314 302, 302 258, 298 212 L 248 212 C 246 264, 258 312, 270 344 Z' },
  { key: 'temporal',  d: 'M 140 280 C 168 310, 210 338, 258 348 C 230 356, 190 354, 168 348 C 120 330, 90 280, 80 240 C 100 250, 120 268, 140 280 Z' },
  { key: 'occipital', d: 'M 352 54 C 390 70, 430 110, 454 200 C 430 290, 390 330, 352 346 C 320 356, 300 350, 298 212 L 298 188 C 300 90, 320 60, 352 54 Z' }
];

const ANCHORS_TOP = {
  frontal:   [128, 200],
  parietal:  [268, 78],
  temporal:  [168, 318],
  occipital: [408, 200]
};

const LABELS_TOP = [
  { x: 118, y: 194, t: '额' },
  { x: 268, y: 86,  t: '顶' },
  { x: 168, y: 328, t: '颞' },
  { x: 408, y: 196, t: '枕' }
];

const FAR_RIM = 'M 96 46 C 168 16, 268 12, 348 28 C 386 38, 408 58, 404 78 C 368 50, 286 40, 204 46 C 146 50, 108 56, 96 46 Z';
const FAR_MID = 'M 188 44 C 240 36, 310 38, 362 54';

function sulciMarkup(list) {
  return list.map(s => `<path class="${s.cls}" d="${s.d}"/>`).join('');
}
function foliaMarkup(list) {
  return list.map(d => `<path class="sv-folia" d="${d}"/>`).join('');
}
function regionMarkup(list, view) {
  return list.map(r =>
    `<path class="sv-region" data-region="${r.key}" data-od-id="lobe-${r.key}-${view}" d="${r.d}" clip-path="url(#brainClip)"/>`
  ).join('');
}
function regionMarkupRaw(list, view) {
  return list.map(r =>
    `<path class="sv-region" data-region="${r.key}" data-od-id="lobe-${r.key}-${view}" d="${r.d}"/>`
  ).join('');
}
function anchorsMarkup(map) {
  return REGION_KEYS.map(k =>
    `<circle class="sv-anchor" data-region="${k}" cx="${map[k][0]}" cy="${map[k][1]}" r="2.2"/>`
  ).join('');
}
function labelsMarkup(list) {
  return list.map(l =>
    `<text class="sv-label" x="${l.x}" y="${l.y}">${l.t}</text>`
  ).join('');
}

function lateralInner(opts) {
  const view = (opts && opts.view) || 'left';
  const regionFn = opts && opts.rawRegions ? regionMarkupRaw : regionMarkup;
  return `
    <path class="sv-outline-ghost" d="${CEREBRUM_L}" transform="translate(1.1,.7)"/>
    <path class="sv-stem" d="${STEM_L}"/>
    <path class="sv-cereb" d="${CEREB_L}"/>
    ${foliaMarkup(FOLIA_L)}
    <path class="sv-outline" d="${CEREBRUM_L}"/>
    ${regionFn(REGIONS_L, view)}
    ${sulciMarkup(SULCI_L)}
    ${anchorsMarkup(ANCHORS_L)}
  `;
}

function caption(id, line) {
  return `<text class="sv-caption" x="240" y="372" text-anchor="middle" data-od-id="${id}">${line}</text>`;
}

function buildMarkup() {
  return `
    <defs>
      <clipPath id="brainClip"><path d="${CEREBRUM_L}"/></clipPath>
      <clipPath id="brainClipTop">
        <path d="${CEREBRUM_U}"/>
        <path d="${CEREBRUM_D}"/>
      </clipPath>
    </defs>

    <g class="plate-chrome" aria-hidden="true">
      <path class="sv-tick" d="M 18 18 h 18 M 18 18 v 18"/>
      <path class="sv-tick" d="M 462 18 h -18 M 462 18 v 18"/>
      <path class="sv-tick" d="M 18 362 h 18 M 18 362 v -18"/>
      <path class="sv-tick" d="M 462 362 h -18 M 462 362 v -18"/>
      <text class="sv-plate-no" x="22" y="52">TAB. I</text>
    </g>

    <g class="brain-view is-on" data-view="left">
      ${lateralInner({ view: 'left' })}
      ${labelsMarkup(LABELS_L)}
      ${caption('cap-left', '左半球 · 外侧面')}
    </g>

    <g class="brain-view" data-view="right">
      <g transform="translate(480,0) scale(-1,1)">
        ${lateralInner({ rawRegions: true, view: 'right' })}
      </g>
      ${labelsMarkup([
        { x: 372, y: 118, t: '额' },
        { x: 194, y: 72,  t: '顶' },
        { x: 326, y: 236, t: '颞' },
        { x: 88,  y: 148, t: '枕' }
      ])}
      ${caption('cap-right', '右半球 · 外侧面')}
    </g>

    <g class="brain-view" data-view="top">
      <path class="sv-outline-ghost" d="${CEREBRUM_U}" transform="translate(.8,.6)"/>
      <path class="sv-outline-ghost" d="${CEREBRUM_D}" transform="translate(.8,.6)"/>
      <path class="sv-outline" d="${CEREBRUM_U}"/>
      <path class="sv-outline" d="${CEREBRUM_D}"/>
      ${REGIONS_TOP.map(r =>
        `<path class="sv-region" data-region="${r.key}" data-od-id="lobe-${r.key}-top" d="${r.d}" clip-path="url(#brainClipTop)"/>`
      ).join('')}
      ${sulciMarkup(SULCI_TOP)}
      ${anchorsMarkup(ANCHORS_TOP)}
      ${labelsMarkup(LABELS_TOP)}
      ${caption('cap-top', '大脑 · 上面')}
    </g>

    <g class="brain-view" data-view="oblique">
      <path class="sv-far" d="${FAR_RIM}"/>
      <path class="sv-sulcus-soft" d="${FAR_MID}"/>
      <g transform="translate(8,14)">
        ${lateralInner({ rawRegions: true, view: 'oblique' })}
      </g>
      ${labelsMarkup([
        { x: 118, y: 132, t: '额' },
        { x: 296, y: 86,  t: '顶' },
        { x: 164, y: 250, t: '颞' },
        { x: 400, y: 162, t: '枕' }
      ])}
      ${caption('cap-oblique', '左半球 · 斜侧面')}
    </g>
  `;
}

function createBrainPlate(svg, { onSelect, onViewChange } = {}) {
  svg.setAttribute('viewBox', '0 0 480 380');
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.innerHTML = buildMarkup();

  let view = 'left';

  svg.querySelectorAll('.sv-region').forEach(p => {
    p.setAttribute('tabindex', '0');
    p.setAttribute('role', 'button');
    p.setAttribute('aria-label', '翻到 ' + (p.dataset.region || '') + ' 区注记');
    // pointerup：避免父级 swipe 的 setPointerCapture 吞掉 click
    // 不用 click 再调一次，否则会「打开又立刻回封面」
    let downAt = null;
    p.addEventListener('pointerdown', (e) => {
      if (e.button != null && e.button !== 0) return;
      downAt = { x: e.clientX, y: e.clientY, id: e.pointerId };
      e.stopPropagation(); // 不让舞台把这次按下当成手划起点
    });
    p.addEventListener('pointerup', (e) => {
      if (!downAt || e.pointerId !== downAt.id) return;
      const dx = Math.abs(e.clientX - downAt.x);
      const dy = Math.abs(e.clientY - downAt.y);
      downAt = null;
      if (dx > 10 || dy > 10) return;
      e.preventDefault();
      e.stopPropagation();
      onSelect && onSelect(p.dataset.region);
    });
    p.addEventListener('pointercancel', () => { downAt = null; });
    p.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        onSelect && onSelect(p.dataset.region);
      }
    });
  });

  function applyView(name) {
    const next = svg.querySelector(`[data-view="${name}"]`) ? name : 'left';
    view = next;
    svg.querySelectorAll('.brain-view').forEach(g => {
      g.classList.toggle('is-on', g.dataset.view === next);
    });
    onViewChange && onViewChange(next);
  }

  function setRegionTint(key) {
    svg.querySelectorAll('.sv-region').forEach(p => {
      p.classList.toggle('is-active', !!(key && p.dataset.region === key));
    });
  }

  function getAnchors() {
    const stage = svg.parentElement;
    if (!stage) return {};
    const sr = stage.getBoundingClientRect();
    const activeView = svg.querySelector('.brain-view.is-on');
    const out = {};
    REGION_KEYS.forEach(key => {
      const el = activeView && activeView.querySelector(`.sv-anchor[data-region="${key}"]`);
      if (!el) {
        out[key] = { x: 0, y: 0, hidden: true };
        return;
      }
      const pt = svg.createSVGPoint();
      pt.x = +el.getAttribute('cx');
      pt.y = +el.getAttribute('cy');
      const ctm = el.getScreenCTM();
      if (!ctm) {
        out[key] = { x: 0, y: 0, hidden: true };
        return;
      }
      const sp = pt.matrixTransform(ctm);
      out[key] = { x: sp.x - sr.left, y: sp.y - sr.top, hidden: false };
    });
    return out;
  }

  applyView('left');

  return { applyView, setRegionTint, getAnchors, get view() { return view; } };
}

root.createBrainPlate = createBrainPlate;
})(window);
