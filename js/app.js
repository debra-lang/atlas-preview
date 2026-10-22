/* Tinnitus Atlas — app.js: data layer + shared chrome + page renderers.
   All pages render from /data/*.json. No frameworks, no build step. */

/* Google tag (gtag.js) — GA4, Measurement ID G-0EJFE7M8MQ.
   Loaded from the shared bundle so every page carrying the site chrome gets
   it exactly once (guarded); production-only so localhost, the github.io
   mirror and single-file preview builds never pollute the data. 404.html
   (no app.js) carries the same guarded snippet inline. */
(function () {
  if (window.__teGa) return;
  var h = location.hostname;
  if (h !== 'tinnitusevidence.com' && h !== 'www.tinnitusevidence.com') return;
  window.__teGa = true;
  var s = document.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=G-0EJFE7M8MQ';
  document.head.appendChild(s);
  window.dataLayer = window.dataLayer || [];
  function gtag(){ dataLayer.push(arguments); }
  window.gtag = gtag;
  gtag('js', new Date());

  gtag('config', 'G-0EJFE7M8MQ');
})();

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
  // Polite status announcements for results that change without a page load (WCAG 4.1.3). One shared visually hidden live
  // region; messages are ignored until the visitor has interacted, so nothing is spoken on first load.
  let __announceTimer, __userActed = false;
  ['pointerdown', 'keydown'].forEach(ev => addEventListener(ev, () => { __userActed = true; }, { once: true, capture: true }));
  function announce(msg) {
    if (!__userActed) return;
    let el = document.getElementById('a11y-status');
    if (!el) return;
    clearTimeout(__announceTimer);
    __announceTimer = setTimeout(() => { el.textContent = ''; setTimeout(() => { el.textContent = msg; }, 50); }, 350);
  }
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

  /* ---------------- Tinnitus Claims cross-links (private V14) ----------------
     The interactive treatment page lists the claim checks that mention a treatment. Loaded lazily and
     non-blocking: if data/claims.json is unavailable the page is unchanged. Static pages get the same block at build time. */
  let CLAIMS = null;
  async function loadClaims() {
    if (CLAIMS) return CLAIMS;
    try {
      if (window.__TA_DATA__ && window.__TA_DATA__.claims) CLAIMS = window.__TA_DATA__.claims;
      else {
        const r = await fetch('data/claims.json', { cache: 'no-cache' });
        if (!r.ok) return null;
        CLAIMS = await r.json();
      }
    } catch (e) { return null; }
    return CLAIMS;
  }
  function attachClaimChecks(root, id) {
    loadClaims().then(C => {
      if (!C || !root.isConnected) return;
      const sym = { supported: '✓', partly: '◐', misleading: '!', unsupported: '✕', insufficient: '?' };
      const cls = Object.fromEntries((C.verdicts || []).map(v => [v.name, v.cls]));
      const hits = (C.claims || []).filter(c => ((c.related || {}).treatments || []).includes(id));
      if (!hits.length || root.querySelector('.cl-xlink')) return;
      const box = document.createElement('section');
      box.className = 'card sec-card cl-xlink'; box.id = 'claim-checks';
      box.innerHTML = '<h2>Claim checks that mention this treatment</h2><ul>' + hits.map(c => {
        const k = cls[c.verdict] || 'insufficient';
        return '<li><a href="claims/' + esc(c.slug) + '/">' + esc(c.question) + '</a> <span class="cl-chip cl-' + k + '"><span aria-hidden="true">' +
          sym[k] + '</span> ' + esc(c.verdict) + '</span></li>';
      }).join('') + '</ul><p class="small muted">From <a href="claims/">Tinnitus Claims: Fact vs. Evidence</a>, which checks popular claims against the research. It does not change this treatment’s evidence rating.</p>';
      root.appendChild(box);
    });
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
    return 'Not currently available';
  }
  function whoStudied(t) {
    if (t.whoStudied) return t.whoStudied;
    const s = (t.subtypes || []).filter(Boolean);
    if (s.some(x => /^to be defined/i.test(x))) return 'Target population not yet defined';
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
    const availSeg = { 'Available': 4, 'Limited availability': 3, 'Clinical trials / research only': 1, 'Not currently available': 0 }[availW] ?? 0;
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
    const ind = t.independence ? `<div class="eprow"><span class="lab">Independence</span><span class="segbar hide" style="visibility:hidden" aria-hidden="true"></span>
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
    if (s.includes('de novo')) return 'De Novo authorized = the FDA allowed marketing of a new type of lower-risk device that had no similar device to compare with. It is a different route from clearance or approval, not a ranking of how well it works.';
    if (s.includes('510(k)') || s.includes('cleared')) return 'FDA cleared (510(k)) = judged similar to an existing device. Clearance is NOT proof that it works.';
    if (s.includes('pma') || s.startsWith('fda approved')) return 'FDA approved = passed the FDA\'s strictest review (PMA) — for the indication on its label.';
    if (s.includes('off-label')) return 'Off-label = doctors may legally use an approved product for a purpose it wasn\'t originally approved for.' + (s.includes('investigational') ? ' A dedicated product for this use is still investigational (being tested).' : '');
    if (s.includes('investigational')) return 'Investigational = still being tested; not authorized for sale for this use.';
    if (s.includes('ce mark') || s.includes('ce-mark')) return 'CE marked = meets European safety requirements; for low-risk devices this is not proof of effectiveness.';
    if (s.includes('standard')) return 'An established therapy — no device/drug authorization applies.';
    if (s.includes('unregulated') || s.includes('supplement') || s.includes('wellness') || s.includes('no tinnitus-specific authorization')) return 'Not authorized as a tinnitus treatment. Products of this kind are generally sold without a regulator reviewing whether they work for tinnitus.';
    if (s.includes('off-label')) return 'Off-label = the product is approved for something else; using it for tinnitus is at the prescriber\'s discretion.';
    return '';
  }

  /* ---------------- shared components ---------------- */
  const TIER_LABELS = {
    1: ['Strongest evidence', 'b-strong'], 2: ['Promising', 'b-promising'],
    3: ['Experimental', 'b-emerging'], 4: ['Supportive', 'b-watch'],
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
      : '<span class="badge b-emerging">Not currently available</span>';
  }
  function updatedRecently(t, days) {
    const cutoff = Date.now() - (days || 45) * 864e5;
    return (t.latest || []).some(l => new Date(l.added || l.date) >= cutoff);   // 'added' (optional) = the day the entry reached the site, for entries whose own date is older or month-only
  }

  function treatmentCard(t, opts) {
    opts = opts || {};
    const cat = DB.catById[t.category] || {};
    return `<div class="card tcard" style="--cat-c:${esc(cat.color || '#888')}">
      <div class="rhead">${opts.rank ? `<span class="rank">#${opts.rank}</span>` : ''}
        <span class="cat" style="${catVars(cat.color)}">${esc(cat.icon || '')} ${esc(cat.name || t.category)}</span>${opts.top10 ? `<span class="top10-chip" title="Ranked #${opts.top10} in the homepage Top 10 most promising developments"><b>#${opts.top10}</b> Top 10</span>` : ''}</div>
      <h3>${updatedRecently(t) ? '<span class="updated-dot" title="Updated recently"></span>' : ''}<a href="treatment.html?id=${esc(t.id)}">${esc(t.name)}</a></h3>
      <p class="one">${esc(t.oneLiner)}</p>
      ${duo(t, true)}
      <div class="foot">${emeter(t.evidenceScore)} ${availBadge(t)}</div>
      <details class="rmore" open>
        <summary>More details</summary>
        <div class="foot" style="margin:0 0 4px">${tierBadge(t.tier)}
          <span class="badge b-promising" title="What the evidence addresses">🎯 ${effectWord(t)}</span>
          ${t.narrowPopulation ? '<span class="badge b-watch" title="Results apply only to a specific diagnosed population">⚠ Specific population only</span>' : ''}</div>
        <p class="who">👥 ${esc(whoStudied(t))}</p>
      </details>
    </div>`;
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

  // Before the database has loaded (multi-page first paint) the brand comes from the page itself:
  // og:site_name, else the "… | Brand" / "… — Brand" tail of the document title.
  function brandFromDocument() {
    const og = document.querySelector('meta[property="og:site_name"]');
    if (og && og.content) return og.content;
    const m = document.title.match(/(?:\||—|–)\s*([^|—–]+)$/);
    return m ? m[1].trim() : 'Tinnitus Atlas';
  }
  // Accordion headers (details.sec > summary) hold a title, helper text and a "+" in one row. At very large text sizes on narrow
  // screens that row cannot fit, so it is allowed to wrap, but only then: at normal sizes the layout is untouched.
  function fitSummaries() {
    document.querySelectorAll('details.sec > summary').forEach(s => {
      s.classList.remove('wrap-fit');
      if (s.scrollWidth > s.clientWidth + 1 || [...s.children].some(c => c.scrollWidth > c.clientWidth + 1)) s.classList.add('wrap-fit');
    });
  }
  let __fitTimer;
  const scheduleFit = () => { clearTimeout(__fitTimer); __fitTimer = setTimeout(fitSummaries, 120); };
  addEventListener('resize', scheduleFit);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(scheduleFit);
  // Category labels: each colour is pulled toward the text colour (darker in the light theme, lighter in the dark theme) only as far as
  // needed to reach 4.5:1 on the page surfaces and the tinted card washes (the darkest and lightest backdrops measured behind the labels), so every category keeps as much of its own colour as possible (WCAG 1.4.3).
  const CAT_CACHE = {};
  function catVars(color) {
    const c = String(color || '');
    if (!/^#[0-9a-f]{6}$/i.test(c)) return `--cat-c:${esc(c || 'var(--muted)')}`;
    if (CAT_CACHE[c]) return CAT_CACHE[c];
    const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
    const lin = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
    const lum = a => .2126 * lin(a[0]) + .7152 * lin(a[1]) + .0722 * lin(a[2]);
    const cr = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
    const share = (text, surfaces) => {
      const base = rgb(c), t = rgb(text);
      for (let s = 100; s >= 30; s -= 2) {
        const m = base.map((v, i) => Math.round(v * s / 100 + t[i] * (100 - s) / 100));
        if (surfaces.every(b => cr(m, rgb(b)) >= 4.7)) return s;
      }
      return 30;
    };
    return CAT_CACHE[c] = `--cat-c:${c};--cat-sl:${share('#151a2b', ['#f5f7fc', '#eef2fa', '#ffffff', '#f5dfe5'])}%;--cat-sd:${share('#e8ecf7', ['#0c1120', '#141b30', '#1b2340', '#143146', '#281e35'])}%`;
  }
  function chrome() {
    $$('.topbar, .featnav, .bottomnav, .footer, .footer-links').forEach(el => el.remove()); // idempotent (static footer-links block is folded into the JS footer below)
    const brand = (DB && DB.meta && DB.meta.name) || brandFromDocument();
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
    // the skip link must stay the first Tab stop: place the header after it, not before (WCAG 2.4.1)
    const skipLink = document.querySelector('.skip-link');
    if (skipLink && skipLink.parentNode === document.body) skipLink.after(top); else document.body.prepend(top);
    // Pre-rendered sub-pages carry <base href>, which makes a bare "#content" point at the home page. Aim the skip link at this page
    // and move focus ourselves so it works everywhere (WCAG 2.4.1).
    if (skipLink && !skipLink.dataset.bound) {
      skipLink.dataset.bound = '1';
      skipLink.href = location.href.split('#')[0] + '#content';
      skipLink.addEventListener('click', e => {
        const t = document.getElementById('content'); if (!t) return;
        e.preventDefault(); t.focus({ preventScroll: true }); t.scrollIntoView();
      });
    }
    if (!document.getElementById('a11y-status')) {
      const st = document.createElement('div');
      st.id = 'a11y-status'; st.className = 'sr-only'; st.setAttribute('role', 'status'); st.setAttribute('aria-live', 'polite'); st.setAttribute('aria-atomic', 'true');
      document.body.appendChild(st);
    }
    // make the skip-link target programmatically focusable so activating the link moves focus (not just scroll position)
    const mainEl = document.getElementById('content');
    if (mainEl && !mainEl.hasAttribute('tabindex')) mainEl.setAttribute('tabindex', '-1');
    // featured evidence navigation: second row (desktop) / compact strip (phones). aria-current="page" on a section's
    // landing page, "true" on pages inside the section (e.g. a Claims article).
    const inSec = k => page === k || page.startsWith(k + '/') || (!SINGLE && new RegExp('/' + k + '(/|$)').test(location.pathname));
    const isTop = k => page === k || (!SINGLE && new RegExp('/' + k + '/?(index\\.html)?$').test(location.pathname));
    const feat = document.createElement('nav');
    feat.className = 'featnav'; feat.setAttribute('aria-label', 'Featured evidence sections');
    feat.innerHTML = '<div class="featnav-in">' + [['emerging-unproven/', 'Emerging Treatments', 'feat-em', 'emerging-unproven'], ['claims/', 'Claims: Fact vs. Evidence', 'feat-cl', 'claims']].map(([h, n, c, k]) =>
      `<a class="feat ${c}" href="${h}"${isTop(k) ? ' aria-current="page"' : inSec(k) ? ' aria-current="true"' : ''}><span class="dot" aria-hidden="true"></span><span>${n}</span></a>`).join('') + '</div>';
    top.after(feat);
    const sizeHeader = () => {
      const r = document.documentElement.style, t = top.offsetHeight;
      r.setProperty('--tb-h', t + 'px');
      r.setProperty('--hdr-h', (t + (getComputedStyle(feat).position === 'sticky' ? feat.offsetHeight : 0)) + 'px');
    };
    sizeHeader();
    if (!window.__featNavResize) { window.__featNavResize = true; addEventListener('resize', () => { const f = $('.featnav'), t = $('.topbar'); if (f && t) { const r = document.documentElement.style; r.setProperty('--tb-h', t.offsetHeight + 'px'); r.setProperty('--hdr-h', (t.offsetHeight + (getComputedStyle(f).position === 'sticky' ? f.offsetHeight : 0)) + 'px'); } }); }
    const themeBtn = $('.theme-btn', top);
    themeBtn.setAttribute('aria-pressed', String(document.documentElement.dataset.theme === 'dark'));   // announces the state, not only the action
    themeBtn.addEventListener('click', () => {
      const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      applyTheme(t); try { localStorage.setItem(THEME_KEY, t); } catch (e) {}
      themeBtn.setAttribute('aria-pressed', String(t === 'dark'));
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
      <a href="emerging-unproven/">Emerging, experimental &amp; unproven treatments</a> ·
      <a href="claims/">Tinnitus claims: fact vs. evidence</a> ·
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
    // "latest automated research scan" = date of the newest weekly report; the separate
    // full-review date (meta.lastFullReview) is still shown in the footer and on About
    const lastScan = (DB.weeklyIndex && DB.weeklyIndex.reports && DB.weeklyIndex.reports[0] && DB.weeklyIndex.reports[0].date) || meta.lastFullReview;
    $('#stat-updated').textContent = fmtDate(lastScan);

    // Top 10 (scannable cards; "Why this ranking?" + research detail behind each card's expander).
    // The ranking-uncertainty statement (data/rankings.json) lives in the section's
    // "How solid is this order?" expander instead of a banner above the grid.
    const unc = $('#rank-uncertainty');
    if (unc && rankings.uncertaintyNote) unc.textContent = rankings.uncertaintyNote;
    $('#top10').innerHTML = rankings.top.map(r => {
        const t = DB.tById[r.id]; if (!t) return '';
        return rankedCard(t, r);
      }).join('');

    // Available now
    // every treatment that meets the rule is shown (no cut-off, so equal scores are never split by data-file order)
    const avail = treatments.filter(t => t.availability && t.availability.availableNow && t.tier <= 4 && t.evidenceScore >= 3)
      .sort((a, b) => b.evidenceScore - a.evidenceScore);
    $('#available').innerHTML = avail.map(t => treatmentCard(t)).join('');

    // What's new this week
    if (weekly) {
      $('#week-date').textContent = fmtDate(weekly.date);
      $('#whatsnew').innerHTML = weekly.items.slice(0, 5).map(weekItem).join('') +
        `<p><a class="btn btn-ghost" href="research.html">Read the latest research update →</a></p>`;
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

  function stabilityBadge(r) {
    if (!r.stability) return '';
    const ws = r.stability === 'weighting-sensitive';
    return `<span class="badge ${ws ? 'b-watch' : 'b-strong'}" title="${esc(r.stabilityNote || '')}">${ws ? 'Weighting-sensitive' : 'Stable rank'}</span>`;
  }
  /* Ranked card, scannable first: rank · category · name · loudness · distress · one plain-English
     line · "See evidence" · an always-visible summary strip (evidence score, tier, availability,
     rank stability — same data and badges as before, no longer hidden in the expander).
     "Why #N?" and the full research detail remain one tap down. */
  function rankedCard(t, r) {
    const cat = DB.catById[t.category] || {};
    const top = r.rank <= 3; // all 10 share the card style; #1–#3 carry the stronger 3px category top edge
    return `<div class="card tcard rcard ${top ? 'rcard-top' : 'rcard-rest'}" style="--cat-c:${esc(cat.color || '#888')}">
      <div class="rhead"><span class="rank">#${r.rank}</span>
        <span class="cat" style="${catVars(cat.color)}">${esc(cat.icon || '')} ${esc(cat.name || t.category)}</span></div>
      <h3>${updatedRecently(t) ? '<span class="updated-dot" title="Updated recently"></span>' : ''}<a href="treatment.html?id=${esc(t.id)}">${esc(t.name)}</a></h3>
      <p class="one">${esc(t.oneLiner)}</p>
      ${duo(t, true)}
      <a class="see" href="treatment.html?id=${esc(t.id)}">See evidence →</a>
      <div class="foot">${emeter(t.evidenceScore)} ${tierBadge(t.tier)} ${availBadge(t)} ${stabilityBadge(r)}</div>
      <details class="rmore">
        <summary>More evidence details</summary>
        ${whyRankingBlock(r, t)}
      </details>
    </div>`;
  }

  const IMP_STYLE = {
    'Potentially Important': 'b-strong', 'Interesting but Early': 'b-emerging',
    'Confirms Previous Evidence': 'b-promising', 'Negative Result': 'b-watch',
    'Does Not Change Current Evidence': 'b-weak'
  };
  function weekItem(it, label, extra) {
    const KIND_COLORS = { study: 'var(--c-promising)', trial: 'var(--c-emerging)', regulatory: 'var(--c-strong)', ranking: 'var(--c-watch)', negative: 'var(--c-weak)', news: 'var(--c-promising)' };
    const d = it.detail || {};
    const drow = (k, v) => (v && v !== 'Not reported' && (!Array.isArray(v) || v.length)) ?
      `<li><strong>${k}:</strong> ${esc(Array.isArray(v) ? v.join('; ') : v)}</li>` : '';
    // imp-* is presentation only: it mirrors the importance badge class so the research-page card
    // wash and hover frame follow the classification color already shown on the badge
    const impCls = it.importance ? (IMP_STYLE[it.importance] || 'b-weak').slice(2) : 'promising';
    return `<div class="week-item imp-${impCls}" style="--w-c:${KIND_COLORS[it.kind] || 'var(--c-promising)'}">
      ${it.importance ? `<span class="badge ${IMP_STYLE[it.importance] || 'b-weak'}" style="margin-bottom:4px">${esc(it.importance)}</span>` : ''}
      ${it.safetySignal ? `<span class="badge b-watch" style="margin-bottom:4px">⚠ Possible safety signal — read the source</span>` : ''}
      ${it.underEvaluation ? `<span class="badge b-emerging" style="margin-bottom:4px">Impact on Tinnitus Evidence rating: Under evaluation</span>` : ''}
      <div class="t">${esc(it.title)}</div>
      ${it.whyMatters ? `<div class="small"><strong>Why it matters:</strong> ${esc(it.whyMatters)}</div>` : ''}
      ${typeof it.reviewNote === 'string' && it.reviewNote ? `<div class="small muted review-note">${esc(it.reviewNote)}</div>` : ''}
      ${typeof label === 'string' && label ? `<div class="small muted ai-label">${esc(label)}</div>` : ''}
      ${typeof extra === 'string' ? extra : ''}
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
    // presentation classes only: st-* mirrors the status badge class so the card's top wash and
    // hover frame follow the existing status color; .sec marks the quieter secondary badges
    return `<div class="card trial-card st-${st.slice(2)}">
      <div class="foot tbadges">
        <span class="badge ${st}">${esc(tr.status)}</span>
        ${tr.phase ? `<span class="badge sec b-emerging">${esc(tr.phase)}</span>` : ''}
        ${tr.country ? `<span class="badge sec b-weak" title="Country of the lead sponsor/site">📍 ${esc(tr.country)}</span>` : ''}
        ${tr.watch ? '<span class="badge sec b-watch">One to watch</span>' : ''}</div>
      <h3>${esc(tr.title)}</h3>
      <p class="small muted meta">${esc(tr.sponsor)}${tr.n ? ` · aiming to enroll ${esc(tr.n)} people` : ''}${tr.completionEst ? ` · est. completion ${esc(tr.completionEst)}` : ''}</p>
      ${tr.whyItMatters ? `<p class="small why">${esc(tr.whyItMatters)}</p>` : ''}
      ${opts.profileNotes && matches.length ? `<div class="match-note">👤 This study involves ${matches.map(m => esc(CHAR_NAMES[m] || m)).join(' and ')} — a characteristic in your Tinnitus Profile. Only the study's research team can determine whether anyone is eligible.</div>` : ''}
      <p class="small acts" style="margin-bottom:0">
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
    catChips.innerHTML = `<button class="chip" data-cat="">Any categories</button>` +
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
    // Top-10 rank shown on the card comes from the same source as the homepage list (data/rankings.json)
    const topRank = {}; ((DB.rankings && DB.rankings.top) || []).forEach(r => { topRank[r.id] = r.rank; });
    const noteEl = $('#tnote'), resH = $('#tres-h');

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
      // filter explanations render above the grid (#tnote), never as a cell inside it
      const note =
        state.loud ? `<div class="notice">🔉 <strong>Honest note:</strong> very few treatments have credible evidence of making the tinnitus sound itself quieter — and most of those apply only to specific tinnitus types. Sorted by strength of loudness evidence; check each card's population.</div>` :
        state.negative ? `<div class="fnote" role="note"><b>What the evidence has shown</b><p>These treatments have failed trials, never beat placebo, or are marketed well beyond their evidence. No judgment if you've tried them — the marketing is persuasive. The evidence just isn't.</p></div>` :
        state.profile ? `<div class="match-note">👤 Showing research studied in people who share characteristics with your Tinnitus Profile. This is evidence navigation, not a recommendation.</div>` : '';
      if (noteEl) noteEl.innerHTML = note;
      listEl.innerHTML = (noteEl ? '' : note) + (list.length ? list.map(t => treatmentCard(t, { top10: topRank[t.id] })).join('') :
        '<div class="empty">Nothing matches those filters.</div>');
      // results heading names the active filter: "All tracked treatments — 38 shown", "Available now — 28 treatments"
      // (+ "28 of 38 tracked treatments match this filter."), or "Matching treatments — n treatments" when several
      // filters are combined (the supporting line then lists them). Counts always come from the filtered list.
      const FLAG_LABELS = { avail: 'Available now', loud: 'Loudness evidence', distress: 'Distress evidence', negative: "What hasn't worked", profile: 'Relevant to my profile' };
      const active = [];
      if (state.cat) active.push((DB.catById[state.cat] || {}).name || state.cat);
      if (state.type) active.push(SUBTYPE_LABELS[state.type] || state.type);
      Object.keys(FLAG_LABELS).forEach(f => { if (state[f]) active.push(FLAG_LABELS[f]); });
      if (state.q) active.push(`Search “${state.q}”`);
      const n = list.length, total = DB.treatments.length, word = `treatment${n === 1 ? '' : 's'}`;
      const sub = $('#tres-sub');
      if (!active.length) {
        if (resH) resH.textContent = 'All tracked treatments';
        $('#tcount').textContent = `${n} shown`;
        if (sub) { sub.textContent = ''; sub.hidden = true; }
      } else {
        if (resH) resH.textContent = active.length === 1 ? active[0] : 'Matching treatments';
        $('#tcount').textContent = `${n} ${word}`;
        if (sub) { sub.textContent = active.length === 1 ? `${n} of ${total} tracked treatments match this filter.` : `${n} of ${total} tracked treatments match these filters: ${active.join(' · ')}.`; sub.hidden = false; }
      }
      announce(`${n} ${word} ${active.length ? 'match' : 'shown'}`);
      // the heading names the subset while the "What hasn't worked" filter is on
      const h1 = $('.hero h1'); if (h1) h1.textContent = state.negative ? "Treatments That Haven't Worked" : 'Treatments';
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

    /* Page hierarchy (top → bottom): what it is → evidence at a glance → loudness → distress →
       how strong the evidence is → key studies → limitations → replication → safety / regulatory /
       availability → history → methodology & citations. Same data, same wording; only the order and
       which parts start collapsed changed. */
    const repWord = t.replication ? (REP_LABELS[t.replication] || cap(t.replication)) : 'Not yet assessed';
    const toc = [['what', 'What it is'], ['evidence', 'Evidence'], ['loud', '🔉 Loudness'], ['distress', '🧠 Distress'],
      ['strength', 'How strong?'], ['studies', 'Key studies'], ['limits', 'Limitations'], ['replication', 'Replication'],
      ['safety', 'Safety & availability'], ['sources', 'Sources']];
    root.innerHTML = `
      <p class="small" style="margin-top:14px"><a href="treatments.html">‹ All treatments</a></p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <span class="cat" style="${catVars(cat.color)};font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.06em">${esc(cat.icon)} ${esc(cat.name)}</span>
        ${rank ? `<span class="badge b-promising">#${rank} most promising</span>` : ''}
        ${rEntry ? stabilityBadge(rEntry) : ''}
      </div>
      <h1 style="margin:.2em 0 .3em">${esc(t.name)}</h1>
      <p class="muted" style="max-width:46em;margin-top:0">${esc(t.oneLiner)}</p>
      ${t.scopeNote ? `<div class="notice" role="note" aria-label="Scope of this assessment" style="margin:10px 0"><strong>Scope of this assessment.</strong> ${esc(t.scopeNote.text)}${(t.scopeNote.links || []).length ? ` <span class="small">Sources: ${t.scopeNote.links.map(l => `<a href="${esc(l[1])}" rel="noopener" target="_blank">${esc(l[0])}</a>`).join(' · ')}</span>` : ''}</div>` : ''}
      ${t.narrowPopulation ? `<div class="narrow-note">🎯 <strong>Applies only to a specific diagnosed tinnitus population.</strong> ${esc(t.narrowNote || '')}</div>` : ''}
      ${t.underReevaluation ? `<div class="notice" style="margin:10px 0">🔎 <strong>Evidence rating under re-evaluation${t.underReevaluation.since ? ' since ' + fmtDate(t.underReevaluation.since) : ''}.</strong>
        ${esc(t.underReevaluation.reason || '')} The rating shown is the current published assessment; it changes only when the review completes.</div>` : ''}
      ${prevNote}
      ${profileRelevance(t)}
      <nav class="toc" aria-label="On this page">${toc.map(([id, label]) => `<a href="#${id}">${label}</a>`).join('')}</nav>
      <div class="tpage-actions">
        <button class="btn watch-btn" type="button" id="watch" aria-pressed="${wlHas('treatments', t.id)}">⭐ <span>${wlHas('treatments', t.id) ? 'On your watchlist' : 'Add to watchlist'}</span></button>
        <a class="btn" href="compare.html?ids=${esc(t.id)}">⚖ Compare</a>
      </div>

      <div class="prose tpage">
        <section class="card sec-card" id="what"><h2>What it is</h2><p>${esc(t.whatItIs)}</p>
          <h3>How it works</h3><p>${esc(t.howItWorks)}</p></section>

        <section class="card sec-card sec-blue" id="evidence"><h2>Evidence at a glance</h2>
          ${plainBlock(t)}
          ${evidenceProfile(t)}</section>

        <section class="card sec-card sec-indigo" id="outcomes"><h2>Does it make tinnitus quieter — or easier to live with?</h2>
          <div class="duo ld-full">
            <div class="cell" id="loud"><div class="k">🔉 Loudness — did tinnitus loudness improve?</div>
              <div class="v lv-${esc(t.loudness.level)}">${LV_LABELS[t.loudness.level]}</div><p class="small">${esc(t.loudness.summary)}</p></div>
            <div class="cell" id="distress"><div class="k">🧠 Distress — did tinnitus distress improve?</div>
              <div class="v lv-${esc(t.distress.level)}">${LV_LABELS[t.distress.level]}</div><p class="small">${esc(t.distress.summary)}</p></div>
          </div>
          <p class="small muted">These are different outcomes. Loudness = the sound itself is reduced.
          Distress = the reaction to it improves (THI/TFI, anxiety, sleep, quality of life).</p></section>

        <section class="card sec-card" id="strength"><h2>How strong is the evidence?</h2>
          <p><strong>Why this score:</strong> ${esc(t.scoreRationale)}</p>
          ${rEntry ? whyRankingBlock(rEntry, t) : ''}
          ${rankHistory(t)}</section>

        <details class="sec" id="studies"><summary>Key studies <span class="small">${(t.studies || []).length} tracked</span></summary>
          ${(t.studies || []).map(id => studyBlock(DB.sById[id])).join('') || '<p class="muted">No studies recorded yet.</p>'}</details>

        <section class="card sec-card" id="limits"><h2>Limitations & open questions</h2>
          ${(t.limitations || []).length ? `<ul>${t.limitations.map(l => `<li>${esc(l)}</li>`).join('')}</ul>` : '<p class="muted">No limitations recorded.</p>'}
          ${t.conflicts ? `<div class="notice">⚠ <strong>Conflicts of interest:</strong> ${esc(t.conflicts)}</div>` : ''}</section>

        <section class="card sec-card" id="replication"><h2>Has the result been independently replicated?</h2>
          <p><strong>${esc(repWord)}.</strong> ${esc(t.replicationNote || '')}</p>
          ${t.independence ? `<p class="small muted">Independence: <strong>${esc(IND_LABELS[t.independence] || cap(t.independence))}</strong>. ${esc(t.independenceNote || '')}</p>` : ''}</section>

        <section class="card sec-card" id="safety"><h2>Safety, regulatory status & availability</h2>
          <p><strong>Safety evidence: ${esc(t.safetyLevel ? cap(t.safetyLevel) : 'Not yet assessed')}.</strong> ${esc(t.safety)}</p>
          <div class="snapshot" style="margin:14px 0">
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
          <details class="rdetail"><summary>Availability by region, prescription and regulatory detail</summary>
            <ul>
              <li><strong>USA:</strong> ${esc(av.usa || 'Unknown')}</li>
              <li><strong>Europe:</strong> ${esc(av.europe || 'Unknown')}</li>
              ${av.other ? `<li><strong>Elsewhere:</strong> ${esc(av.other)}</li>` : ''}
              <li><strong>Prescription / specialist:</strong> ${av.prescription ? 'Yes' : 'No'}</li>
              <li><strong>Approximate cost:</strong> ${esc(av.cost || 'Unknown')}</li>
            </ul>
            <p class="small muted">Regulatory detail: ${esc(t.regulatory.detail)}
              ${t.regulatory.sourceUrl ? ` <a href="${esc(t.regulatory.sourceUrl)}" rel="noopener" target="_blank">Source ↗</a>` : ''}</p>
          </details>
          ${fmqsBox(t)}</section>

        ${(t.timeline || []).length ? `<details class="sec" id="timeline"><summary>Research timeline <span class="small">${t.timeline.length} events</span></summary>${TL_KEY}<ul class="timeline">${t.timeline.map(ev => `<li class="${timelineClass(ev.event)}"><b>${esc(ev.year)}</b> — ${esc(ev.event)}</li>`).join('')}</ul></details>` : ''}

        ${(t.latest || []).length ? `<details class="sec" id="latest"${updatedRecently(t) ? ' open' : ''}><summary>Latest developments <span class="small">${t.latest.length}</span></summary>${t.latest.map(l =>
          `<div class="week-item"><div class="t">${esc(l.dateLabel || fmtDate(l.date))}</div><div class="small">${esc(l.text)}
           ${l.url ? ` <a href="${esc(l.url)}" rel="noopener" target="_blank">Source ↗</a>` : ''}</div></div>`).join('')}</details>` : ''}

        ${(t.history || []).length ? `<details class="sec" id="history"><summary>Change history <span class="small">${t.history.length}</span></summary>${t.history.map(h =>
          `<div class="week-item" style="--w-c:var(--c-watch)"><div class="t">${fmtDate(h.date)} — ${esc(h.change)}</div><div class="small muted">${esc(h.reason)}</div></div>`).join('')}</details>` : ''}

        <details class="sec" id="sources"><summary>Sources & methodology <span class="small">${(t.studies || []).length + (t.extraSources || []).length} sources</span></summary>
          <ul class="small">${(t.studies || []).map(id => { const s = DB.sById[id]; return s ? `<li>${esc(s.authors)} — <a href="${esc(s.url)}" rel="noopener" target="_blank">${esc(s.title)}</a> (${esc(s.journal)}, ${esc(s.year)})</li>` : ''; }).join('')}
          ${(t.extraSources || []).map(s => `<li><a href="${esc(s.url)}" rel="noopener" target="_blank">${esc(s.title)}</a></li>`).join('')}</ul>
          <p class="small muted">Last reviewed ${fmtDate(t.lastReviewed)} · evidence included through ${fmtDate(t.evidenceThrough)} ·
          tinnitus subtypes studied: ${esc((t.subtypes || []).map(x => /^to be defined/i.test(x) ? 'not yet defined' : x).join(', ') || 'not specified')} ·
          <a href="about.html#methodology">how we rate evidence</a> · <a href="about.html#profile-bars">how the profile bars work</a></p></details>
      </div>`;

    $('#watch').addEventListener('click', function () {
      const on = wlToggle('treatments', t.id);
      this.setAttribute('aria-pressed', on);
      $('span:last-child', this).textContent = on ? 'On your watchlist' : 'Add to watchlist';
    });
    attachClaimChecks(root, t.id);
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
    const steps = hist.filter((h, i) => i === 0 || h.rank !== hist[i - 1].rank);
    if (steps.length === 1) return `<div><div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">Ranking history</div>
      <div class="rankhist"><span class="step">${fmtDate(steps[0].date)}: #${steps[0].rank}</span></div>
      <p class="small muted" style="margin-top:2px">The rank has not changed at any later review.</p></div>`;
    return `<div><div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">Ranking history</div>
      <div class="rankhist">${steps.map((h, i) => `${i ? '<span class="arrow" aria-hidden="true">→</span>' : ''}<span class="step">${fmtDate(h.date)}: #${h.rank}</span>`).join('')}</div>
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
        <a class="tag" href="${esc(s.url)}" rel="noopener" target="_blank">${/pubmed\.ncbi\.nlm\.nih\.gov/i.test(s.url || '') ? 'PubMed' : /pmc\.ncbi\.nlm\.nih\.gov/i.test(s.url || '') ? 'Full text (PMC)' : /doi\.org/i.test(s.url || '') ? 'Publisher (DOI)' : 'Publisher / full text'} ↗</a>
      </div></div>`;
  }

  /* ----- compare ----- */
  PAGES.compare = function () {
    const sel = new Set((qs('ids') || '').split(',').filter(id => DB.tById[id]));
    const chipsEl = $('#cmp-chips'), out = $('#cmp-out');
    chipsEl.innerHTML = DB.treatments.slice().sort((a, b) => a.name.localeCompare(b.name))
      .map(t => `<button class="chip" data-id="${esc(t.id)}">${esc(t.name)}</button>`).join('');

    // selection-area UI only: live "n of 4 selected" count, search filter over the chips
    // (selected chips always stay visible), and a "full" state once 4 are chosen
    const countEl = $('#cmp-count'), searchEl = $('#cmp-search');
    let filter = '';
    function applyFilter() {
      $$('.chip', chipsEl).forEach(c => { c.hidden = !!filter && !sel.has(c.dataset.id) && !c.textContent.toLowerCase().includes(filter); });
    }
    if (searchEl) searchEl.addEventListener('input', e => { filter = e.target.value.trim().toLowerCase(); applyFilter(); });
    function render() {
      $$('.chip', chipsEl).forEach(c => c.setAttribute('aria-pressed', sel.has(c.dataset.id)));
      if (countEl) countEl.textContent = `${sel.size} of 4 selected`;
      chipsEl.classList.toggle('full', sel.size >= 4);
      applyFilter();
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
      announce(l.length ? `${l.length} trial${l.length === 1 ? '' : 's'} shown` : 'No trials match');
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
    // Reports that said "No evidence-changing tinnitus research identified" while automated evaluation was not running (clarification added after publication; the report data is not edited).
    const QUIET = {
      dates: ['2026-09-04', '2026-09-28', '2026-10-05', '2026-10-12', '2026-10-19'],
      text: 'This report previously stated that no evidence-changing tinnitus research was identified. However, automated evaluation was not completed for any of the records collected. Therefore, this statement should not be interpreted as confirmation that no relevant research was found.'
    };
    // Corrections to the September 2026 reports. The report text was corrected in place; data/corrections-log.json keeps the original wording of every
    // change, and each corrected item shows a visible note. Loaded before the report is drawn; if it cannot be loaded the report is drawn without notes.
    let CORR = { corrections: [] };
    const loadCorrections = () => fetch('data/corrections-log.json', { cache: 'no-cache' }).then(r => (r.ok ? r.json() : CORR)).then(j => { CORR = j; }, () => {});
    const correctionHtml = (date, it) => {
      const cs = (CORR.corrections || []).filter(c => c.reportDate === date && c.itemUrl === it.url);
      if (!cs.length) return '';
      return `<div class="small correction" role="note" style="border-left:4px solid var(--c-watch);padding:4px 10px;margin:6px 0"><strong>Correction (added October 2026):</strong><ul style="margin:4px 0 4px 18px;padding:0">${cs.map(c => `<li>${esc(c.noteText)}</li>`).join('')}</ul>Source: <a href="${esc(it.url)}" rel="noopener" target="_blank">${esc(cs[0].sourceLabel)} ↗</a></div>`;
    };
    // Reports whose items were written by an AI model and published without individual review (7-26 September 2026).
    const AI_UNREVIEWED = {
      dates: ['2026-09-07', '2026-09-14', '2026-09-21', '2026-09-26'],
      notice: 'Except for trial status changes taken directly from the registry, the items in this edition were written and published automatically by an AI model from each study\'s abstract or registry record. No person reviewed them individually before publication, and none was reviewed by a physician or other clinician. Numbers, study design and links come from the source record; statements about novelty, importance or interpretation are the AI\'s own wording and may be wrong or unsupported. An October 2026 check of these items against their sources found statements the sources do not make; each was corrected, and the correction is shown under the item. An item without a correction note has not been verified. Always use the linked source, and do not use these summaries for medical decisions.',
      label: 'Automated summary: AI-written, not individually reviewed, not clinician-reviewed. See the source for what the study actually reports.'
    };
    const renderReport = rep => {
      const unreviewed = AI_UNREVIEWED.dates.includes(rep.date);
      const impCounts = {};
      rep.items.forEach(it => { if (it.importance) impCounts[it.importance] = (impCounts[it.importance] || 0) + 1; });
      const impOrder = ['Potentially Important', 'Interesting but Early', 'Confirms Previous Evidence', 'Negative Result', 'Does Not Change Current Evidence'];
      $('#rep').innerHTML = `
        <h2 style="margin-top:10px">Update of ${fmtDate(rep.date)}</h2>
        ${QUIET.dates.includes(rep.date) ? `<aside class="card ai-notice clarification" role="note" aria-label="Important clarification" style="margin-bottom:14px;border-left:6px solid var(--c-watch)"><p style="margin:0"><strong>Important clarification:</strong> ${esc(QUIET.text)}</p></aside>` : ''}
        ${unreviewed ? `<aside class="card ai-notice" role="note" aria-label="About these summaries" style="margin-bottom:14px;border-left:4px solid var(--c-watch)"><h3 style="margin-top:0">About these summaries</h3><p class="small" style="margin-bottom:0">${esc(AI_UNREVIEWED.notice)} <a href="about.html#automation">How updates are made →</a></p></aside>` : ''}
        ${Object.keys(impCounts).length ? `<div class="card" style="margin-bottom:14px">
          <div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">This edition's ${rep.items.length} updates, by importance</div>
          ${countBars(impOrder.filter(k => impCounts[k]).map(k => ({ label: k, n: impCounts[k] })), { aria: 'Updates by importance' })}
          <p class="small muted" style="margin:8px 0 0">Classifications are assigned by our automated evaluation pipeline; anything that could change an evidence rating is held for review rather than auto-applied. An activity-over-time view will appear as the archive grows.</p></div>` : ''}
        ${rep.headline ? `<div class="card" style="border-left:4px solid var(--c-promising)"><div class="k small muted" style="text-transform:uppercase;font-weight:700;letter-spacing:.06em">Most important in this update</div>
          <h3>${esc(rep.headline.title)}</h3><p class="small">${esc(rep.headline.summary)}</p>
          ${rep.headline.url ? `<a class="small" href="${esc(rep.headline.url)}" rel="noopener" target="_blank">Source ↗</a>` : ''}</div>` : ''}
        ${rep.items.map(it => weekItem(it, unreviewed && it.detail && it.detail.studyType ? AI_UNREVIEWED.label : '', correctionHtml(rep.date, it))).join('')}`;
    };
    const drawArchive = () => {
      $('#archive').innerHTML = DB.weeklyIndex.reports.map(r => {
        const n = (CORR.corrections || []).filter(c => c.reportDate === r.date).length;
        return `<li><a href="research.html?week=${esc(r.file)}">${fmtDate(r.date)}</a> — ${esc(r.title)}${QUIET.dates.includes(r.date) ? ' <span class="small muted">— clarification added</span>' : ''}${n ? ' <span class="small muted">— ' + n + (n === 1 ? ' correction' : ' corrections') + ' added</span>' : ''}</li>`;
      }).join('');
    };
    drawArchive();
    loadCorrections().then(() => {
      if (file) {
        if (SINGLE && DB.weeklyAll) renderReport(DB.weeklyAll[file] || DB.weekly);
        else fetch('data/weekly/' + file, { cache: 'no-cache' }).then(r => r.json()).then(renderReport);
      } else if (DB.weekly) renderReport(DB.weekly);
      drawArchive();
    });
  };

  /* ----- institutions ----- */
  PAGES.institutions = function () {
    const inst = $('#inst');
    inst.innerHTML = DB.institutions.map(i => `<div class="card inst-card">
      <h3>${esc(i.name)}</h3><p class="small muted inst-loc">${esc(i.location)}</p>
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
    // Emerging, Experimental & Unproven Treatments: searched from the same finalized data file the page itself
    // renders from (embedded in single-file previews; otherwise fetched once, only when Search is opened)
    let EU = null;
    (window.__TA_EU__ ? Promise.resolve(window.__TA_EU__.data)
      : fetch('data/emerging-unproven.json', { cache: 'no-cache' }).then(r => r.ok ? r.json() : null))
      .then(d => { if (d && d.T) { EU = d; render(); } }).catch(() => {});
    // punctuation- and accent-tolerant matching that never joins separate words:
    // "NAD" finds "NAD+", "bpc157" / "BPC 157" find "BPC-157", "AC 102" finds "AC102", "meniere" finds "Menière"
    const fold = s => (s || '').toLowerCase().normalize('NFD').replace(/\p{M}/gu, '');
    const tight = s => fold(s).replace(/[^\p{L}\p{N}\s]+/gu, '').replace(/\s+/g, ' ');   // drop punctuation, keep word gaps
    const loose = s => fold(s).replace(/[^\p{L}\p{N}]+/gu, ' ').replace(/\s+/g, ' ');    // punctuation counts as a word gap
    function rows(q) {
      const qf = fold(q), qt = tight(q).trim(), ql = loose(q).trim(), qs = qt.replace(/ /g, '');
      // punctuation-insensitive matches must start at the beginning of a word, so a hyphenated code such as
      // "NITESGON-ADT" (→ "nitesgonadt") is never matched by "nad"
      const hit = s => { const f = fold(s); if (f.includes(qf)) return true; const t = tight(f);
        return (ql.length >= 2 && loose(f).includes(ql)) || (qt.length >= 2 && (' ' + t).includes(' ' + qt)) ||
          (qs.length >= 2 && t.split(' ').some(w => w.startsWith(qs))); };
      const r = [];
      DB.treatments.forEach(t => { if (hit(t.name + ' ' + t.oneLiner + ' ' + t.mechanism + ' ' + t.developer + ' ' + (t.researchers || []).join(' ')))
        r.push(['Treatment', t.name, `treatment.html?id=${t.id}`, t.oneLiner]); });
      // same fields the Emerging page's own search uses: name, other names, description
      // (exact name first, then name matches, then other-name/description matches)
      if (EU) EU.T.filter(t => hit(t.name + ' ' + (t.alt || '') + ' ' + t.desc))
        .map(t => [fold(t.name) === qf ? 0 : hit(t.name) ? 1 : 2, t]).sort((a, b) => a[0] - b[0])
        .forEach(([, t]) => r.push(['Emerging & unproven', t.name, `emerging-unproven/#${t.id}`,
          'Emerging, Experimental & Unproven Treatments · ' + ((EU.SIT[t.cat] || {}).short || '')]));
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
      if (q.length < 2) { // untouched box: orientation line; started typing: the short-input hint
        out.innerHTML = '<div class="empty">' + (q.length ? 'Type at least two characters.' : 'Search across treatments, research, clinical trials, researchers and institutions.') + '</div>'; return; }
      const r = rows(q);
      out.innerHTML = r.length ? r.map(([type, title, href, sub, ext]) =>
        `<div class="sr-row sr-${type.toLowerCase().replace(/[^a-z]+/g, '-')}"><span class="type">${type}</span>
          <span><a href="${esc(href)}"${ext ? ' rel="noopener" target="_blank"' : ''}>${esc(title)}${ext ? ' ↗' : ''}</a>
          ${sub ? `<br><span class="small muted">${esc(sub)}</span>` : ''}</span></div>`).join('')
        : '<div class="empty">No matches across treatments, studies, trials, institutions, categories or updates.</div>';
      announce(r.length ? `${r.length} result${r.length === 1 ? '' : 's'}` : 'No matches');
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
      root.innerHTML = `<div class="empty empty-state">
        <strong class="es-title">Your watchlist is empty.</strong>
        <p>Follow treatments, clinical trials or research groups, and this page will highlight news about them.</p>
        <p class="es-actions"><a class="btn btn-primary" href="treatments.html">Browse treatments</a>
        <a class="btn" href="trials.html">Browse trials</a></p></div>`;
      return;
    }
    let lastSeen = 0; try { lastSeen = +localStorage.getItem(SEEN_KEY) || 0; } catch (e) {}
    let html = '';
    // entries reuse the site's treatment / trial cards as-is (wash, frame, hover); the watchlist-only
    // extras (fresh-research badge, latest items, Remove) are appended inside the same card
    const inside = (card, extra) => card.replace(/<\/div>\s*$/, extra + '</div>');
    html += wl.treatments.map(id => {
      const t = DB.tById[id]; if (!t) return '';
      const fresh = (t.latest || []).filter(l => new Date(l.added || l.date).getTime() > lastSeen);
      return inside(treatmentCard(t), `<div class="wl-extra">
        ${fresh.length ? `<span class="badge b-strong">🔔 New research available</span>` : ''}
        ${fresh.map(l => `<div class="week-item"><div class="t small">${esc(l.dateLabel || fmtDate(l.date))}</div><div class="small">${esc(l.text)}</div></div>`).join('')}
        <button class="btn small" data-unwatch="treatments" data-id="${esc(id)}" type="button">Remove</button></div>`);
    }).join('');
    html += wl.trials.map(nct => {
      const tr = DB.trials.find(x => x.nctId === nct); if (!tr) return '';
      return inside(trialCard(tr), `<div class="wl-extra"><button class="btn small" data-unwatch="trials" data-id="${esc(nct)}" type="button">Remove</button></div>`);
    }).join('');
    html += wl.institutions.map(iid => {
      const i = DB.institutions.find(x => x.id === iid); if (!i) return '';
      return `<div class="card wl-inst"><h3>${esc(i.name)}</h3><p class="small">${esc(i.focus)}</p>
        <div class="wl-extra"><button class="btn small" data-unwatch="institutions" data-id="${esc(iid)}" type="button">Remove</button></div></div>`;
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
    // counts stay live from the data; "selected" = the main evaluated treatment database (the separate
    // Emerging & Unproven collection is not added in). Two different dates: the manual full evidence review
    // (meta.lastFullReview) and the latest automated research scan (newest weekly report).
    const scan = (DB.weeklyIndex && DB.weeklyIndex.reports && DB.weeklyIndex.reports[0] && DB.weeklyIndex.reports[0].date) || '';
    if (fm) fm.innerHTML = esc(`Evidence database: hundreds of research results screened · ${DB.treatments.length} selected treatments · ${DB.studies.length} research records · ${DB.trials.length} trials watched`) +
      '<br>' + esc(`Last full evidence review: ${fmtDate(DB.meta.lastFullReview)}` + (scan ? ` · Latest automated research scan: ${fmtDate(scan)}` : '')) +
      '<br>' + esc('Trial status changes are verified at the registry before they publish. AI-written summaries are currently paused and, when they resume, will receive editorial review (not a clinical review) before publication. Evidence ratings, rankings and safety assessments never change automatically.');
  }
  /* Deep links into collapsed sections: open every <details> ancestor of the target so
     about.html#rankings, #timeline etc. never land on a closed expander. */
  function revealTarget(id) {
    const el = id && document.getElementById(id);
    if (!el) return null;
    for (let p = el; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
    return el;
  }
  let pendingAnchor = null;
  function renderRoute() {
    const raw = (location.hash || '#/').replace(/^#\/?/, '');
    let page = (raw.split('?')[0] || 'index').replace(/\.html$/, '') || 'index';
    // prerendered static pages are embedded under their path, e.g. "treatments/cbt/" -> page-treatments/cbt
    if (page.includes('/')) page = page.replace(/\/$/, '');
    if (!document.getElementById('page-' + page)) page = 'index';
    document.body.dataset.page = page;
    document.title = ((DB.tById[qs('id')] || {}).name || pageTitle(page)) + ' — ' + DB.meta.name;
    $('#app').innerHTML = document.getElementById('page-' + page).innerHTML;
    if (page.includes('/')) { const h1 = $('#app h1'); if (h1) document.title = h1.textContent.trim() + ' — ' + DB.meta.name; }
    chrome();
    setFootMeta();
    if (PAGES[page]) PAGES[page]();
    else if (window.TA_PAGE_HOOKS && window.TA_PAGE_HOOKS[page]) window.TA_PAGE_HOOKS[page]({ anchor: pendingAnchor }); // pages with their own script (emerging-unproven); anchor = card to open
    if (pendingAnchor) {
      const el = revealTarget(pendingAnchor); pendingAnchor = null;
      if (el) { el.scrollIntoView(); return; }
    }
    window.scrollTo(0, 0);
  }
  function pageTitle(p) {
    return { index: 'Home', treatments: 'Treatments', treatment: 'Treatment', compare: 'Compare',
      trials: 'Clinical Trials', research: 'Latest Research', institutions: 'Institutions',
      watchlist: 'Watchlist', about: 'About', search: 'Search', profile: 'My Tinnitus Profile',
      'emerging-unproven': 'Emerging & Unproven Treatments' }[p] || p;
  }
  function initRouter() {
    document.addEventListener('click', e => {
      // composedPath: links inside a page's shadow root (emerging-unproven) are routed too
      const tgt = (e.composedPath && e.composedPath()[0] instanceof Element) ? e.composedPath()[0] : e.target;
      const a = tgt.closest('a[href]');
      if (!a) return;
      const href = a.getAttribute('href') || '';
      let m = href.match(/^([a-z-]+)\.html(?:\?([^#]*))?(?:#(.*))?$/);
      if (!m) {
        // clean static URLs ("treatments/cbt/", "research/", "./") → embedded prerendered page
        const s = href.match(/^(?:\.\/|((?:treatments|trials|research|guides|research-questions|ask|emerging-unproven|claims)(?:\/[A-Za-z0-9_.-]+)?)\/?)(?:#(.*))?$/);
        if (!s) return;
        e.preventDefault();
        pendingAnchor = s[2] || null;
        const h = '#/' + (s[1] || '');
        if (h === location.hash) renderRoute(); else location.hash = h;
        return;
      }
      if (href.startsWith('#')) return;
      e.preventDefault();
      pendingAnchor = m[3] || null;
      const h = '#/' + (m[1] === 'index' ? '' : m[1]) + (m[2] ? '?' + m[2] : '');
      if (h === location.hash) renderRoute(); else location.hash = h;
    });
    // same-page anchors inside a routed page (e.g. the treatment page's "On this page" chips)
    document.addEventListener('click', e => {
      const a = e.target.closest('a[href^="#"]');
      if (!a || a.getAttribute('href').startsWith('#/')) return;
      const el = revealTarget(a.getAttribute('href').slice(1));
      if (el) { e.preventDefault(); el.scrollIntoView({ block: 'start' }); }
    });
    addEventListener('hashchange', renderRoute);
    renderRoute();
  }

  /* ---------------- boot ---------------- */
  async function boot() {
    const page = document.body.dataset.page;
    // Multi-page build: the header, navigation and footer are built before the data request, so they are part of
    // the first paint. A page whose main content is rendered from the database (or by its own renderer, e.g.
    // emerging-unproven) is held behind html.ta-loading (css) until that content has been inserted; the gate is
    // lifted in the same task, so the browser never paints the shell with empty grids and the footer half-way up.
    // Static prerendered pages (data-page="") are not gated — their content is already in the HTML.
    const gated = !SINGLE && !!(PAGES[page] || (window.TA_PAGE_HOOKS && window.TA_PAGE_HOOKS[page]));
    if (gated) document.documentElement.classList.add('ta-loading');
    if (!SINGLE) chrome();
    try {
      await load();
      if (SINGLE) { initRouter(); return; }
      if (DB.meta && DB.meta.name && DB.meta.name !== brandFromDocument()) chrome();   // brand follows data/meta.json
      setFootMeta();
      if (PAGES[page]) PAGES[page]();
      if (window.__TA_PAGE_READY) await window.__TA_PAGE_READY.catch(() => {});      // page with its own renderer
      // deep links into collapsed <details> sections (about.html#rankings, #timeline …)
      const open = () => { const el = revealTarget(decodeURIComponent(location.hash.slice(1))); if (el) el.scrollIntoView(); };
      if (location.hash) open();
      addEventListener('hashchange', open);
    } catch (err) {
      chrome();
      const m = document.createElement('div');
      m.className = 'wrap notice'; m.style.margin = '20px auto';
      m.textContent = 'Could not load the research database (' + err.message + '). If you opened this file directly, serve the folder over HTTP instead.';
      document.body.insertBefore(m, document.body.children[1]);
    } finally {
      document.documentElement.classList.remove('ta-loading');
      scheduleFit();
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot(); // script may execute after DOMContentLoaded (single-file/artifact wrapping)
})();
