/* Tinnitus Atlas — app.js: data layer + shared chrome + page renderers.
   All pages render from /data/*.json. No frameworks, no build step. */
(function () {
  'use strict';

  /* ---------------- theme ---------------- */
  const THEME_KEY = 'ta:theme';
  function applyTheme(t) { document.documentElement.dataset.theme = t; }
  (function initTheme() {
    let t;
    try { t = localStorage.getItem(THEME_KEY); } catch (e) {}
    if (t !== 'light' && t !== 'dark') t = 'dark'; // dark is the default; light only by explicit choice
    applyTheme(t);
  })();

  /* ---------------- utils ---------------- */
  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const $ = (sel, el) => (el || document).querySelector(sel);
  const $$ = (sel, el) => Array.from((el || document).querySelectorAll(sel));
  const fmtDate = iso => {
    if (!iso) return '';
    const d = new Date(iso + (iso.length === 10 ? 'T12:00:00' : ''));
    return isNaN(d) ? iso : d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  };
  /* Single-file preview mode: data embedded, pages routed via location.hash (see tools/build_preview.py) */
  const SINGLE = !!window.__TA_SINGLE__;
  const qs = k => new URLSearchParams(SINGLE ? (location.hash.split('?')[1] || '') : location.search).get(k);

  /* ---------------- data ---------------- */
  let DB = null;
  function indexDB() {
    DB.catById = Object.fromEntries(DB.categories.map(c => [c.id, c]));
    DB.tById = Object.fromEntries(DB.treatments.map(t => [t.id, t]));
    DB.sById = Object.fromEntries(DB.studies.map(s => [s.id, s]));
  }
  async function load() {
    if (DB) return DB;
    if (window.__TA_DATA__) { DB = window.__TA_DATA__; indexDB(); return DB; }
    const get = f => fetch('data/' + f).then(r => { if (!r.ok) throw new Error(f + ' ' + r.status); return r.json(); });
    const [meta, categories, treatments, studies, trials, institutions, rankings, weeklyIndex] =
      await Promise.all(['meta.json', 'categories.json', 'treatments.json', 'studies.json',
        'trials.json', 'institutions.json', 'rankings.json', 'weekly/index.json'].map(get));
    let weekly = null;
    if (weeklyIndex.reports && weeklyIndex.reports.length) {
      weekly = await get('weekly/' + weeklyIndex.reports[0].file);
    }
    DB = { meta, categories, treatments, studies, trials, institutions, rankings, weeklyIndex, weekly };
    indexDB();
    return DB;
  }

  /* ---------------- watchlist ---------------- */
  const WL_KEY = 'ta:watchlist', SEEN_KEY = 'ta:lastSeen';
  const wlGet = () => { try { return JSON.parse(localStorage.getItem(WL_KEY)) || []; } catch (e) { return []; } };
  const wlSet = ids => { try { localStorage.setItem(WL_KEY, JSON.stringify(ids)); } catch (e) {} };
  const wlHas = id => wlGet().includes(id);
  const wlToggle = id => { const l = wlGet(); const i = l.indexOf(id); i >= 0 ? l.splice(i, 1) : l.push(id); wlSet(l); return i < 0; };

  /* ---------------- shared components ---------------- */
  const TIER_LABELS = {
    1: ['Strongest evidence', 'b-strong'], 2: ['Promising', 'b-promising'],
    3: ['Experimental', 'b-emerging'], 4: ['Coping / symptom mgmt', 'b-watch'],
    5: ['Weak / unsupported', 'b-weak']
  };
  const LV_LABELS = { none: 'None shown', limited: 'Limited', moderate: 'Moderate', strong: 'Strong' };
  const scoreColor = n => n >= 4 ? 'var(--c-strong)' : n >= 3 ? 'var(--c-promising)' : n >= 2 ? 'var(--c-watch)' : 'var(--c-weak)';

  function tierBadge(tier) {
    const [label, cls] = TIER_LABELS[tier] || ['—', 'b-weak'];
    return `<span class="badge ${cls}">${label}</span>`;
  }
  function emeter(score, label) {
    let dots = '';
    for (let i = 1; i <= 5; i++) dots += `<i class="${i <= score ? 'on' : ''}"></i>`;
    return `<span class="emeter" style="--em-c:${scoreColor(score)}" title="Evidence score ${score}/5"
      role="img" aria-label="Evidence score ${score} out of 5">${dots}<span class="lab">${label !== false ? score + '/5' : ''}</span></span>`;
  }
  function duo(t, compact) {
    const cell = (k, o) => `<div class="cell"><div class="k">${k}</div>
      <div class="v lv-${esc(o.level)}">${LV_LABELS[o.level] || esc(o.level)}</div>
      ${compact ? '' : `<div class="small muted">${esc(o.summary)}</div>`}</div>`;
    return `<div class="duo">${cell('🔉 Loudness', t.loudness)}${cell('🧠 Distress', t.distress)}</div>`;
  }
  function availBadge(t) {
    return t.availability && t.availability.availableNow
      ? '<span class="badge b-strong">Available now</span>'
      : '<span class="badge b-emerging">Not yet available</span>';
  }
  function updatedRecently(t, days) {
    const cutoff = Date.now() - (days || 45) * 864e5;
    return (t.latest || []).some(l => new Date(l.date) >= cutoff);
  }

  function treatmentCard(t, opts) {
    opts = opts || {};
    const cat = DB.catById[t.category] || {};
    return `<a class="card tcard" href="treatment.html?id=${esc(t.id)}" style="--cat-c:${esc(cat.color || '#888')}">
      ${opts.rank ? `<span class="rank">#${opts.rank}</span>` : ''}
      <span class="cat" style="color:${esc(cat.color || 'var(--muted)')}">${esc(cat.icon || '')} ${esc(cat.name || t.category)}</span>
      <h3>${updatedRecently(t) ? '<span class="updated-dot" title="Updated recently"></span>' : ''}${esc(t.name)}</h3>
      <p class="one">${esc(t.oneLiner)}</p>
      ${duo(t, true)}
      <div class="foot">${emeter(t.evidenceScore)} ${tierBadge(t.tier)} ${availBadge(t)}</div>
    </a>`;
  }

  /* ---------------- chrome ---------------- */
  const NAV = [
    ['index.html', 'Home', '🏠'],
    ['treatments.html', 'Treatments', '🧭'],
    ['trials.html', 'Trials', '🧪'],
    ['research.html', 'Research', '📰'],
    ['watchlist.html', 'Watchlist', '⭐'],
  ];
  const NAV_MORE = [['compare.html', 'Compare'], ['institutions.html', 'Institutions'], ['about.html', 'About']];

  function chrome() {
    $$('.topbar, .bottomnav, .footer').forEach(el => el.remove()); // idempotent (single-file router re-runs it)
    const brand = (DB && DB.meta && DB.meta.name) || 'Tinnitus Atlas';
    // keep the brand configurable: page titles follow data/meta.json
    if (DB && document.title.includes('Tinnitus Atlas')) {
      document.title = document.title.replace(/Tinnitus Atlas/g, brand);
    }
    const page = document.body.dataset.page || '';
    const here = f => f.replace('.html', '') === page ? ' aria-current="page"' : '';
    const top = document.createElement('header');
    top.className = 'topbar';
    top.innerHTML = `
      <a class="brand" href="index.html"><span class="mark" aria-hidden="true">◔</span><span>${esc(brand)}</span></a>
      <nav class="nav-desktop" aria-label="Main">
        ${NAV.concat(NAV_MORE.map(x => [x[0], x[1], ''])).map(([f, n]) => `<a href="${f}"${here(f)}>${n}</a>`).join('')}
      </nav>
      <button class="theme-btn" type="button" aria-label="Toggle dark mode">◐</button>`;
    document.body.prepend(top);
    $('.theme-btn', top).addEventListener('click', () => {
      const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      applyTheme(t); try { localStorage.setItem(THEME_KEY, t); } catch (e) {}
    });

    const bottom = document.createElement('nav');
    bottom.className = 'bottomnav'; bottom.setAttribute('aria-label', 'Primary');
    bottom.innerHTML = NAV.map(([f, n, i]) =>
      `<a href="${f}"${here(f)}><span class="ico" aria-hidden="true">${i}</span>${n}</a>`).join('');
    document.body.append(bottom);

    const foot = document.createElement('footer');
    foot.className = 'footer';
    foot.innerHTML = `<div class="wrap">
      <p><strong>${esc(brand)}</strong> is an educational and scientific information resource. It does not diagnose
      tinnitus, does not provide personalized medical advice, and does not replace an ENT physician, audiologist, or
      other qualified professional. Treatment rankings reflect our evaluation of available evidence; scientific
      understanding changes and individual results differ. <a href="about.html#disclaimer">Full disclaimer & methodology</a>.</p>
      <p class="small" id="foot-meta"></p></div>`;
    document.body.append(foot);
  }

  /* ---------------- page renderers ---------------- */
  const PAGES = {};

  /* ----- home ----- */
  PAGES.index = function () {
    const { meta, treatments, rankings, weekly, categories, trials } = DB;
    $('#stat-treatments').textContent = treatments.length;
    $('#stat-studies').textContent = DB.studies.length;
    $('#stat-trials').textContent = trials.length;
    $('#stat-updated').textContent = fmtDate(meta.lastFullReview);

    // Top 10 (with "Why this ranking?" expanders)
    $('#top10').innerHTML = rankings.top.map(r => {
      const t = DB.tById[r.id]; if (!t) return '';
      return rankedCard(t, r);
    }).join('');

    // Available now
    const avail = treatments.filter(t => t.availability && t.availability.availableNow && t.tier <= 4 && t.evidenceScore >= 3)
      .sort((a, b) => b.evidenceScore - a.evidenceScore).slice(0, 6);
    $('#available').innerHTML = avail.map(t => treatmentCard(t)).join('');

    // What's new this week
    if (weekly) {
      $('#week-date').textContent = fmtDate(weekly.date);
      $('#whatsnew').innerHTML = weekly.items.slice(0, 5).map(weekItem).join('') +
        `<p><a class="btn btn-ghost" href="research.html">Read the full weekly report →</a></p>`;
    }

    // Coming soon
    const coming = trials.filter(t => t.watch).slice(0, 4);
    $('#coming').innerHTML = coming.map(trialCard).join('');

    // Categories
    $('#cats').innerHTML = categories.map(c => {
      const n = treatments.filter(t => t.category === c.id).length;
      return `<a class="catcard" href="treatments.html?cat=${esc(c.id)}" style="--cat-c:${esc(c.color)}">
        <span class="ico" aria-hidden="true">${esc(c.icon)}</span><h3>${esc(c.name)}</h3>
        <span class="small muted">${esc(c.blurb)}</span><span class="count">${n} treatment${n === 1 ? '' : 's'} tracked</span></a>`;
    }).join('');
  };

  function whyRankingBlock(r, t) {
    const d = r.detail || {};
    const row = (k, v) => v ? `<li><strong>${k}:</strong> ${esc(v)}</li>` : '';
    return `<details class="rdetail"><summary>Why is this ranked #${r.rank}?</summary>
      <p class="small">${esc(r.why)}</p>
      <ul class="small">
        ${row('Strongest evidence', d.strongest)}
        ${row('Weakest point', d.weakest)}
        ${row('Key studies', d.studies)}
        ${row('Independent replication', d.replication)}
        ${row('Loudness evidence', d.loudness || (t && t.loudness.summary))}
        ${row('Distress evidence', d.distress || (t && t.distress.summary))}
        ${row('Availability', d.availability)}
        ${row('Main uncertainty', d.uncertainty)}
        ${row('What could change this ranking', r.couldChange)}
      </ul></details>`;
  }

  function rankedCard(t, r) {
    const cat = DB.catById[t.category] || {};
    return `<div class="card tcard" style="--cat-c:${esc(cat.color || '#888')}">
      <span class="rank">#${r.rank}</span>
      <span class="cat" style="color:${esc(cat.color || 'var(--muted)')}">${esc(cat.icon || '')} ${esc(cat.name || t.category)}</span>
      <h3>${updatedRecently(t) ? '<span class="updated-dot" title="Updated recently"></span>' : ''}<a href="treatment.html?id=${esc(t.id)}" style="color:inherit">${esc(t.name)}</a></h3>
      <p class="one">${esc(t.oneLiner)}</p>
      ${duo(t, true)}
      <div class="foot">${emeter(t.evidenceScore)} ${tierBadge(t.tier)} ${availBadge(t)}</div>
      ${whyRankingBlock(r, t)}
    </div>`;
  }

  function weekItem(it) {
    const KIND_COLORS = { study: 'var(--c-promising)', trial: 'var(--c-emerging)', regulatory: 'var(--c-strong)', ranking: 'var(--c-watch)', negative: 'var(--c-weak)', news: 'var(--c-promising)' };
    return `<div class="week-item" style="--w-c:${KIND_COLORS[it.kind] || 'var(--c-promising)'}">
      <div class="t">${esc(it.title)}</div>
      <div class="small muted">${esc(it.summary)}</div>
      ${it.treatment && DB.tById[it.treatment] ? `<a class="small" href="treatment.html?id=${esc(it.treatment)}">${esc(DB.tById[it.treatment].name)} →</a>` : ''}
      ${it.url ? ` <a class="small" href="${esc(it.url)}" rel="noopener" target="_blank">Source ↗</a>` : ''}</div>`;
  }

  function trialCard(tr) {
    const t = tr.treatment && DB.tById[tr.treatment];
    const st = /recruit/i.test(tr.status) ? 'b-strong' : /active|enrolling/i.test(tr.status) ? 'b-promising' : /complete/i.test(tr.status) ? 'b-weak' : 'b-watch';
    return `<div class="card">
      <div class="foot" style="margin:0 0 8px;display:flex;gap:6px;flex-wrap:wrap">
        <span class="badge ${st}">${esc(tr.status)}</span>
        ${tr.phase ? `<span class="badge b-emerging">${esc(tr.phase)}</span>` : ''}
        ${tr.watch ? '<span class="badge b-watch">One to watch</span>' : ''}</div>
      <h3 style="font-size:1rem">${esc(tr.title)}</h3>
      <p class="small muted">${esc(tr.sponsor)}${tr.n ? ` · target N=${esc(tr.n)}` : ''}${tr.completionEst ? ` · est. completion ${esc(tr.completionEst)}` : ''}</p>
      ${tr.whyItMatters ? `<p class="small">${esc(tr.whyItMatters)}</p>` : ''}
      <p class="small" style="margin-bottom:0">
        ${t ? `<a href="treatment.html?id=${esc(t.id)}">${esc(t.name)}</a> · ` : ''}
        <a href="${esc(tr.url || ('https://clinicaltrials.gov/study/' + tr.nctId))}" rel="noopener" target="_blank">${esc(tr.nctId)} ↗</a></p>
    </div>`;
  }

  /* ----- treatments browse ----- */
  PAGES.treatments = function () {
    const state = { cat: qs('cat') || '', tier: '', avail: false, loud: false, distress: false, q: '' };
    const catChips = $('#cat-chips'), listEl = $('#tlist');
    catChips.innerHTML = `<button class="chip" data-cat="">All categories</button>` +
      DB.categories.map(c => `<button class="chip" data-cat="${esc(c.id)}">${esc(c.icon)} ${esc(c.name)}</button>`).join('');

    function render() {
      $$('#cat-chips .chip').forEach(ch => ch.setAttribute('aria-pressed', ch.dataset.cat === state.cat));
      $$('#flag-chips .chip').forEach(ch => ch.setAttribute('aria-pressed', !!state[ch.dataset.flag]));
      let list = DB.treatments.slice();
      if (state.cat) list = list.filter(t => t.category === state.cat);
      if (state.avail) list = list.filter(t => t.availability && t.availability.availableNow);
      if (state.loud) list = list.filter(t => ['moderate', 'strong'].includes(t.loudness.level));
      if (state.distress) list = list.filter(t => ['moderate', 'strong'].includes(t.distress.level));
      if (state.q) {
        const q = state.q.toLowerCase();
        list = list.filter(t => (t.name + ' ' + t.oneLiner + ' ' + t.developer + ' ' + (t.researchers || []).join(' ') + ' ' + t.mechanism).toLowerCase().includes(q));
      }
      list.sort((a, b) => a.tier - b.tier || b.evidenceScore - a.evidenceScore || a.name.localeCompare(b.name));
      listEl.innerHTML = list.length ? list.map(t => treatmentCard(t)).join('') :
        '<div class="empty">Nothing matches those filters.</div>';
      $('#tcount').textContent = list.length;
    }
    catChips.addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { state.cat = b.dataset.cat; render(); } });
    $('#flag-chips').addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { state[b.dataset.flag] = !state[b.dataset.flag]; render(); } });
    $('#tsearch').addEventListener('input', e => { state.q = e.target.value.trim(); render(); });
    render();
  };

  /* ----- treatment detail ----- */
  PAGES.treatment = function () {
    const t = DB.tById[qs('id')];
    const root = $('#tdetail');
    if (!t) { root.innerHTML = '<div class="empty">Treatment not found. <a href="treatments.html">Browse all treatments</a></div>'; return; }
    document.title = t.name + ' — ' + ((DB.meta && DB.meta.name) || 'Tinnitus Atlas');
    const cat = DB.catById[t.category] || {};
    const rEntry = DB.rankings.top.find(r => r.id === t.id);
    const rank = (rEntry || {}).rank;
    // "Previously: #x · y/5" — compare the last two ranking-history snapshots (Part XXI / #12)
    let prevNote = '';
    const rh = DB.rankings.history || [];
    if (rh.length >= 2) {
      const prev = (rh[rh.length - 2].snapshot || []).find(s => s.id === t.id);
      const cur = (rh[rh.length - 1].snapshot || []).find(s => s.id === t.id);
      if (prev && cur && (prev.rank !== cur.rank || prev.evidenceScore !== cur.evidenceScore)) {
        const why = (t.history && t.history[0] && t.history[0].reason) || rh[rh.length - 1].note || '';
        prevNote = `<div class="notice" style="margin:10px 0"><strong>Assessment changed.</strong>
          Previously: #${prev.rank || '—'} · Evidence ${prev.evidenceScore}/5 &nbsp;→&nbsp; Now: #${cur.rank || '—'} · Evidence ${cur.evidenceScore}/5.
          ${esc(why)}</div>`;
      }
    }
    const av = t.availability || {};
    const conf = { low: ['b-watch', 'Low'], moderate: ['b-promising', 'Moderate'], high: ['b-strong', 'High'] }[t.confidence] || ['b-weak', '—'];

    root.innerHTML = `
      <p class="small" style="margin-top:14px"><a href="treatments.html">‹ All treatments</a></p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <span class="cat" style="color:${esc(cat.color)};font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.06em">${esc(cat.icon)} ${esc(cat.name)}</span>
        ${rank ? `<span class="badge b-promising">#${rank} most promising</span>` : ''}
      </div>
      <h1 style="margin:.2em 0 .3em">${esc(t.name)}</h1>
      <p class="muted" style="max-width:46em">${esc(t.oneLiner)}</p>
      <p><button class="btn watch-btn" type="button" id="watch" aria-pressed="${wlHas(t.id)}">⭐ <span>${wlHas(t.id) ? 'On your watchlist' : 'Add to watchlist'}</span></button>
      <a class="btn" href="compare.html?ids=${esc(t.id)}">⚖ Compare</a></p>

      ${prevNote}
      ${rEntry ? whyRankingBlock(rEntry, t) : ''}
      <div class="snapshot" style="margin:16px 0">
        <div class="cell"><div class="k">Evidence score</div><div class="v">${emeter(t.evidenceScore)}</div></div>
        <div class="cell"><div class="k">Tier</div><div class="v">${tierBadge(t.tier)}</div></div>
        <div class="cell"><div class="k">Available now</div><div class="v">${av.availableNow ? 'Yes' : 'No'}</div></div>
        <div class="cell"><div class="k">Regulatory status</div><div class="v">${esc(t.regulatory.status)}</div></div>
        <div class="cell"><div class="k">Loudness effect</div><div class="v lv-${esc(t.loudness.level)}">${LV_LABELS[t.loudness.level]}</div></div>
        <div class="cell"><div class="k">Distress effect</div><div class="v lv-${esc(t.distress.level)}">${LV_LABELS[t.distress.level]}</div></div>
        <div class="cell"><div class="k">Cost (approx.)</div><div class="v">${esc(av.cost || 'Unknown')}</div></div>
        <div class="cell"><div class="k">Confidence</div><div class="v"><span class="badge ${conf[0]}">${conf[1]}</span></div></div>
        <div class="cell"><div class="k">Best suited for</div><div class="v small">${esc(t.bestSuitedFor || '—')}</div></div>
        <div class="cell"><div class="k">Developer</div><div class="v small">${esc(t.developer || '—')}</div></div>
        <div class="cell"><div class="k">Last reviewed</div><div class="v small">${fmtDate(t.lastReviewed)}</div></div>
        <div class="cell"><div class="k">Studies tracked</div><div class="v small">${(t.studies || []).length}</div></div>
      </div>

      <div class="prose">
        <h2>What it is</h2><p>${esc(t.whatItIs)}</p>
        <h2>How it works</h2><p>${esc(t.howItWorks)}</p>

        <h2>Does it make tinnitus quieter — or easier to live with?</h2>
        <p class="small muted">These are different outcomes. Loudness = the sound itself is reduced.
        Distress = the reaction to it improves (THI/TFI, anxiety, sleep, quality of life).</p>
        ${duo(t, false)}

        <h2>Clinical evidence</h2>
        <p><strong>Why this score:</strong> ${esc(t.scoreRationale)}</p>
        ${(t.studies || []).map(id => studyBlock(DB.sById[id])).join('') || '<p class="muted">No studies recorded yet.</p>'}

        <h2>Safety</h2><p>${esc(t.safety)}</p>

        ${(t.limitations || []).length ? `<h2>Limitations & open questions</h2><ul>${t.limitations.map(l => `<li>${esc(l)}</li>`).join('')}</ul>` : ''}
        ${t.conflicts ? `<div class="notice">⚠ <strong>Conflicts of interest:</strong> ${esc(t.conflicts)}</div>` : ''}

        <h2>Availability</h2>
        <ul>
          <li><strong>USA:</strong> ${esc(av.usa || 'Unknown')}</li>
          <li><strong>Europe:</strong> ${esc(av.europe || 'Unknown')}</li>
          ${av.other ? `<li><strong>Elsewhere:</strong> ${esc(av.other)}</li>` : ''}
          <li><strong>Prescription / specialist:</strong> ${av.prescription ? 'Yes' : 'No'}</li>
          <li><strong>Approximate cost:</strong> ${esc(av.cost || 'Unknown')}</li>
        </ul>
        <p class="small muted">Regulatory detail: ${esc(t.regulatory.detail)}
          ${t.regulatory.sourceUrl ? ` <a href="${esc(t.regulatory.sourceUrl)}" rel="noopener" target="_blank">Source ↗</a>` : ''}</p>

        ${(t.timeline || []).length ? `<h2>Research timeline</h2><ul class="timeline">${t.timeline.map(ev => `<li><b>${esc(ev.year)}</b> — ${esc(ev.event)}</li>`).join('')}</ul>` : ''}

        ${(t.latest || []).length ? `<h2>Latest developments</h2>${t.latest.map(l =>
          `<div class="week-item"><div class="t">${fmtDate(l.date)}</div><div class="small">${esc(l.text)}
           ${l.url ? ` <a href="${esc(l.url)}" rel="noopener" target="_blank">Source ↗</a>` : ''}</div></div>`).join('')}` : ''}

        ${(t.history || []).length ? `<h2>Change history</h2>${t.history.map(h =>
          `<div class="week-item" style="--w-c:var(--c-watch)"><div class="t">${fmtDate(h.date)} — ${esc(h.change)}</div><div class="small muted">${esc(h.reason)}</div></div>`).join('')}` : ''}

        <h2>Sources</h2>
        <ul class="small">${(t.studies || []).map(id => { const s = DB.sById[id]; return s ? `<li>${esc(s.authors)} — <a href="${esc(s.url)}" rel="noopener" target="_blank">${esc(s.title)}</a> (${esc(s.journal)}, ${esc(s.year)})</li>` : ''; }).join('')}
        ${(t.extraSources || []).map(s => `<li><a href="${esc(s.url)}" rel="noopener" target="_blank">${esc(s.title)}</a></li>`).join('')}</ul>

        <p class="small muted">Last reviewed ${fmtDate(t.lastReviewed)} · evidence included through ${fmtDate(t.evidenceThrough)} ·
        tinnitus subtypes studied: ${esc((t.subtypes || []).join(', ') || 'not specified')}</p>
      </div>`;

    $('#watch').addEventListener('click', function () {
      const on = wlToggle(t.id);
      this.setAttribute('aria-pressed', on);
      $('span:last-child', this).textContent = on ? 'On your watchlist' : 'Add to watchlist';
    });
  };

  function studyBlock(s) {
    if (!s) return '';
    const res = s.results || {};
    return `<div class="study">
      <div class="t">${esc(s.title)}</div>
      <div class="meta">${esc(s.authors)} · ${esc(s.journal)} · ${esc(s.year)}
        ${s.n ? ` · N=${esc(s.n)}` : ''}${s.design ? ` · ${esc(s.design)}` : ''}</div>
      <div class="res">${esc(res.summary || '')}</div>
      <details class="rdetail"><summary>Research detail</summary>
        <ul class="small">
          ${s.control ? `<li><strong>Control:</strong> ${esc(s.control)}</li>` : ''}
          ${s.blinding ? `<li><strong>Blinding:</strong> ${esc(s.blinding)}</li>` : ''}
          ${s.duration ? `<li><strong>Treatment duration:</strong> ${esc(s.duration)}</li>` : ''}
          ${s.followUp ? `<li><strong>Follow-up:</strong> ${esc(s.followUp)}</li>` : ''}
          ${s.primaryOutcome ? `<li><strong>Primary outcome:</strong> ${esc(s.primaryOutcome)}</li>` : ''}
          ${res.detail ? `<li><strong>Results:</strong> ${esc(res.detail)}</li>` : ''}
          ${s.limitations ? `<li><strong>Limitations:</strong> ${esc(s.limitations)}</li>` : ''}
          ${s.coi ? `<li><strong>Funding / conflicts:</strong> ${esc(s.coi)}</li>` : ''}
        </ul>
      </details>
      <div class="flags">
        ${s.randomized ? '<span class="tag">Randomized</span>' : '<span class="tag">Not randomized</span>'}
        ${s.sham ? '<span class="tag">Sham/placebo-controlled</span>' : ''}
        ${s.independent ? '<span class="tag">Independent</span>' : '<span class="tag">Manufacturer-involved</span>'}
        <a class="tag" href="${esc(s.url)}" rel="noopener" target="_blank">${s.pmid ? 'PubMed' : s.doi ? 'DOI' : 'Source'} ↗</a>
      </div></div>`;
  }

  /* ----- compare ----- */
  PAGES.compare = function () {
    const sel = new Set((qs('ids') || '').split(',').filter(id => DB.tById[id]));
    const chipsEl = $('#cmp-chips'), out = $('#cmp-out');
    chipsEl.innerHTML = DB.treatments.slice().sort((a, b) => a.name.localeCompare(b.name))
      .map(t => `<button class="chip" data-id="${esc(t.id)}">${esc(t.name)}</button>`).join('');

    function render() {
      $$('.chip', chipsEl).forEach(c => c.setAttribute('aria-pressed', sel.has(c.dataset.id)));
      const list = Array.from(sel).map(id => DB.tById[id]);
      const q = list.length ? '?ids=' + list.map(t => t.id).join(',') : '';
      history.replaceState(null, '', SINGLE ? ('#/compare' + q) : ('compare.html' + q));
      if (list.length < 2) { out.innerHTML = '<div class="empty">Pick 2–4 treatments above to compare them side by side.</div>'; return; }
      const av = t => t.availability || {};
      const row = (label, fn) => `<tr><td>${label}</td>${list.map(t => `<td>${fn(t)}</td>`).join('')}</tr>`;
      out.innerHTML = `<div class="cmp-scroll"><table class="cmp">
        <thead><tr><th></th>${list.map(t => `<th><a href="treatment.html?id=${esc(t.id)}">${esc(t.name)}</a></th>`).join('')}</tr></thead>
        <tbody>
        ${row('Evidence score', t => emeter(t.evidenceScore))}
        ${row('Tier', t => tierBadge(t.tier))}
        ${row('Category', t => esc((DB.catById[t.category] || {}).name || ''))}
        ${row('Mechanism', t => esc(t.mechanism))}
        ${row('Loudness effect', t => `<span class="lv-${esc(t.loudness.level)}" style="font-weight:600">${LV_LABELS[t.loudness.level]}</span><div class="small muted">${esc(t.loudness.summary)}</div>`)}
        ${row('Distress effect', t => `<span class="lv-${esc(t.distress.level)}" style="font-weight:600">${LV_LABELS[t.distress.level]}</span><div class="small muted">${esc(t.distress.summary)}</div>`)}
        ${row('Best result reported', t => esc(t.bestResult || '—'))}
        ${row('Safety', t => esc(t.safety))}
        ${row('Regulatory status', t => esc(t.regulatory.status))}
        ${row('Available now', t => av(t).availableNow ? '✅ Yes' : '—')}
        ${row('Approx. cost', t => esc(av(t).cost || 'Unknown'))}
        ${row('Studies tracked', t => (t.studies || []).length)}
        ${row('Overall', t => esc(t.scoreRationale))}
        </tbody></table></div>`;
    }
    chipsEl.addEventListener('click', e => {
      const b = e.target.closest('.chip'); if (!b) return;
      if (sel.has(b.dataset.id)) sel.delete(b.dataset.id);
      else if (sel.size >= 4) return; else sel.add(b.dataset.id);
      render();
    });
    render();
  };

  /* ----- trials ----- */
  PAGES.trials = function () {
    const state = { status: '', phase: '', q: '' };
    const list = () => {
      let l = DB.trials.slice();
      if (state.status) l = l.filter(t => new RegExp(state.status, 'i').test(t.status));
      if (state.phase) l = l.filter(t => (t.phase || '').includes(state.phase));
      if (state.q) { const q = state.q.toLowerCase(); l = l.filter(t => (t.title + ' ' + t.sponsor + ' ' + t.nctId).toLowerCase().includes(q)); }
      l.sort((a, b) => (b.watch ? 1 : 0) - (a.watch ? 1 : 0));
      return l;
    };
    function render() {
      $$('#trial-chips .chip').forEach(c => {
        const k = c.dataset.k, v = c.dataset.v;
        c.setAttribute('aria-pressed', state[k] === v);
      });
      const l = list();
      $('#trlist').innerHTML = l.length ? l.map(trialCard).join('') : '<div class="empty">No trials match.</div>';
    }
    $('#trial-chips').addEventListener('click', e => {
      const b = e.target.closest('.chip'); if (!b) return;
      const k = b.dataset.k;
      state[k] = state[k] === b.dataset.v ? '' : b.dataset.v;
      render();
    });
    $('#trsearch').addEventListener('input', e => { state.q = e.target.value.trim(); render(); });
    render();
  };

  /* ----- research (weekly) ----- */
  PAGES.research = function () {
    const file = qs('week');
    const renderReport = rep => {
      $('#rep').innerHTML = `
        <h2 style="margin-top:10px">Week of ${fmtDate(rep.date)}</h2>
        ${rep.headline ? `<div class="card" style="border-left:4px solid var(--c-promising)"><div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">Most important this week</div>
          <h3>${esc(rep.headline.title)}</h3><p class="small">${esc(rep.headline.summary)}</p>
          ${rep.headline.url ? `<a class="small" href="${esc(rep.headline.url)}" rel="noopener" target="_blank">Source ↗</a>` : ''}</div>` : ''}
        ${rep.items.map(weekItem).join('')}`;
    };
    if (file) {
      if (SINGLE && DB.weeklyAll) renderReport(DB.weeklyAll[file] || DB.weekly);
      else fetch('data/weekly/' + file).then(r => r.json()).then(renderReport);
    } else if (DB.weekly) renderReport(DB.weekly);
    $('#archive').innerHTML = DB.weeklyIndex.reports.map(r =>
      `<li><a href="research.html?week=${esc(r.file)}">${fmtDate(r.date)}</a> — ${esc(r.title)}</li>`).join('');
  };

  /* ----- institutions ----- */
  PAGES.institutions = function () {
    $('#inst').innerHTML = DB.institutions.map(i => `<div class="card">
      <h3>${esc(i.name)}</h3><p class="small muted" style="margin-top:-4px">${esc(i.location)}</p>
      <p class="small">${esc(i.focus)}</p>
      ${(i.researchers || []).length ? `<p class="small"><strong>Key researchers:</strong> ${i.researchers.map(esc).join(', ')}</p>` : ''}
      ${(i.treatments || []).length ? `<p class="small"><strong>Related treatments:</strong> ${i.treatments.map(id => DB.tById[id] ? `<a href="treatment.html?id=${esc(id)}">${esc(DB.tById[id].name)}</a>` : '').filter(Boolean).join(' · ')}</p>` : ''}
      ${i.url ? `<a class="small" href="${esc(i.url)}" rel="noopener" target="_blank">Website ↗</a>` : ''}
    </div>`).join('');
  };

  /* ----- watchlist ----- */
  PAGES.watchlist = function () {
    const ids = wlGet();
    const root = $('#wl');
    if (!ids.length) {
      root.innerHTML = `<div class="empty">Your watchlist is empty.<br><br>
        Follow treatments you care about and this page will highlight new research about them.<br><br>
        <a class="btn btn-primary" href="treatments.html">Browse treatments</a></div>`;
      return;
    }
    let lastSeen = 0; try { lastSeen = +localStorage.getItem(SEEN_KEY) || 0; } catch (e) {}
    root.innerHTML = ids.map(id => {
      const t = DB.tById[id]; if (!t) return '';
      const fresh = (t.latest || []).filter(l => new Date(l.date).getTime() > lastSeen);
      return `<div class="card">
        ${fresh.length ? `<span class="badge b-strong" style="margin-bottom:8px">🔔 New research available</span>` : ''}
        ${treatmentCard(t).replace('class="card tcard"', 'class="tcard"')}
        ${fresh.map(l => `<div class="week-item"><div class="t small">${fmtDate(l.date)}</div><div class="small">${esc(l.text)}</div></div>`).join('')}
        <button class="btn small" data-unwatch="${esc(id)}" type="button">Remove</button>
      </div>`;
    }).join('');
    root.onclick = e => { // assignment, not addEventListener: re-renders must not stack handlers
      const b = e.target.closest('[data-unwatch]');
      if (b) { wlToggle(b.dataset.unwatch); PAGES.watchlist(); }
    };
    try { localStorage.setItem(SEEN_KEY, Date.now()); } catch (e) {}
  };

  /* ----- about ----- */
  PAGES.about = function () {
    $('#about-meta').textContent = 'Database last fully reviewed ' + fmtDate(DB.meta.lastFullReview) +
      ' · evidence included through ' + fmtDate(DB.meta.evidenceThrough) + '.';
  };

  /* ---------------- single-file router ---------------- */
  function setFootMeta() {
    const fm = $('#foot-meta');
    if (fm) fm.textContent = `Database: ${DB.treatments.length} treatments · ${DB.studies.length} studies · ${DB.trials.length} trials · last full review ${fmtDate(DB.meta.lastFullReview)}. Nothing publishes without human review.`;
  }
  let pendingAnchor = null;
  function renderRoute() {
    const raw = (location.hash || '#/').replace(/^#\/?/, '');
    let page = (raw.split('?')[0] || 'index').replace(/\.html$/, '') || 'index';
    if (!document.getElementById('page-' + page)) page = 'index';
    document.body.dataset.page = page;
    document.title = ((DB.tById[qs('id')] || {}).name || pageTitle(page)) + ' — ' + DB.meta.name;
    $('#app').innerHTML = document.getElementById('page-' + page).innerHTML;
    chrome();
    setFootMeta();
    if (PAGES[page]) PAGES[page]();
    if (pendingAnchor) {
      const el = document.getElementById(pendingAnchor); pendingAnchor = null;
      if (el) { el.scrollIntoView(); return; }
    }
    window.scrollTo(0, 0);
  }
  function pageTitle(p) {
    return { index: 'Home', treatments: 'Treatments', treatment: 'Treatment', compare: 'Compare',
      trials: 'Clinical Trials', research: 'This Week in Research', institutions: 'Institutions',
      watchlist: 'Watchlist', about: 'About' }[p] || p;
  }
  function initRouter() {
    document.addEventListener('click', e => {
      const a = e.target.closest('a[href]');
      if (!a) return;
      const m = (a.getAttribute('href') || '').match(/^([a-z-]+)\.html(?:\?([^#]*))?(?:#(.*))?$/);
      if (!m) return;
      e.preventDefault();
      pendingAnchor = m[3] || null;
      const h = '#/' + (m[1] === 'index' ? '' : m[1]) + (m[2] ? '?' + m[2] : '');
      if (h === location.hash) renderRoute(); else location.hash = h;
    });
    addEventListener('hashchange', renderRoute);
    renderRoute();
  }

  /* ---------------- boot ---------------- */
  async function boot() {
    try {
      await load();
      if (SINGLE) { initRouter(); return; }
      chrome();
      setFootMeta();
      const page = document.body.dataset.page;
      if (PAGES[page]) PAGES[page]();
    } catch (err) {
      chrome();
      const m = document.createElement('div');
      m.className = 'wrap notice'; m.style.margin = '20px auto';
      m.textContent = 'Could not load the research database (' + err.message + '). If you opened this file directly, serve the folder over HTTP instead.';
      document.body.insertBefore(m, document.body.children[1]);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot(); // script may execute after DOMContentLoaded (single-file/artifact wrapping)
})();
