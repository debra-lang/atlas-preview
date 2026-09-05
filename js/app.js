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
    // cache:'no-cache' revalidates instead of silently serving stale weekly data
    // (never use ?v= query-busting here — the Capacitor iOS asset server can't serve query URLs)
    const get = f => fetch('data/' + f, { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(f + ' ' + r.status); return r.json(); });
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

  /* ---------------- watchlist (v2: treatments + trials + institutions) ---------------- */
  const WL_KEY = 'ta:watchlist', SEEN_KEY = 'ta:lastSeen';
  function wlGet() {
    try {
      const raw = JSON.parse(localStorage.getItem(WL_KEY));
      if (Array.isArray(raw)) return { treatments: raw, trials: [], institutions: [] }; // v1 migration
      return Object.assign({ treatments: [], trials: [], institutions: [] }, raw || {});
    } catch (e) { return { treatments: [], trials: [], institutions: [] }; }
  }
  const wlSet = wl => { try { localStorage.setItem(WL_KEY, JSON.stringify(wl)); } catch (e) {} };
  const wlHas = (kind, id) => (wlGet()[kind] || []).includes(id);
  function wlToggle(kind, id) {
    const wl = wlGet(); const l = wl[kind] = wl[kind] || [];
    const i = l.indexOf(id); i >= 0 ? l.splice(i, 1) : l.push(id); wlSet(wl); return i < 0;
  }

  /* ---------------- My Tinnitus Profile (local-only) ---------------- */
  const PROFILE_KEY = 'ta:profile';
  const getProfile = () => { try { return JSON.parse(localStorage.getItem(PROFILE_KEY)); } catch (e) { return null; } };
  const setProfile = p => { try { localStorage.setItem(PROFILE_KEY, JSON.stringify(p)); } catch (e) {} };
  const SUBTYPE_LABELS = {
    general: 'Broad / unspecified tinnitus', pulsatile: 'Pulsatile tinnitus',
    somatic: 'Somatic-modulated tinnitus', 'hearing-loss': 'With hearing loss',
    'sudden-hl': 'After sudden hearing loss', 'ci-candidate': 'Cochlear-implant candidates',
    meniere: "Meniere's disease"
  };
  const CHAR_NAMES = {
    pulsatile: 'pulsatile (heartbeat-synchronized) tinnitus',
    somatic: 'tinnitus that changes with jaw or neck movement',
    'hearing-loss': 'tinnitus with hearing loss',
    'sudden-hl': 'tinnitus after a sudden hearing drop'
  };
  function profileTags(p) {
    if (!p) return [];
    const tags = [];
    if (p.pulsatile === 'yes') tags.push('pulsatile');
    if (p.somaticModulation === 'yes' || p.jawTMJ === 'yes' || p.neck === 'yes') tags.push('somatic');
    if (p.hearingLoss === 'yes') tags.push('hearing-loss');
    if (p.suddenHL === 'yes') tags.push('sudden-hl');
    return tags; // specific tags only — 'general' matches are not meaningful
  }
  function profileMatches(t) {
    const p = getProfile(); if (!p) return [];
    const specific = profileTags(p);
    return (t.subtypeTags || []).filter(tag => specific.includes(tag));
  }
  // Red flags from AAO-HNSF CPG: Tinnitus (2014) + AAO-HNSF CPG: Sudden Hearing Loss (2019)
  function redFlags(p) {
    const f = [];
    if (p.pulsatile === 'yes') f.push('tinnitus that pulses with your heartbeat');
    if (p.suddenHL === 'yes') f.push('a sudden drop in hearing (guidelines recommend prompt evaluation for this one)');
    if (p.laterality === 'left' || p.laterality === 'right') f.push('tinnitus in one ear only');
    if (p.asymmetric === 'yes') f.push('hearing that is clearly different between ears, or recently changed');
    if (p.neuroSymptoms === 'yes') f.push('neurological symptoms alongside tinnitus');
    if (p.vertigo === 'yes') f.push('vertigo or serious dizziness');
    if (p.earPainDrainage === 'yes') f.push('ear pain or discharge');
    if (p.trauma === 'yes') f.push('a recent head or ear injury');
    return f;
  }

  /* ---------------- plain-language helpers ---------------- */
  const EVIDENCE_WORDS = { 1: 'Weak', 2: 'Limited', 3: 'Moderate', 4: 'Strong', 5: 'Very strong' };
  function effectWord(t) {
    const l = ['moderate', 'strong'].includes(t.loudness.level);
    const d = ['moderate', 'strong'].includes(t.distress.level);
    if (l && d) return 'Loudness + distress';
    if (l) return 'Loudness';
    if (d) return 'Distress';
    if (t.loudness.level === 'limited' || t.distress.level === 'limited') return 'Unclear (early signals)';
    return 'Unclear';
  }
  function availWord(t) {
    const a = t.availability || {};
    if (a.availableNow) return /some|limited|scarce|select/i.test(a.usa || '') ? 'Limited availability' : 'Available';
    if (/investigational|pre-clinical|registered/i.test((t.regulatory || {}).status || '')) return 'Clinical trials / research only';
    return 'Not yet available';
  }
  function whoStudied(t) {
    if (t.whoStudied) return t.whoStudied;
    const s = (t.subtypes || []).filter(Boolean);
    return s.length ? 'Studied primarily in people with ' + s.join('; ') : 'Studied in broad or unspecified tinnitus populations';
  }
  /* ---------- Evidence Profile visuals (no chart library; CSS marks only) ----------
     Mapping (documented in ARCHITECTURE.md + About): qualitative → 0–4 segments.
     strong=4 · moderate=3 · limited=2 · weak=1 · none=0 · missing field = "Not yet assessed"
     (hatched, NOT zero — unknown is not the same as weak). No invented percentages. */
  const SEG = { strong: 4, moderate: 3, limited: 2, weak: 1, none: 0 };
  /* Replication uses its own 5-category semantics (independent reproduction of POSITIVE findings).
     'conflicting' = replication was attempted and results disagree — rendered as its own state,
     never forced onto the positive 0–4 scale. Legacy values (strong/moderate/limited) map via SEG. */
  const REP_SEG = { 'strong-independent': 4, 'limited-independent': 2, 'same-group': 1, none: 0 };
  const REP_LABELS = {
    'strong-independent': 'Strong independent', 'limited-independent': 'Limited independent',
    'same-group': 'Same group/sponsor only', none: 'None yet', conflicting: 'Conflicting results'
  };
  const IND_LABELS = {
    'primarily-independent': 'Primarily independent', mixed: 'Mixed',
    'primarily-sponsor': 'Primarily sponsor-supported', unclear: 'Independence unclear'
  };
  const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  function segbar(n, na, total, cf) {
    total = total || 4; // evidence quality uses 5 (one segment per score point); qualitative dims use 4
    let s = '';
    for (let i = 1; i <= total; i++) s += `<i class="${cf ? 'cf' : (!na && i <= n ? 'on' : '')}"></i>`;
    return `<span class="segbar${na ? ' na' : ''}${cf ? ' conflict' : ''}" aria-hidden="true">${s}</span>`;
  }
  function epDims(t) {
    const availW = availWord(t);
    const availSeg = { 'Available': 4, 'Limited availability': 3, 'Clinical trials / research only': 1, 'Not yet available': 0 }[availW] ?? 0;
    const lv = o => ({ segs: SEG[o.level] ?? 0, word: LV_LABELS[o.level] || cap(o.level), na: false });
    return [
      { label: 'Evidence quality', segs: t.evidenceScore, total: 5, word: `${EVIDENCE_WORDS[t.evidenceScore]} (${t.evidenceScore}/5)`, na: false,
        def: 'How strong and rigorous is the underlying clinical evidence? (5 segments — one per point of the 1–5 evidence score, so 4/5 and 5/5 look different.)' },
      { label: 'Replication', segs: REP_SEG[t.replication] ?? SEG[t.replication] ?? 0,
        word: t.replication ? (REP_LABELS[t.replication] || cap(t.replication)) : 'Not yet assessed',
        na: t.replication == null, cf: t.replication === 'conflicting',
        def: 'Have INDEPENDENT groups reproduced the positive findings? Repeats by the same lab or sponsor count as "Same group/sponsor only". "Conflicting results" means replication was attempted and independent results disagree — shown as its own state, not a strength level.' },
      { label: 'Loudness evidence', ...lv(t.loudness),
        def: 'Is there evidence the tinnitus sound itself became quieter?' },
      { label: 'Distress evidence', ...lv(t.distress),
        def: 'Is there evidence tinnitus became less bothersome or quality of life improved?' },
      { label: 'Safety', segs: SEG[t.safetyLevel] ?? 0, word: t.safetyLevel ? cap(t.safetyLevel) : 'Not yet assessed', na: t.safetyLevel == null,
        def: 'What does current evidence show about tolerability and known risks?' },
      { label: 'Availability', segs: availSeg, word: availW, na: false,
        def: 'Can patients realistically access this today?' }
    ];
  }
  function evidenceProfile(t) {
    const dims = epDims(t);
    const ind = t.independence ? `<div class="eprow"><span class="lab">Independence</span><span class="segbar" style="visibility:hidden" aria-hidden="true"></span>
        <span class="val">${esc(IND_LABELS[t.independence] || cap(t.independence))}</span></div>` : '';
    const notes = [t.replicationNote && 'Replication: ' + t.replicationNote, t.independenceNote && 'Independence: ' + t.independenceNote].filter(Boolean);
    return `<div class="eprofile"><div class="k">Evidence profile</div>
      ${dims.map(d => `<div class="eprow"><span class="lab">${esc(d.label)}</span>${segbar(d.segs, d.na, d.total, d.cf)}
        <span class="val">${esc(d.word)}</span></div>`).join('')}
      ${ind}
      ${notes.length ? `<p class="small muted" style="margin:6px 0 0">${notes.map(esc).join('<br>')}</p>` : ''}
      <details><summary>What does each bar mean?</summary>
        <ul class="small">${dims.map(d => `<li><strong>${esc(d.label)}:</strong> ${esc(d.def)}</li>`).join('')}
        <li class="muted">Evidence quality shows the 1–5 score directly (one segment per point). The other bars show
        qualitative categories from the reviewed database (Strong=4 segments · Moderate=3 · Limited=2 · Weak=1 · None=0).
        A hatched bar means "not yet assessed" — unknown is not the same as weak. An amber striped Replication bar means
        "Conflicting results" — independent studies disagree, which is different from both weak and none.
        <strong>Independence</strong> states who produced the evidence: primarily independent researchers, a mix, or
        primarily the treatment's own sponsor — it does not change the scores, but it tells you how much rests on
        parties with a commercial stake.
        No percentages are shown because tinnitus studies measure different outcomes; a single "effectiveness %"
        would be scientifically misleading.</li></ul>
      </details></div>`;
  }
  function countBars(rows, opts) { // rows: [{label, n, color?, href?}] — single-hue magnitude bars + always-on labels
    const max = Math.max(1, ...rows.map(r => r.n));
    return `<div class="dchart" role="img" aria-label="${esc(opts && opts.aria || 'Counts')}: ${rows.map(r => r.label + ' ' + r.n).join(', ')}">
      ${rows.map(r => {
        const inner = `<span class="lab">${esc(r.label)}</span>
          <span class="dbar"><i style="width:${(r.n / max * 100).toFixed(1)}%${r.color ? ';--d-c:' + r.color : ''}"></i></span>
          <span class="n">${r.n}</span>`;
        return r.href ? `<a class="drow" href="${esc(r.href)}">${inner}</a>` : `<div class="drow">${inner}</div>`;
      }).join('')}</div>`;
  }
  function timelineClass(ev) { // presentation-only keyword classification — never alters evidence data
    const s = ev.toLowerCase();
    if (/fail|miss|null|negative|discontinu|dissolv|terminat|no benefit|not achieved|silen|refut/.test(s)) return 'tl-negative';
    if (/fda|cleared|authoriz|de novo|ce mark|approval|designation|diga|regulat/.test(s)) return 'tl-regulatory';
    if (/launch|commercial|spinout|spin|startup|marketing/.test(s)) return 'tl-commercial';
    if (/rating|rank|tier|audit|assessment/.test(s)) return 'tl-assessment';
    return 'tl-study';
  }
  const TL_KEY = `<div class="tl-key">
    <span><i style="background:var(--c-promising)"></i>Study</span>
    <span><i style="background:var(--c-strong)"></i>Regulatory</span>
    <span><i style="background:var(--c-weak)"></i>Negative / setback</span>
    <span><i style="background:var(--c-emerging)"></i>Commercial</span>
    <span><i style="background:var(--c-watch)"></i>Our assessment</span></div>`;

  function regExplain(status) {
    const s = (status || '').toLowerCase();
    if (s.includes('de novo')) return 'De Novo authorized = the FDA reviewed it as a brand-new device type and allowed marketing. Stronger than "cleared", weaker than full "approval".';
    if (s.includes('510(k)') || s.includes('cleared')) return 'FDA cleared (510(k)) = judged similar to an existing device. Clearance is NOT proof that it works.';
    if (s.includes('pma') || s.startsWith('fda approved')) return 'FDA approved = passed the FDA\'s strictest review (PMA) — for the indication on its label.';
    if (s.includes('off-label')) return 'Off-label = doctors may legally use an approved product for a purpose it wasn\'t originally approved for.' + (s.includes('investigational') ? ' A dedicated product for this use is still investigational (being tested).' : '');
    if (s.includes('investigational')) return 'Investigational = still being tested; not authorized for sale for this use.';
    if (s.includes('ce mark') || s.includes('ce-mark')) return 'CE marked = meets European safety requirements; for low-risk devices this is not proof of effectiveness.';
    if (s.includes('standard')) return 'An established therapy — no device/drug authorization applies.';
    if (s.includes('unregulated') || s.includes('supplement') || s.includes('wellness')) return 'No regulator has evaluated this for tinnitus at all.';
    if (s.includes('off-label')) return 'Off-label = the product is approved for something else; using it for tinnitus is at the prescriber\'s discretion.';
    return '';
  }

  /* ---------------- shared components ---------------- */
  const TIER_LABELS = {
    1: ['Strongest evidence', 'b-strong'], 2: ['Promising', 'b-promising'],
    3: ['Experimental', 'b-emerging'], 4: ['Helps you cope', 'b-watch'],
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
    return `<span class="emeter" style="--em-c:${scoreColor(score)}" title="Evidence score ${score}/5 (${EVIDENCE_WORDS[score]})"
      role="img" aria-label="Evidence score ${score} out of 5, ${EVIDENCE_WORDS[score]}">${dots}<span class="lab">${label !== false ? score + '/5 · ' + EVIDENCE_WORDS[score] : ''}</span></span>`;
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
      <p class="who">👥 ${esc(whoStudied(t))}</p>
      <div class="foot">${emeter(t.evidenceScore)} ${tierBadge(t.tier)}
        <span class="badge b-promising" title="What the evidence addresses">🎯 ${effectWord(t)}</span> ${availBadge(t)}
        ${t.narrowPopulation ? '<span class="badge b-watch" title="Results apply only to a specific diagnosed population">⚠ Specific population only</span>' : ''}</div>
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
  const NAV_MORE = [['search.html', 'Search'], ['ask/', 'Ask'], ['profile.html', 'My Profile'], ['compare.html', 'Compare'], ['research-questions/', 'Research Questions'], ['institutions.html', 'Institutions'], ['about.html', 'About']];

  function chrome() {
    $$('.topbar, .bottomnav, .footer, .footer-links').forEach(el => el.remove()); // idempotent (static footer-links block is folded into the JS footer below)
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
      <p class="small"><a href="treatments/">Tinnitus treatments</a> · <a href="trials/">Clinical trials</a> ·
      <a href="research/">Research records</a> · <a href="ask/">Ask Tinnitus Evidence</a> ·
      <a href="research-questions/">Research questions</a> ·
      <a href="guides/tinnitus-treatments/">Strongest evidence</a> ·
      <a href="guides/tinnitus-loudness-vs-distress/">Loudness vs distress</a> ·
      <a href="about.html#limitations">Research limitations</a> · <a href="about.html#corrections">Corrections &amp; editorial integrity</a></p>
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
    $('#top10').innerHTML =
      (rankings.uncertaintyNote ? `<div class="notice" style="grid-column:1/-1;margin:0 0 4px">ℹ️ <strong>How solid is this order?</strong> ${esc(rankings.uncertaintyNote)}</div>` : '') +
      rankings.top.map(r => {
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

    // Where the evidence stands (auto-computed distribution; semantic ordinal colors + always-on labels)
    const stand = $('#evstand');
    if (stand) {
      const g = s => treatments.filter(t => s(t.evidenceScore)).length;
      const loudN = treatments.filter(t => ['moderate', 'strong'].includes(t.loudness.level)).length;
      const distN = treatments.filter(t => ['moderate', 'strong'].includes(t.distress.level)).length;
      const bothN = treatments.filter(t => ['moderate', 'strong'].includes(t.loudness.level) && ['moderate', 'strong'].includes(t.distress.level)).length;
      stand.innerHTML = countBars([
        { label: 'Strong evidence (4–5/5)', n: g(s => s >= 4), color: 'var(--c-strong)' },
        { label: 'Moderate evidence (3/5)', n: g(s => s === 3), color: 'var(--c-promising)' },
        { label: 'Limited evidence (2/5)', n: g(s => s === 2), color: 'var(--c-watch)' },
        { label: 'Weak / unsupported (1/5)', n: g(s => s === 1), color: 'var(--c-weak)' }
      ], { aria: 'Treatments by evidence strength' }) +
      `<p class="small muted" style="margin:10px 0 0">Of ${treatments.length} tracked treatments,
        <a href="treatments.html?flag=loud">${loudN} have at least moderate evidence for the sound itself</a>,
        <a href="treatments.html?flag=distress">${distN} for being less bothered</a> — and only ${bothN} for both.
        Counts update automatically; the underlying classifications only change through the held-review process.</p>`;
    }

    // What hasn't worked (Tier 5, still marketed/available — the ones people spend money on)
    const neg = treatments.filter(t => t.tier === 5 && t.availability && t.availability.availableNow)
      .sort((a, b) => a.evidenceScore - b.evidenceScore).slice(0, 3);
    if ($('#negative')) $('#negative').innerHTML = neg.map(t => treatmentCard(t)).join('');

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
    return `${r.whyPlain ? `<p class="whyline"><strong>Why #${r.rank}?</strong> ${esc(r.whyPlain)}</p>` : ''}
      <details class="rdetail"><summary>Research detail — the full reasoning</summary>
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
        ${row('Ranking stability', r.stabilityNote)}
        ${row('What could change this ranking', r.couldChange)}
      </ul></details>`;
  }

  function rankedCard(t, r) {
    const cat = DB.catById[t.category] || {};
    return `<div class="card tcard" style="--cat-c:${esc(cat.color || '#888')}">
      <span class="rank">#${r.rank}</span>
      <span class="cat" style="color:${esc(cat.color || 'var(--muted)')}">${esc(cat.icon || '')} ${esc(cat.name || t.category)}</span>
      ${r.stability ? `<span class="badge ${r.stability === 'weighting-sensitive' ? 'b-watch' : 'b-strong'}" style="margin-left:4px" title="${esc(r.stabilityNote || '')}">${r.stability === 'weighting-sensitive' ? 'Weighting-sensitive' : 'Stable rank'}</span>` : ''}
      <h3>${updatedRecently(t) ? '<span class="updated-dot" title="Updated recently"></span>' : ''}<a href="treatment.html?id=${esc(t.id)}" style="color:inherit">${esc(t.name)}</a></h3>
      <p class="one">${esc(t.oneLiner)}</p>
      ${duo(t, true)}
      <div class="foot">${emeter(t.evidenceScore)} ${tierBadge(t.tier)} ${availBadge(t)}</div>
      ${whyRankingBlock(r, t)}
    </div>`;
  }

  const IMP_STYLE = {
    'Potentially Important': 'b-strong', 'Interesting but Early': 'b-emerging',
    'Confirms Previous Evidence': 'b-promising', 'Negative Result': 'b-watch',
    'Does Not Change Current Evidence': 'b-weak'
  };
  function weekItem(it) {
    const KIND_COLORS = { study: 'var(--c-promising)', trial: 'var(--c-emerging)', regulatory: 'var(--c-strong)', ranking: 'var(--c-watch)', negative: 'var(--c-weak)', news: 'var(--c-promising)' };
    const d = it.detail || {};
    const drow = (k, v) => (v && v !== 'Not reported' && (!Array.isArray(v) || v.length)) ?
      `<li><strong>${k}:</strong> ${esc(Array.isArray(v) ? v.join('; ') : v)}</li>` : '';
    return `<div class="week-item" style="--w-c:${KIND_COLORS[it.kind] || 'var(--c-promising)'}">
      ${it.importance ? `<span class="badge ${IMP_STYLE[it.importance] || 'b-weak'}" style="margin-bottom:4px">${esc(it.importance)}</span>` : ''}
      ${it.safetySignal ? `<span class="badge b-watch" style="margin-bottom:4px">⚠ Possible safety signal — read the source</span>` : ''}
      ${it.underEvaluation ? `<span class="badge b-emerging" style="margin-bottom:4px">Impact on Tinnitus Evidence rating: Under evaluation</span>` : ''}
      <div class="t">${esc(it.title)}</div>
      ${it.whyMatters ? `<div class="small"><strong>Why it matters:</strong> ${esc(it.whyMatters)}</div>` : ''}
      <details class="rdetail"><summary>Research detail</summary>
        <p class="small">${esc(it.summary)}</p>
        <ul class="small">
          ${drow('Study type', d.studyType)}${drow('Population', d.population)}${drow('Sample size', d.sampleSize)}
          ${drow('Control / comparison', d.control)}${drow('Comparison type', d.comparisonType)}
          ${drow('Primary endpoint', d.primaryEndpoint)}${drow('Secondary endpoints', d.secondaryEndpoints)}
          ${drow('🔉 Loudness outcome', d.loudnessOutcome)}${drow('🧠 Distress outcome', d.distressOutcome)}
          ${drow('Other outcomes', d.otherOutcomes)}${drow('Safety (as reported)', d.safety)}
          ${drow('Limitations', d.limitations)}${drow('Funding / conflicts', d.funding)}
          ${drow('Identifier', d.identifier)}${drow('Changes our assessment?', d.changesAssessment)}
        </ul>
        <p class="small">
        ${it.treatment && DB.tById[it.treatment] ? `<a href="treatment.html?id=${esc(it.treatment)}">${esc(DB.tById[it.treatment].name)} — full evidence page →</a><br>` : ''}
        ${it.url ? `<a href="${esc(it.url)}" rel="noopener" target="_blank">Original source ↗</a>` : ''}</p>
      </details></div>`;
  }

  function trialCard(tr, opts) {
    opts = opts || {};
    const t = tr.treatment && DB.tById[tr.treatment];
    const st = /recruit/i.test(tr.status) && !/stale/i.test(tr.status) ? 'b-strong' : /active|enrolling|ongoing/i.test(tr.status) ? 'b-promising' : /complete/i.test(tr.status) ? 'b-weak' : 'b-watch';
    const matches = t ? profileMatches(t) : [];
    return `<div class="card">
      <div class="foot" style="margin:0 0 8px;display:flex;gap:6px;flex-wrap:wrap">
        <span class="badge ${st}">${esc(tr.status)}</span>
        ${tr.phase ? `<span class="badge b-emerging">${esc(tr.phase)}</span>` : ''}
        ${tr.country ? `<span class="badge b-weak" title="Country of the lead sponsor/site">📍 ${esc(tr.country)}</span>` : ''}
        ${tr.watch ? '<span class="badge b-watch">One to watch</span>' : ''}</div>
      <h3 style="font-size:1rem">${esc(tr.title)}</h3>
      <p class="small muted">${esc(tr.sponsor)}${tr.n ? ` · aiming to enroll ${esc(tr.n)} people` : ''}${tr.completionEst ? ` · est. completion ${esc(tr.completionEst)}` : ''}</p>
      ${tr.whyItMatters ? `<p class="small">${esc(tr.whyItMatters)}</p>` : ''}
      ${opts.profileNotes && matches.length ? `<div class="match-note">👤 This study involves ${matches.map(m => esc(CHAR_NAMES[m] || m)).join(' and ')} — a characteristic in your Tinnitus Profile. Only the study's research team can determine whether anyone is eligible.</div>` : ''}
      <p class="small" style="margin-bottom:0">
        ${t ? `<a href="treatment.html?id=${esc(t.id)}">${esc(t.name)}</a> · ` : ''}
        <a href="${esc(tr.url || ('https://clinicaltrials.gov/study/' + tr.nctId))}" rel="noopener" target="_blank">${esc(tr.nctId)} ↗</a>
        ${opts.follow ? ` <button class="btn followbtn watch-btn" type="button" data-watch-trial="${esc(tr.nctId)}" aria-pressed="${wlHas('trials', tr.nctId)}">${wlHas('trials', tr.nctId) ? '⭐ Watching' : '☆ Watch this trial'}</button>` : ''}</p>
    </div>`;
  }

  /* ----- treatments browse ----- */
  PAGES.treatments = function () {
    const flagParam = qs('flag') || '';
    const state = { cat: qs('cat') || '', type: qs('type') || '', q: '',
      avail: flagParam === 'avail', loud: flagParam === 'loud', distress: flagParam === 'distress',
      negative: flagParam === 'negative', profile: flagParam === 'profile' };
    const catChips = $('#cat-chips'), listEl = $('#tlist');
    catChips.innerHTML = `<button class="chip" data-cat="">All categories</button>` +
      DB.categories.map(c => `<button class="chip" data-cat="${esc(c.id)}">${esc(c.icon)} ${esc(c.name)}</button>`).join('');
    const typeChips = $('#type-chips');
    if (typeChips) {
      const used = new Set(); DB.treatments.forEach(t => (t.subtypeTags || []).forEach(x => used.add(x)));
      typeChips.innerHTML = `<button class="chip" data-type="">Any tinnitus type</button>` +
        Object.keys(SUBTYPE_LABELS).filter(k => k !== 'general' && used.has(k))
          .map(k => `<button class="chip" data-type="${k}">${esc(SUBTYPE_LABELS[k])}</button>`).join('');
    }
    const profChip = $('[data-flag="profile"]');
    if (profChip && !getProfile()) profChip.hidden = true;

    function render() {
      $$('#cat-chips .chip').forEach(ch => ch.setAttribute('aria-pressed', ch.dataset.cat === state.cat));
      $$('#type-chips .chip').forEach(ch => ch.setAttribute('aria-pressed', ch.dataset.type === state.type));
      $$('#flag-chips .chip').forEach(ch => ch.setAttribute('aria-pressed', !!state[ch.dataset.flag]));
      let list = DB.treatments.slice();
      if (state.cat) list = list.filter(t => t.category === state.cat);
      if (state.type) list = list.filter(t => (t.subtypeTags || []).includes(state.type));
      if (state.avail) list = list.filter(t => t.availability && t.availability.availableNow);
      if (state.loud) list = list.filter(t => ['limited', 'moderate', 'strong'].includes(t.loudness.level));
      if (state.distress) list = list.filter(t => ['moderate', 'strong'].includes(t.distress.level));
      if (state.negative) list = list.filter(t => t.tier === 5);
      if (state.profile) list = list.filter(t => profileMatches(t).length);
      if (state.q) {
        const q = state.q.toLowerCase();
        list = list.filter(t => (t.name + ' ' + t.oneLiner + ' ' + t.developer + ' ' + (t.researchers || []).join(' ') + ' ' + t.mechanism).toLowerCase().includes(q));
      }
      if (state.loud) list.sort((a, b) => lvRank(b.loudness.level) - lvRank(a.loudness.level) || b.evidenceScore - a.evidenceScore);
      else list.sort((a, b) => a.tier - b.tier || b.evidenceScore - a.evidenceScore || a.name.localeCompare(b.name));
      const note =
        state.loud ? `<div class="notice" style="margin-bottom:14px">🔉 <strong>Honest note:</strong> very few treatments have credible evidence of making the tinnitus sound itself quieter — and most of those apply only to specific tinnitus types. Sorted by strength of loudness evidence; check each card's population.</div>` :
        state.negative ? `<div class="notice" style="margin-bottom:14px">These treatments have failed trials, never beat placebo, or are marketed well beyond their evidence. No judgment if you've tried them — the marketing is persuasive. The evidence just isn't.</div>` :
        state.profile ? `<div class="match-note" style="margin-bottom:14px">👤 Showing research studied in people who share characteristics with your Tinnitus Profile. This is evidence navigation, not a recommendation.</div>` : '';
      listEl.innerHTML = note + (list.length ? list.map(t => treatmentCard(t)).join('') :
        '<div class="empty">Nothing matches those filters.</div>');
      $('#tcount').textContent = list.length;
    }
    const lvRank = l => ({ strong: 3, moderate: 2, limited: 1 }[l] || 0);
    catChips.addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { state.cat = b.dataset.cat; render(); } });
    if (typeChips) typeChips.addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { state.type = b.dataset.type; render(); } });
    $('#flag-chips').addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { state[b.dataset.flag] = !state[b.dataset.flag]; render(); } });
    $('#tsearch').addEventListener('input', e => { state.q = e.target.value.trim(); render(); });
    render();
  };

  /* ----- treatment detail ----- */
  PAGES.treatment = function () {
    const t = DB.tById[qs('id')];
    const root = $('#tdetail');
    if (!t) { root.innerHTML = '<div class="empty">Treatment not found. <a href="treatments.html">Browse all treatments</a></div>'; return; }
    document.title = (t.name.toLowerCase().includes('tinnitus') ? t.name + ': Research & Evidence' : t.name + ' for Tinnitus: Research & Evidence') + ' | ' + ((DB.meta && DB.meta.name) || 'Tinnitus Evidence');
    // canonicalize the query-string view onto the static crawlable page for this treatment
    let canon = document.querySelector('link[rel="canonical"]');
    if (!canon) { canon = document.createElement('link'); canon.rel = 'canonical'; document.head.appendChild(canon); }
    canon.href = 'https://tinnitusevidence.com/treatments/' + t.id + '/';
    const md = document.querySelector('meta[name="description"]');
    if (md && t.oneLiner) md.content = ('Current evidence for ' + t.name + ' and tinnitus: ' + t.oneLiner).slice(0, 300);
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
      ${t.narrowPopulation ? `<div class="narrow-note">🎯 <strong>Applies only to a specific diagnosed tinnitus population.</strong> ${esc(t.narrowNote || '')}</div>` : ''}
      ${t.underReevaluation ? `<div class="notice" style="margin:10px 0">🔎 <strong>Evidence rating under re-evaluation${t.underReevaluation.since ? ' since ' + fmtDate(t.underReevaluation.since) : ''}.</strong>
        ${esc(t.underReevaluation.reason || '')} The rating shown is the current published assessment; it changes only when the review completes.</div>` : ''}
      ${plainBlock(t)}
      ${evidenceProfile(t)}
      ${profileRelevance(t)}
      <p><button class="btn watch-btn" type="button" id="watch" aria-pressed="${wlHas('treatments', t.id)}">⭐ <span>${wlHas('treatments', t.id) ? 'On your watchlist' : 'Add to watchlist'}</span></button>
      <a class="btn" href="compare.html?ids=${esc(t.id)}">⚖ Compare</a></p>

      ${prevNote}
      ${rEntry ? whyRankingBlock(rEntry, t) : ''}
      ${rankHistory(t)}
      <div class="snapshot" style="margin:16px 0">
        <div class="cell"><div class="k">Evidence score</div><div class="v">${emeter(t.evidenceScore)}</div></div>
        <div class="cell"><div class="k">Tier</div><div class="v">${tierBadge(t.tier)}</div></div>
        <div class="cell"><div class="k">Available now</div><div class="v">${av.availableNow ? 'Yes' : 'No'}</div></div>
        <div class="cell"><div class="k">Regulatory status</div><div class="v">${esc(t.regulatory.status)}</div>
          ${regExplain(t.regulatory.status) ? `<div class="small muted" style="margin-top:3px">${esc(regExplain(t.regulatory.status))}</div>` : ''}</div>
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
        ${fmqsBox(t)}

        ${(t.timeline || []).length ? `<h2>Research timeline</h2>${TL_KEY}<ul class="timeline">${t.timeline.map(ev => `<li class="${timelineClass(ev.event)}"><b>${esc(ev.year)}</b> — ${esc(ev.event)}</li>`).join('')}</ul>` : ''}

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
      const on = wlToggle('treatments', t.id);
      this.setAttribute('aria-pressed', on);
      $('span:last-child', this).textContent = on ? 'On your watchlist' : 'Add to watchlist';
    });
  };

  function plainBlock(t) {
    const L = { none: 'No good evidence it makes the sound itself quieter.',
      limited: 'Only weak or early signs it may affect the sound itself.',
      moderate: 'Reasonable evidence it can make the sound quieter — in the population studied.',
      strong: 'Strong evidence it can reduce or eliminate the sound — in the population studied.' };
    const D = { none: 'No good evidence it makes tinnitus less bothersome.',
      limited: 'Some early evidence it may make tinnitus less bothersome.',
      moderate: 'Reasonable evidence it helps people be less bothered by tinnitus.',
      strong: 'Strong evidence it helps people be less bothered by tinnitus.' };
    return `<div class="plain-block">
      <div class="k">In plain English</div>
      <p style="margin:.4em 0"><strong>How solid is the evidence?</strong> ${EVIDENCE_WORDS[t.evidenceScore]} (${t.evidenceScore}/5).</p>
      <p style="margin:.4em 0"><strong>🔉 The sound itself:</strong> ${L[t.loudness.level]}</p>
      <p style="margin:.4em 0"><strong>🧠 How much it bothers you:</strong> ${D[t.distress.level]}</p>
      <p style="margin:.4em 0"><strong>Can I get it?</strong> ${availWord(t)}.</p>
      <p style="margin:.4em 0 0"><strong>Who was studied?</strong> ${esc(whoStudied(t))}.</p>
    </div>`;
  }

  function profileRelevance(t) {
    const matches = profileMatches(t);
    if (!matches.length) return '';
    return `<div class="match-note">👤 <strong>Relevant to your profile:</strong> this treatment has been studied in
      people who share some characteristics with your Tinnitus Profile — specifically
      ${matches.map(m => esc(CHAR_NAMES[m] || m)).join(' and ')}. That makes the research more relevant to read,
      not a recommendation that it will work for you.</div>`;
  }

  function rankHistory(t) {
    const hist = (DB.rankings.history || []).map(h => {
      const s = (h.snapshot || []).find(x => x.id === t.id);
      return s ? { date: h.date, rank: s.rank } : null;
    }).filter(Boolean);
    if (hist.length < 2) return '';
    return `<div><div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">Ranking history</div>
      <div class="rankhist">${hist.map((h, i) => `${i ? '<span class="arrow" aria-hidden="true">→</span>' : ''}<span class="step">${fmtDate(h.date)}: #${h.rank}</span>`).join('')}</div>
      <p class="small muted" style="margin-top:2px">The rank is our platform's assessment weighing ten factors (evidence, replication, availability…) —
      rank movement reflects that assessment, not a measurement that the treatment itself got better or worse.</p></div>`;
  }

  function fmqsBox(t) {
    if (!t.fmqs || !DB.meta.relatedProduct) return '';
    const rp = DB.meta.relatedProduct;
    return `<div class="fmqs-box">
      <strong>🎧 Want to try ${esc(t.fmqs.feature)} yourself?</strong><br>
      <a href="${esc(rp.url)}" rel="noopener" target="_blank">${esc(t.fmqs.label)} → ${esc(rp.name)} ↗</a>
      <p class="small muted">This is a product link, not evidence — the evidence rating above is unaffected by it.
      ${esc(rp.disclosure)}</p>
    </div>`;
  }

  function studyBlock(s) {
    if (!s) return '';
    const res = s.results || {};
    return `<div class="study">
      ${s.integrityNotice ? `<div class="notice" style="margin-bottom:6px">⚠️ <strong>Research-integrity notice (${esc(s.integrityNotice.severity.replace(/-/g, ' '))}).</strong> ${esc(s.integrityNotice.text)}</div>` : ''}
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
      const dimRow = i => `<tr><td>${esc(epDims(list[0])[i].label)}</td>${list.map(t => { const d = epDims(t)[i];
        return `<td>${segbar(d.segs, d.na, d.total)}<div class="small" style="font-weight:600;margin-top:3px">${esc(d.word)}</div></td>`; }).join('')}</tr>`;
      out.innerHTML = `<div class="cmp-scroll"><table class="cmp">
        <thead><tr><th></th>${list.map(t => `<th><a href="treatment.html?id=${esc(t.id)}">${esc(t.name)}</a></th>`).join('')}</tr></thead>
        <tbody>
        <tr><td style="font-weight:700">Evidence profile</td>${list.map(() => '<td></td>').join('')}</tr>
        ${[0, 1, 2, 3, 4, 5].map(dimRow).join('')}
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
    const state = { status: '', phase: '', country: '', q: '' };
    // "Recruiting near me": country chips (lead sponsor/site country) added to the static chip row
    const chipsEl = $('#trial-chips');
    const countries = [...new Set(DB.trials.map(t => t.country).filter(Boolean))].sort();
    chipsEl.insertAdjacentHTML('beforeend',
      countries.map(c => `<button class="chip" data-k="country" data-v="${esc(c)}">📍 ${esc(c)}</button>`).join(''));
    const chart = $('#trchart');
    if (chart) {
      const bucket = s => /stale/i.test(s) ? 'Stale registration (needs re-check)'
        : /not yet|registered/i.test(s) ? 'Registered / not yet recruiting'
        : /recruit/i.test(s) ? 'Recruiting'
        : /active|ongoing/i.test(s) ? 'Active, not recruiting'
        : /complete/i.test(s) ? 'Completed' : 'Other';
      const counts = {};
      DB.trials.forEach(t => { const b = bucket(t.status); counts[b] = (counts[b] || 0) + 1; });
      const order = ['Recruiting', 'Active, not recruiting', 'Registered / not yet recruiting', 'Stale registration (needs re-check)', 'Completed', 'Other'];
      chart.innerHTML = `<div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">The ${DB.trials.length} trials we watch, by status</div>` +
        countBars(order.filter(k => counts[k]).map(k => ({ label: k, n: counts[k] })), { aria: 'Watched trials by status' });
    }
    const nearNote = $('#near-note');
    if (nearNote) nearNote.innerHTML = `Country shows the lead sponsor/site. For a full location search near you, use
      <a href="https://clinicaltrials.gov/search?cond=tinnitus" rel="noopener" target="_blank">ClinicalTrials.gov's tinnitus search ↗</a>
      — it lists every recruiting site worldwide.` +
      (getProfile() ? '' : ` <a href="profile.html">Build a Tinnitus Profile</a> to see which studies involve characteristics like yours.`);

    const list = () => {
      let l = DB.trials.slice();
      if (state.status) l = l.filter(t => new RegExp(state.status, 'i').test(t.status));
      if (state.phase) l = l.filter(t => (t.phase || '').includes(state.phase));
      if (state.country) l = l.filter(t => t.country === state.country);
      if (state.q) { const q = state.q.toLowerCase(); l = l.filter(t => (t.title + ' ' + t.sponsor + ' ' + t.nctId).toLowerCase().includes(q)); }
      l.sort((a, b) => (b.watch ? 1 : 0) - (a.watch ? 1 : 0));
      return l;
    };
    function render() {
      $$('#trial-chips .chip').forEach(c => c.setAttribute('aria-pressed', state[c.dataset.k] === c.dataset.v));
      const l = list();
      $('#trlist').innerHTML = l.length ? l.map(tr => trialCard(tr, { follow: true, profileNotes: true })).join('') : '<div class="empty">No trials match.</div>';
    }
    chipsEl.addEventListener('click', e => {
      const b = e.target.closest('.chip'); if (!b) return;
      const k = b.dataset.k;
      state[k] = state[k] === b.dataset.v ? '' : b.dataset.v;
      render();
    });
    $('#trlist').addEventListener('click', e => {
      const b = e.target.closest('[data-watch-trial]'); if (!b) return;
      const on = wlToggle('trials', b.dataset.watchTrial);
      b.setAttribute('aria-pressed', on);
      b.textContent = on ? '⭐ Watching' : '☆ Watch this trial';
    });
    $('#trsearch').addEventListener('input', e => { state.q = e.target.value.trim(); render(); });
    render();
  };

  /* ----- research (weekly) ----- */
  PAGES.research = function () {
    const file = qs('week');
    const renderReport = rep => {
      const impCounts = {};
      rep.items.forEach(it => { if (it.importance) impCounts[it.importance] = (impCounts[it.importance] || 0) + 1; });
      const impOrder = ['Potentially Important', 'Interesting but Early', 'Confirms Previous Evidence', 'Negative Result', 'Does Not Change Current Evidence'];
      $('#rep').innerHTML = `
        <h2 style="margin-top:10px">Week of ${fmtDate(rep.date)}</h2>
        ${Object.keys(impCounts).length ? `<div class="card" style="margin-bottom:14px">
          <div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">This edition's ${rep.items.length} updates, by importance</div>
          ${countBars(impOrder.filter(k => impCounts[k]).map(k => ({ label: k, n: impCounts[k] })), { aria: 'Updates by importance' })}
          <p class="small muted" style="margin:8px 0 0">Classifications are assigned by our automated evaluation pipeline; anything that could change an evidence rating is held for review rather than auto-applied. An activity-over-time view will appear as the archive grows.</p></div>` : ''}
        ${rep.headline ? `<div class="card" style="border-left:4px solid var(--c-promising)"><div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">Most important this week</div>
          <h3>${esc(rep.headline.title)}</h3><p class="small">${esc(rep.headline.summary)}</p>
          ${rep.headline.url ? `<a class="small" href="${esc(rep.headline.url)}" rel="noopener" target="_blank">Source ↗</a>` : ''}</div>` : ''}
        ${rep.items.map(weekItem).join('')}`;
    };
    if (file) {
      if (SINGLE && DB.weeklyAll) renderReport(DB.weeklyAll[file] || DB.weekly);
      else fetch('data/weekly/' + file, { cache: 'no-cache' }).then(r => r.json()).then(renderReport);
    } else if (DB.weekly) renderReport(DB.weekly);
    $('#archive').innerHTML = DB.weeklyIndex.reports.map(r =>
      `<li><a href="research.html?week=${esc(r.file)}">${fmtDate(r.date)}</a> — ${esc(r.title)}</li>`).join('');
  };

  /* ----- institutions ----- */
  PAGES.institutions = function () {
    const inst = $('#inst');
    inst.innerHTML = DB.institutions.map(i => `<div class="card">
      <h3>${esc(i.name)}</h3><p class="small muted" style="margin-top:-4px">${esc(i.location)}</p>
      <p class="small">${esc(i.focus)}</p>
      ${(i.researchers || []).length ? `<p class="small"><strong>Key researchers:</strong> ${i.researchers.map(esc).join(', ')}</p>` : ''}
      ${(i.treatments || []).length ? `<p class="small"><strong>Related treatments:</strong> ${i.treatments.map(id => DB.tById[id] ? `<a href="treatment.html?id=${esc(id)}">${esc(DB.tById[id].name)}</a>` : '').filter(Boolean).join(' · ')}</p>` : ''}
      <p class="small" style="margin-bottom:0">
        ${i.url ? `<a href="${esc(i.url)}" rel="noopener" target="_blank">Website ↗</a> ` : ''}
        <button class="btn followbtn watch-btn" type="button" data-follow-inst="${esc(i.id)}" aria-pressed="${wlHas('institutions', i.id)}">${wlHas('institutions', i.id) ? '⭐ Following' : '☆ Follow this group'}</button></p>
    </div>`).join('');
    inst.onclick = e => {
      const b = e.target.closest('[data-follow-inst]'); if (!b) return;
      const on = wlToggle('institutions', b.dataset.followInst);
      b.setAttribute('aria-pressed', on);
      b.textContent = on ? '⭐ Following' : '☆ Follow this group';
    };
  };

  /* ----- unified search ----- */
  PAGES.search = function () {
    const input = $('#gsearch'), out = $('#gresults');
    function rows(q) {
      q = q.toLowerCase();
      const hit = s => (s || '').toLowerCase().includes(q);
      const r = [];
      DB.treatments.forEach(t => { if (hit(t.name + ' ' + t.oneLiner + ' ' + t.mechanism + ' ' + t.developer + ' ' + (t.researchers || []).join(' ')))
        r.push(['Treatment', t.name, `treatment.html?id=${t.id}`, t.oneLiner]); });
      DB.studies.forEach(s => { if (hit(s.title + ' ' + s.authors + ' ' + s.journal))
        r.push(['Study', s.title, s.url, `${s.authors} · ${s.journal} · ${s.year}`, true]); });
      DB.trials.forEach(tr => { if (hit(tr.title + ' ' + tr.sponsor + ' ' + tr.nctId))
        r.push(['Trial', tr.title, `trials.html`, `${tr.nctId} · ${tr.sponsor} · ${tr.status}`]); });
      DB.institutions.forEach(i => { if (hit(i.name + ' ' + (i.researchers || []).join(' ') + ' ' + i.focus))
        r.push(['Institution', i.name, `institutions.html`, i.location]); });
      DB.categories.forEach(c => { if (hit(c.name + ' ' + c.blurb))
        r.push(['Category', c.name, `treatments.html?cat=${c.id}`, c.blurb]); });
      (DB.weekly ? DB.weekly.items : []).forEach(w => { if (hit(w.title + ' ' + w.summary))
        r.push(['Update', w.title, `research.html`, w.whyMatters || '']); });
      return r.slice(0, 40);
    }
    function render() {
      const q = input.value.trim();
      if (q.length < 2) { out.innerHTML = '<div class="empty">Type at least two characters.</div>'; return; }
      const r = rows(q);
      out.innerHTML = r.length ? r.map(([type, title, href, sub, ext]) =>
        `<div class="sr-row"><span class="type">${type}</span>
          <span><a href="${esc(href)}"${ext ? ' rel="noopener" target="_blank"' : ''}>${esc(title)}${ext ? ' ↗' : ''}</a>
          ${sub ? `<br><span class="small muted">${esc(sub)}</span>` : ''}</span></div>`).join('')
        : '<div class="empty">No matches across treatments, studies, trials, institutions, categories or updates.</div>';
    }
    input.addEventListener('input', render);
    render();
  };

  /* ----- My Tinnitus Profile ----- */
  PAGES.profile = function () {
    const form = $('#pform'), box = $('#redflag-box'), results = $('#p-results');
    const existing = getProfile();
    if (existing) Object.entries(existing).forEach(([k, v]) => { const el = form.elements[k]; if (el) el.value = v; });

    function renderFlags(p) {
      const flags = redFlags(p);
      box.innerHTML = flags.length ? `<div class="redflag">
        <strong>Please read this first.</strong>
        <p style="margin:.5em 0">Your answers include a characteristic that clinical guidelines recommend discussing
        with a healthcare professional: <strong>${flags.map(esc).join('; ')}</strong>.</p>
        <p class="small" style="margin:.5em 0">This does not mean something is wrong — it means these particular
        characteristics deserve a professional look (ENT physician or audiologist) before treating tinnitus as routine.
        ${p.suddenHL === 'yes' ? '<strong>A sudden drop in hearing is time-sensitive — clinical guidelines recommend seeking evaluation promptly.</strong>' : ''}</p>
        <p class="small muted" style="margin-bottom:0">Based on the AAO-HNSF Clinical Practice Guidelines for Tinnitus (2014)
        and Sudden Hearing Loss (2019). This page does not diagnose the cause.</p>
      </div>` : '';
    }

    function renderResults(p) {
      const tags = profileTags(p);
      const relevant = DB.treatments.filter(t => (t.subtypeTags || []).some(x => tags.includes(x)))
        .sort((a, b) => a.tier - b.tier || b.evidenceScore - a.evidenceScore);
      const DOMAINS = [
        ['hearing-loss', 'Hearing-loss related research'], ['somatic', 'Somatic / jaw / neck research'],
        ['pulsatile', 'Pulsatile-specific research'], ['sudden-hl', 'Sudden-hearing-loss research']];
      const trialCount = tag => DB.trials.filter(tr => tr.treatment && DB.tById[tr.treatment] &&
        (DB.tById[tr.treatment].subtypeTags || []).includes(tag)).length;
      const mapRows = DOMAINS.map(([tag, label]) => {
        const has = tags.includes(tag);
        const n = has ? DB.treatments.filter(t => (t.subtypeTags || []).includes(tag)).length : 0;
        return `<div class="eprow"><span class="lab">${esc(label)}</span>${segbar(has ? 4 : 0, !has)}
          <span class="val">${has ? `${n} pages · ${trialCount(tag)} trials` : 'Not reported'}</span></div>`;
      }).join('');
      results.innerHTML = `
        <h2 style="margin-top:20px">Research potentially relevant to your profile</h2>
        <div class="eprofile"><div class="k">Research relevance map</div>${mapRows}
          <p class="small muted" style="margin:8px 0 0"><strong>This shows research relevance — which studies involved
          people with characteristics you reported.</strong> It is NOT a measure of how likely any treatment is to work
          for you, and "Not reported" simply means you didn't report that characteristic.</p></div>
        ${tags.length ? `<p class="small muted">Matching on: ${tags.map(x => esc(CHAR_NAMES[x] || x)).join(' · ')}.
          These treatments were <em>studied</em> in people sharing those characteristics — that makes the research
          worth reading, not a recommendation.</p>
        <div class="grid grid-3" style="row-gap:22px">${relevant.map(t => treatmentCard(t)).join('')}</div>
        <p style="margin-top:12px"><a class="btn" href="treatments.html?flag=profile">See this list with filters →</a>
        <a class="btn" href="trials.html">Check clinical trials →</a></p>`
        : `<p class="small muted">Your answers don't point to a specific studied subtype, which is very common —
          most tinnitus research covers broad populations. <a href="treatments.html">Browse all treatments</a>.</p>`}`;
    }

    form.onsubmit = e => {
      e.preventDefault();
      const p = {}; Array.from(form.elements).forEach(el => { if (el.name) p[el.name] = el.value; });
      p.savedAt = new Date().toISOString();
      setProfile(p);
      renderFlags(p); renderResults(p);
      window.scrollTo(0, 0);
    };
    $('#p-export').onclick = () => {
      const p = getProfile();
      results.insertAdjacentHTML('afterbegin', `<div class="card" style="margin-top:14px"><strong>Your profile (copy and keep it anywhere):</strong>
        <pre class="small" style="white-space:pre-wrap;user-select:all">${esc(JSON.stringify(p || {}, null, 1))}</pre></div>`);
    };
    $('#p-import').onclick = () => {
      const txt = window.prompt('Paste a previously exported profile (JSON):');
      if (!txt) return;
      try { const p = JSON.parse(txt); setProfile(p); PAGES.profile(); } catch (e) { alert('That was not valid profile JSON.'); }
    };
    $('#p-delete').onclick = () => {
      try { localStorage.removeItem(PROFILE_KEY); } catch (e) {}
      form.reset(); box.innerHTML = ''; results.innerHTML = '<p class="small muted">Profile deleted from this device.</p>';
    };
    if (existing) { renderFlags(existing); renderResults(existing); }
  };

  /* ----- watchlist (treatments + trials + institutions) ----- */
  PAGES.watchlist = function () {
    const wl = wlGet();
    const root = $('#wl');
    const total = wl.treatments.length + wl.trials.length + wl.institutions.length;
    if (!total) {
      root.innerHTML = `<div class="empty">Your watchlist is empty.<br><br>
        Follow treatments, clinical trials or research groups, and this page will highlight news about them.<br><br>
        <a class="btn btn-primary" href="treatments.html">Browse treatments</a>
        <a class="btn" href="trials.html">Browse trials</a></div>`;
      return;
    }
    let lastSeen = 0; try { lastSeen = +localStorage.getItem(SEEN_KEY) || 0; } catch (e) {}
    let html = '';
    html += wl.treatments.map(id => {
      const t = DB.tById[id]; if (!t) return '';
      const fresh = (t.latest || []).filter(l => new Date(l.date).getTime() > lastSeen);
      return `<div class="card">
        ${fresh.length ? `<span class="badge b-strong" style="margin-bottom:8px">🔔 New research available</span>` : ''}
        ${treatmentCard(t).replace('class="card tcard"', 'class="tcard"')}
        ${fresh.map(l => `<div class="week-item"><div class="t small">${fmtDate(l.date)}</div><div class="small">${esc(l.text)}</div></div>`).join('')}
        <button class="btn small" data-unwatch="treatments" data-id="${esc(id)}" type="button">Remove</button>
      </div>`;
    }).join('');
    html += wl.trials.map(nct => {
      const tr = DB.trials.find(x => x.nctId === nct); if (!tr) return '';
      return `<div class="card">${trialCard(tr)}
        <button class="btn small" data-unwatch="trials" data-id="${esc(nct)}" type="button" style="margin-top:8px">Remove</button></div>`;
    }).join('');
    html += wl.institutions.map(iid => {
      const i = DB.institutions.find(x => x.id === iid); if (!i) return '';
      return `<div class="card"><h3>${esc(i.name)}</h3><p class="small">${esc(i.focus)}</p>
        <button class="btn small" data-unwatch="institutions" data-id="${esc(iid)}" type="button">Remove</button></div>`;
    }).join('');
    root.innerHTML = html;
    root.onclick = e => { // assignment, not addEventListener: re-renders must not stack handlers
      const b = e.target.closest('[data-unwatch]');
      if (b) { wlToggle(b.dataset.unwatch, b.dataset.id); PAGES.watchlist(); }
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
    if (fm) fm.textContent = `Database: ${DB.treatments.length} treatments · ${DB.studies.length} studies · ${DB.trials.length} trials · last full review ${fmtDate(DB.meta.lastFullReview)}. Routine updates publish automatically after source verification; evidence ratings, rankings and safety assessments never change automatically.`;
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
      watchlist: 'Watchlist', about: 'About', search: 'Search', profile: 'My Tinnitus Profile' }[p] || p;
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
