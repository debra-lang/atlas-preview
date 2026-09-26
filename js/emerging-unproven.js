/* Tinnitus Evidence — Emerging & Unproven Treatments page (emerging-unproven/).
   Content: data/emerging-unproven.json. Styles: css/emerging-unproven.css.
   The page renders into a shadow root on #eu-app so its styles are isolated from the rest of the site
   (the single-file preview build puts every page in one document). Site chrome, theme toggle and
   analytics guard come from js/app.js as on every other page. */
(function () {
  'use strict';
  const SINGLE = !!window.__TA_SINGLE__;

  function loadAssets() {
    if (window.__TA_EU__) return Promise.resolve(window.__TA_EU__);   // single-file preview: embedded
    const get = (f, how) => fetch(f, { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(f + ' ' + r.status); return r[how](); });
    return Promise.all([get('data/emerging-unproven.json', 'json'), get('css/emerging-unproven.css', 'text')])
      .then(([data, css]) => ({ data, css }));
  }

  async function init(opts) {
    const anchor = (opts && typeof opts.anchor === 'string') ? opts.anchor : null;   // card id to open (single-file preview)
    const host = document.getElementById('eu-app'), shell = document.getElementById('eu-shell');
    if (!host || !shell || host.shadowRoot) return;
    let assets;
    try { assets = await loadAssets(); }
    catch (err) { host.innerHTML = '<p class="notice">This page could not load its research data (' + err.message + '). Please reload.</p>'; return; }
    const R = host.attachShadow({ mode: 'open' });
    R.innerHTML = '<style>' + assets.css + '</style>' + shell.innerHTML;
    // follow the site-wide theme toggle (js/app.js sets <html data-theme>)
    const syncTheme = () => { host.dataset.theme = document.documentElement.dataset.theme || 'dark'; };
    syncTheme();
    new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    run(R, assets.data, anchor);
  }

  function run(R, D, anchor) {
  const { SIT, ORDER, TYPES, REPL, COMDEF, COVTIP, BADGES, VISIBLE, PRI, GLABEL, PM, CHIPK, STONES, TSTATE, TR, T, SAFE, FD, JOURNEY, NEQ, RL, ELSE } = D;
  const P = {
    flask:'<path d="M9 3h6M10 3v6L4.6 18.6A1.6 1.6 0 0 0 6 21h12a1.6 1.6 0 0 0 1.4-2.4L14 9V3"/><path d="M7.5 14h9"/>',
    person:'<circle cx="12" cy="7.5" r="3.5"/><path d="M5 21c0-4 3.1-6.8 7-6.8s7 2.8 7 6.8"/>',
    scale:'<path d="M12 3v18M8 21h8M4 7h16"/><path d="M7 7l-3 6.5a3 3 0 0 0 6 0L7 7zM17 7l-3 6.5a3 3 0 0 0 6 0L17 7z"/>',
    papers:'<rect x="7" y="3" width="12" height="15" rx="1.5"/><path d="M4 7v12.5A1.5 1.5 0 0 0 5.5 21H15"/><path d="M10 8h6M10 11.5h6M10 15h3"/>',
    diverge:'<path d="M12 21v-7M12 14 6 6M12 14l6-8"/><path d="M4 9V5h4M20 9V5h-4"/>',
    chat:'<path d="M4 5h16v11H10l-5 4v-4H4z"/>',
    paw:'<path d="M12 12.5c-3 0-5 2.6-5 5a3 3 0 0 0 3 3h4a3 3 0 0 0 3-3c0-2.4-2-5-5-5z"/><circle cx="5.5" cy="10" r="1.7"/><circle cx="9.5" cy="6.5" r="1.7"/><circle cx="14.5" cy="6.5" r="1.7"/><circle cx="18.5" cy="10" r="1.7"/>',
    repeat:'<path d="M4 11a8 8 0 0 1 14-5.3L20 8M20 13a8 8 0 0 1-14 5.3L4 16"/><path d="M20 3v5h-5M4 21v-5h5"/>',
    check:'<path d="M20 6 9 17l-5-5"/>',
    ear:'<path d="M7 9a5 5 0 1 1 10 0c0 3-2.5 4-3.5 6a3.5 3.5 0 0 1-6.5 1.5"/><path d="M10 9a2 2 0 1 1 4 0c0 1.5-1.5 2-1.5 3.5"/>',
    hourglass:'<path d="M6 2h12M6 22h12M7.5 2v3.5L12 12l-4.5 6.5V22M16.5 2v3.5L12 12l4.5 6.5V22"/>',
    tri:'<path d="M12 3.5 2.5 20.5h19L12 3.5z"/><path d="M12 10v4.5M12 17.5h.01"/>',
    book:'<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5v-15zM5 19.5A1.5 1.5 0 0 0 6.5 21H19"/><path d="M9.5 10.5h5"/>',
    bldg:'<path d="M3 21h18M5 21V8l7-4 7 4v13M9.5 21v-5h5v5M9 11h.01M15 11h.01"/>',
    globe:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    mag:'<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    docx:'<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4"/><path d="M4 4l16 16"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
    chev:'<path d="M6 9l6 6 6-6"/>',
    shield:'<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>'
  };
  const ic = (n, cls='i') => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[n]}</svg>`;
  function shape(cat){
    const inner = n => `<g transform="translate(7.2 7.2) scale(.65)" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${P[n]}</g>`;
    const s = 'fill="none" stroke="currentColor" stroke-width="1.8"';
    const m = {
      untested:`<circle cx="15" cy="15" r="13" ${s} stroke-dasharray="3.2 3"/>${inner('flask')}`,
      early:`<circle cx="15" cy="15" r="13" ${s}/>${inner('person')}`,
      controlled:`<rect x="2.5" y="2.5" width="25" height="25" rx="4" ${s}/>${inner('scale')}`,
      nosham:`<rect x="6" y="1.5" width="22" height="22" rx="3.5" ${s} opacity=".55"/><rect x="2" y="6" width="22" height="22" rx="3.5" fill="var(--surface)" stroke="currentColor" stroke-width="1.8"/><g transform="translate(4.8 8.6) scale(.68)" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${P.papers}</g>`,
      mixed:`<path d="M15 1.5 28.5 15 15 28.5 1.5 15z" ${s}/>${inner('diverge')}`,
      nobenefit:`<circle cx="15" cy="15" r="13.5" fill="currentColor"/><path d="M9 12.3h12M9 17.7h12" stroke="var(--surface)" stroke-width="2.6" stroke-linecap="round"/>`
    };
    return `<span class="shape" aria-hidden="true"><svg viewBox="0 0 30 30">${m[cat]}</svg></span>`;
  }
  function mk(t){
    const c = 'cx="11" cy="11" r="8.5"';
    const m = {
      y:`<circle ${c} fill="currentColor"/>`,
      r:`<circle ${c} fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M6 13.5l7.5-7.5M8.5 16.5l8-8M5.5 10l4.5-4.5" stroke="currentColor" stroke-width="1.4"/>`,
      p:`<circle ${c} fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M11 2.5a8.5 8.5 0 0 0 0 17z" fill="currentColor"/>`,
      e:`<circle ${c} fill="currentColor"/><path d="M6.8 9h8.4M6.8 13h8.4" stroke="var(--surface)" stroke-width="2" stroke-linecap="round"/>`,
      n:`<circle ${c} fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="2.5 2.5" opacity=".7"/>`
    };
    return `<svg viewBox="0 0 22 22" aria-hidden="true">${m[t]}</svg>`;
  }

  function link(id){
    id=id.trim();
    if(/^NCT\d{8}$/.test(id)) return `<a href="https://clinicaltrials.gov/study/${id}" target="_blank" rel="noopener">${id}</a>`;
    if(/^PMID \d+$/.test(id)) return `PMID <a href="https://pubmed.ncbi.nlm.nih.gov/${id.slice(5)}/" target="_blank" rel="noopener">${id.slice(5)}</a>`;
    if(/^DOI /.test(id)) return `DOI <a href="https://doi.org/${id.slice(4)}" target="_blank" rel="noopener">${id.slice(4)}</a>`;
    if(/^ISRCTN\d+$/.test(id)) return `<a href="https://www.isrctn.com/${id}" target="_blank" rel="noopener">${id}</a>`;
    return id;
  }
  const links = s => s.split(' · ').map(link).join(' · ');
  const isActive = k => (TR[k].st||'active')==='active';
  function trialPanel(k){
    const t=TR[k], s=TSTATE[t.st];
    if(!s) return `<div class="trial"><div style="font-weight:700;margin-bottom:6px">${ic('hourglass')} ${t.t}</div><dl>
    <dt>Registry</dt><dd>${links(t.id)}</dd><dt>Size</dt><dd>${t.size}</dd><dt>Design</dt><dd>${t.design}</dd>
    ${t.comp?`<dt>Comparator</dt><dd>${t.comp}</dd>`:''}<dt>Primary tinnitus outcome</dt><dd>${t.tin}</dd><dt>Status</dt><dd>${t.status}${t.stale?` · <span class="stale">${t.stale}</span>`:''}</dd><dt>Expected</dt><dd>${t.when}</dd><dt>Status last checked</dt><dd>${t.checked||'24 Sep 2026'}</dd></dl>
    <p class="dis">${ic('info')}<span>An ongoing trial is not evidence that the treatment works. Results can show benefit, no benefit, or harm.</span></p></div>`;
    return `<div class="trial"><div class="tlabel">${s.label}</div><div style="font-weight:700;margin-bottom:6px">${ic(s.ic)} ${t.t}</div><dl>
    <dt>Registry</dt><dd>${links(t.id)}</dd><dt>Size</dt><dd>${t.size}</dd><dt>Design</dt><dd>${t.design}</dd>
    ${t.comp?`<dt>Comparator</dt><dd>${t.comp}</dd>`:''}<dt>Primary tinnitus outcome</dt><dd>${t.tin}</dd>
    <dt>Registry status</dt><dd>${t.rstat||t.status}</dd><dt>${t.st==='unknown'?'Last registry update':'Completion date'}</dt><dd>${t.cdate||t.when}</dd>
    <dt>Registry results posted</dt><dd>${t.rres||'No'}</dd><dt>Peer-reviewed publication</dt><dd>${t.pubf||'None found in our search'}</dd>
    <dt>Status last checked</dt><dd>${t.checked||'24 Sep 2026'}</dd></dl>
    <p class="dis">${ic('info')}<span>${s.note}</span></p></div>`;
  };
  function trialsHTML(keys,note){
    keys = keys||[]; const act=keys.filter(isActive), rest=keys.filter(k=>!isActive(k));
    return act.map(trialPanel).join('')
     + (note?`<p>${note}</p>`:'')
     + (rest.length?`<h5 class="thead">Finished or inactive trials — not underway</h5>${rest.map(trialPanel).join('')}`:'');
  };
  function toneSummaries(root){
    root.querySelectorAll('details.xs>summary').forEach(s=>{
      const x=s.textContent.trim().toLowerCase(); const m=STONES.find(k=>x.startsWith(k[0]));
      if(!m) return; s.dataset.tone=m[1]; s.parentElement.dataset.tone=m[1];
      if(m[2] && !s.querySelector('svg')) s.insertAdjacentHTML('afterbegin', ic(m[2]));
    });
  }
  /* ===================== SHARED EXPANDED BLOCKS ===================== */
  function badgeInfo(t,b,lab=true){
    const L = x => lab?`<strong>${x}.</strong> `:'';
    if(b==='guideline') return `${L(GLABEL[t.gl.lvl])}${t.gl.text}`;
    if(b==='maker') return `${L('Commercial involvement')}${t.com||''} <span class="muted">${COMDEF}</span>`;
    if(b==='underway') return `${L('Research underway')}See the trial details below.`;
    if(b==='regonly' && t.reg) return `${L('Registry results only')}${t.reg} <span class="muted">${BADGES.regonly.text}</span>`;
    if(b==='nopub' && t.nop) return `${L('No public results found')}${t.nop} <span class="muted">${BADGES.nopub.text}</span>`;
    if(b==='safety' && SAFE[t.id]) return `${L('Safety note')}${SAFE[t.id]}`;
    return `${L(BADGES[b].label)}${BADGES[b].text}`;
  }
  function badgeLabel(t,b){return b==='guideline'?GLABEL[t.gl.lvl]:BADGES[b].label}
  function glanceHTML(t){
    const r=REPL[t.repl];
    const bs=[...t.badges].sort((a,b)=>PRI.indexOf(a)-PRI.indexOf(b));
    return `<details class="xs" open><summary>${ic('info')} At a glance</summary><div>
    <dl class="glance">
     <dt>What it is</dt><dd>${t.desc}${t.alt?`<span class="muted"> Also: ${t.alt}.</span>`:''}</dd>
     <dt>Best evidence</dt><dd>${t.best}${t.bestsub?` <span class="muted">(${t.bestsub})</span>`:''}</dd>
     <dt>Independent replication</dt><dd><b aria-hidden="true">${r[0]}</b> ${r[1]}</dd>
     <dt>Literature coverage</dt><dd>${t.cov} <button type="button" class="infobtn" data-cov aria-label="What does literature coverage mean?">${ic('info')}</button></dd>
    </dl>
    ${bs.length?`<ul class="binfo">${bs.map(b=>`<li><span class="badge ${BADGES[b].cls||''}">${ic(BADGES[b].ic)}${badgeLabel(t,b)}</span><span>${badgeInfo(t,b,false)}</span></li>`).join('')}</ul>`:''}
    </div></details>`;
  }
  function partsHTML(t){
    if(!t.parts) return '';
    return `<details class="xs" open><summary>Evidence for each part of this group</summary><div>
    <p class="muted" style="font-size:.93rem;margin-top:0">Each is shown separately. Evidence for one does not apply to the others.</p>
    <div class="parts">${t.parts.map(p=>`<div class="part"><div class="ph"><b>${p.n}</b><span class="tm">${mk(p.m)} ${p.ml||PM[p.m]}</span></div><p>${p.e}</p>${p.src?`<p class="psrc">${links(p.src)}</p>`:''}</div>`).join('')}</div>
    <p class="mjkey" style="margin-top:8px"><span>${mk('y')} tinnitus measured in people</span><span>${mk('r')} animal or related-condition evidence only</span><span>${mk('e')} tested, no benefit shown</span><span>${mk('n')} none found in our search</span></p>
    </div></details>`;
  }

  function chips(list){return `<div class="chips">${list.map(c=>`<span class="fchip k-${c[0]}">${ic(CHIPK[c[0]]||'info')}${c[1]}</span>`).join('')}</div>`}
  function rowsDL(rows){return `<dl class="glance">${rows.map(r=>`<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join('')}</dl>`}
  function streamsHTML(list){
    const ICO={tin:'person',hear:'ear',animal:'paw',lab:'flask',product:'bldg'};
    return `<div class="streams">${list.map(s=>`<div class="stream${s.k==='tin'?' tin':''}"><div class="sh">${ic(ICO[s.k])} ${s.title} <span class="tm">${mk(s.m)} ${s.ml}</span></div><p>${s.text}</p></div>`).join('')}</div>`;
  }
  function sec(title, body, open){return `<details class="xs"${open?' open':''}><summary>${title}</summary><div>${body}</div></details>`}
  function ul(items){return `<ul>${items.map(x=>`<li>${x}</li>`).join('')}</ul>`}

  function fullCard(t){
    const d = FD[t.id]; const r = REPL[t.repl];
    const bs=[...t.badges].sort((a,b)=>PRI.indexOf(a)-PRI.indexOf(b));
    const whatIs = `${chips(d.chips)}
     ${rowsDL([['What it is',t.desc+(t.alt?`<span class="muted"> Also: ${t.alt}.</span>`:'')],['Evidence situation',`${SIT[t.cat].label}${t.qual?` — <span class="muted">${t.qual}</span>`:''}`],['Best evidence',t.best+(t.bestsub?` <span class="muted">(${t.bestsub})</span>`:'')],['Literature coverage',`${t.cov} <button type="button" class="infobtn" data-cov aria-label="What does literature coverage mean?">${ic('info')}</button>`]])}
     ${bs.length?`<ul class="binfo">${bs.map(b=>`<li><span class="badge ${BADGES[b].cls||''}">${ic(BADGES[b].ic)}${badgeLabel(t,b)}</span><span>${badgeInfo(t,b,false)}</span></li>`).join('')}</ul>`:''}`;
    const journey = d.journey ? `${mjKey()}<div class="mj" role="img" aria-label="${d.journey.aria}">${d.journey.steps.map(s=>mjStep(s[0],s[1],s[2])).join('')}</div>` : '';
    const duo = d.duo ? `<div class="duo"><div class="cell"><div class="k">🔉 Loudness</div><div class="v">${d.duo[0]}</div></div><div class="cell"><div class="k">🧠 Distress / impact</div><div class="v">${d.duo[1]}</div></div></div>` : '';
    return [
      sec('What is it?', whatIs, true),
      d.journey ? sec('Where it sits in the evidence journey', journey, false) : '',
      sec('What is claimed?', d.claimed),
      sec('What has actually been studied?', streamsHTML(d.studied)+(d.studiedNote?`<p class="muted" style="margin-top:8px">${d.studiedNote}</p>`:''), !!d.openStudied),
      d.gapFirst ? sec('How the evidence connects to the claim', d.gap, true) : '',
      d.special || '',
      sec('Best human tinnitus evidence', rowsDL(d.best)+(d.bestNote?`<p class="muted">${d.bestNote}</p>`:'')),
      sec('What did researchers find?', `<p>${d.found.plain}</p>${duo}${ul(d.found.numbers)}`),
      sec('Important limitations', ul(d.limits)),
      sec('Independent replication', `<p><b aria-hidden="true">${r[0]}</b> <strong>${r[1]}.</strong> ${d.repl}</p>`),
      sec('Safety', d.safety),
      sec('Guidelines', d.guide),
      sec('Commercial involvement', d.com),
      sec('Research underway', trialsHTML(d.trials, d.underway)),
      sec('Why this is not established', `<p>${d.why}</p>`),
      (!d.gapFirst && d.gap) ? sec('How the evidence connects to the claim', d.gap) : '',
      sec('Literature coverage', `<p><strong>${t.cov}.</strong> ${d.cov}</p><p class="muted" style="font-size:.92rem">${COVTIP}</p>`),
      sec('Sources', `<ol class="src">${d.src.map(s=>`<li><span class="ty">${s[0]} ·</span> ${s[1]}${s[2]?' · '+links(s[2]):''}</li>`).join('')}</ol>`)
    ].join('');
  }

  function mjKey(){return `<div class="mjkey"><span>${mk('y')} reached — tinnitus measured</span><span>${mk('r')} related condition only</span><span>${mk('p')} partly reached</span><span>${mk('e')} tested, similar to placebo</span><span>${mk('n')} not reached / none found</span></div>`}
  function mjStep(t,l,s){return `<div>${mk(t)}<b>${l}</b><span>${s||'&nbsp;'}</span></div>`}
  function gapBox(icn,title,body,tm,claim){return `<div class="gbox${claim?' claim':''}"><div class="gh">${ic(icn)} ${title}</div><p>${body}</p>${tm?`<div class="tm">${tm}</div>`:''}</div>`}
  function shift(...xs){return `<div class="shift" aria-label="What changes: ${xs.map(x=>x[0]).join(', ')}">${xs.map(x=>`<span>⇄ <b>${x[0]}</b>: ${x[1]}</span>`).join('')}</div>`}
  /* ===================== RENDER: page graphics ===================== */
  R.getElementById('journey').innerHTML = `
   <div class="jbrackets" aria-hidden="true"><span>These steps can support biological plausibility</span><span>These steps test whether it helps people with tinnitus</span></div>
   <ol class="jsteps" aria-label="Evidence journey with seven steps. The first three can support biological plausibility; the last four test whether a treatment helps people with tinnitus. Laboratory and animal evidence are not evidence of benefit in people. Treatments can stop at any step.">
   ${JOURNEY.map((s,i)=>`<li class="jstep${i===6?' last':''}" style="--js:var(--j${i})"><span class="ic">${ic(s[0])}</span><span class="band">${s[4]}</span><b>${s[1]}</b><small>${s[2]}</small>${s[3]?`<span class="exit">↓ ${s[3]}</span>`:''}</li>`).join('')}
   </ol>
   <p class="jfoot">Laboratory and animal research are valuable for understanding how a treatment might work — but they are not evidence that it helps people with tinnitus. A single human study is not automatically a controlled trial, and one controlled trial is not independent replication. Treatments can stop anywhere along this pathway, and that is normal science. <strong>None of the treatments on this page has reached “established evidence” for tinnitus.</strong></p>`;

  R.getElementById('neqrow').innerHTML = NEQ.map((n,i)=>`${i?'<span class="neqsign" aria-label="is not the same as">≠</span>':''}<div class="neqtile">${shape(n[0])}<b>${n[1]}</b><span>${n[2]}</span></div>`).join('');

  const counts = {}; ORDER.forEach(c=>counts[c]=T.filter(t=>t.cat===c).length);
  R.getElementById('tiles').innerHTML = ORDER.map(c=>`<button type="button" class="tile" data-go="${c}"><span class="th">${shape(c)}<b>${SIT[c].label}</b><span class="ct">${counts[c]}</span></span><span>${SIT[c].mean}</span></button>`).join('');

  R.getElementById('legend').innerHTML = [
   [shape('early'),'<strong>Evidence situation</strong> — one of six. Shape and icon identify it; colour is never used to rank.'],
   [ic('person'),'<strong>Human tinnitus research</strong> — how many studies and people. Hearing-loss or animal studies are shown separately, never added in.'],
   [ic('tri'),'<strong>Safety note and Research underway</strong> — the only badges shown on the closed card. Tap for details. Other badges (guideline, commercial involvement, registry results only, no public results found, regional evidence, literature coverage) are in the expanded view.'],
   [ic('info'),'<strong>Explore the evidence</strong> — best evidence, independent replication, literature coverage, guideline position, commercial involvement, sources, and more.'],
   [ic('mag'),'<strong>Literature coverage</strong> — how completely we could search the research. It does not describe whether a treatment works.'],
   ['<span style="width:20px;text-align:center" aria-hidden="true">🔉🧠</span>','<strong>Loudness and distress</strong> — always reported separately. Most treatments with evidence affect distress, not loudness.']
  ].map(x=>`<div>${x[0]}<p>${x[1]}</p></div>`).join('');

  /* ===================== RENDER: cards ===================== */
  const state = {cat:'all',types:new Set(),research:false,q:''};
  function visibleBadges(t){
   const bs=t.badges.filter(b=>VISIBLE.includes(b)).sort((a,b)=>PRI.indexOf(a)-PRI.indexOf(b));
   if(!bs.length) return '';
   return `<div class="badges">${bs.map(b=>`<button type="button" class="badge ${BADGES[b].cls||''}" data-badge="${b}" data-t="${t.id}">${ic(BADGES[b].ic)}${BADGES[b].label}</button>`).join('')}</div>`;
  }
  function cardHTML(t){
   return `<article class="card" id="${t.id}" data-cat="${t.cat}" aria-labelledby="${t.id}-h">
   <div class="cardin">
    <h3 id="${t.id}-h">${t.name}</h3>
    <div class="status">${shape(t.cat)}<b>${SIT[t.cat].short}</b></div>${t.qual?`<span class="qual">${t.qual}</span>`:''}
    <div class="hline">${ic('person')}<span><span class="k">Human tinnitus research</span><span class="v">${t.human[0]}${t.human[1]?`<small>${t.human[1]}</small>`:''}</span></span></div>
    <p class="tellshort">${t.tells}</p>
    ${visibleBadges(t)}
    <button type="button" class="explore" aria-expanded="false" aria-controls="${t.id}-x">Explore the evidence ${ic('chev','i car')}</button>
   </div>
   <div class="xp" id="${t.id}-x" hidden></div>
   </article>`;
  }
  function matches(t){
   if(state.cat!=='all' && t.cat!==state.cat) return false;
   if(state.types.size && !t.type.some(x=>state.types.has(x))) return false;
   if(state.research && !t.badges.includes('underway')) return false;
   if(state.q){const h=(t.name+' '+(t.alt||'')+' '+t.desc).toLowerCase(); if(!h.includes(state.q)) return false;}
   return true;
  }
  function render(){
   const L=R.getElementById('list'); let html='', any=false;
   ORDER.forEach(c=>{
    const items=T.filter(t=>t.cat===c&&matches(t)).sort((a,b)=>a.name.localeCompare(b.name));
    if(!items.length) return; any=true;
    html+=`<section class="situ" id="sit-${c}" aria-labelledby="sit-${c}-h"><div class="situh">${shape(c)}<div><h2 id="sit-${c}-h">${SIT[c].label}</h2><p>${SIT[c].mean} <span class="ct">· ${items.length} ${items.length===1?'entry':'entries'}</span></p></div></div>
    <p class="alpha">Listed alphabetically — not ranked.</p>`;
    if(c==='nosham') html+=shamExplainer();
    html+=items.map(cardHTML).join('');
    if(c==='nobenefit') html+=timelineHTML();
    html+='</section>';
   });
   L.innerHTML = any?html:`<div class="none">No treatments match these filters. <button type="button" class="badge" id="clearF">Clear filters</button></div>`;
   const shown=L.querySelectorAll('.card').length; R.getElementById('resultStatus').textContent = shown===T.length ? `${shown} treatments shown.` : `${shown} of ${T.length} treatments shown.`;
   const cf=R.getElementById('clearF'); if(cf) cf.onclick=clearFilters;
   syncControls();
  }
  function shamExplainer(){return `<div class="explainer"><h3>Why many studies isn’t always strong evidence</h3>
   <p>Tinnitus is rated by how people feel. If people know they are receiving a treatment — and there is no placebo or sham version to compare against — hope and expectation can make results look better. A large number of such studies can still leave the main question open.</p>
   <div class="vs"><div><div class="big">11 randomized trials</div><div class="stack" aria-hidden="true">${'<i></i>'.repeat(11)}</div><p style="margin:0">Stellate ganglion block: none of the 11 trials in a 2026 meta-analysis compared the block with a sham procedure.</p></div>
   <div><div class="big">What a sham comparison adds</div><p style="margin:.3em 0 0">A look-alike procedure without the active part, so people’s expectations can’t tell the groups apart. Only then does a difference point to the treatment itself.</p></div></div></div>`}
  function timelineHTML(){
   const P2=[
    {n:'AM-101 (Keyzilen)',m:'Esketamine gel injected through the eardrum',s:['Calm overactive inner-ear signalling after acute injury','Phase II: main measure not met; some subgroup signals','2 Phase III, placebo-controlled: 343 and 741 people (sponsor-reported; the TACTT3 registry record lists 893)','Main endpoints not met. Registry results only: results posted on ClinicalTrials.gov (TACTT2) and the EU trial register (TACTT3); no journal publication found in our search'],src:'NCT01803646 · NCT02040194 · PMID 24603353'},
    {n:'Neramexane',m:'Oral medicine',s:['Block specific receptors linked to tinnitus','Phase II, 431 people: main measure not met','Phase III programme, placebo-controlled','No difference from placebo in the one Phase III result we read (EU trial register). No journal publication of the Phase III trials found in our search'],src:'PMID 21223542 · NCT00405886',site:true},
    {n:'AUT00063',m:'Oral medicine',s:['Tune nerve-cell firing (Kv3.1 channels)','—','Phase IIa, placebo-controlled: 91 people randomised, 28 days; stopped early for futility after a planned interim analysis','No benefit over placebo'],src:'PMID 30939361 · NCT02315508'},
    {n:'OTO-313',m:'Injected through the eardrum',s:['Block NMDA receptors in the inner ear','Phase 1/2: early positive signal','Phase 2, placebo-controlled: 153 people','Did not do better than placebo; development stopped'],src:'PMID 34629442 · PMID 37341760 · NCT04829214'},
    {n:'Donepezil',m:'Existing dementia medicine tested for a new use',s:['Boost brain plasticity','—','1 placebo-controlled trial: 70 people','No difference on the main measure; many stopped because of side effects'],src:'PMID 42710361 · NCT07153991'}
   ];
   const lab=['Promising idea','Early development','Controlled trials','Outcome'];
   return `<div class="explainer tone-under" id="drug-trials" style="margin-top:22px"><h3>What happens when promising treatments reach controlled trials?</h3>
   <p>Most treatments that look promising early don’t become approved treatments. Controlled trials are how we find out — and every result, positive or not, narrows the search. These are not failures of the people involved; they are how progress is made.</p>
   <div class="tl">${P2.map(p=>`<div class="prog"><h4>${p.n}</h4><p class="pm">${p.m}</p><div class="track">${p.s.map((x,i)=>`<div><b>${lab[i]}</b>${x}</div>`).join('')}</div>
   <details><summary>Sources${p.site?' · also in our research records':''}</summary><p style="font-size:.95rem">${links(p.src)}</p></details></div>`).join('')}</div>
   <div class="lessons"><div><strong>An early positive signal isn’t always confirmed</strong> (OTO-313).</div><div><strong>Why we check trial registries, not just journals</strong> (AM-101, neramexane).</div><div><strong>Tested and set aside is still progress</strong> — these mechanisms have now been examined in controlled trials.</div></div></div>`;
  }

  /* ===================== RESEARCH UNDERWAY LIST ===================== */
  R.getElementById('rlist').innerHTML = RL.map(g=>`<h3 style="margin:10px 0 4px">${g[0]}</h3>`+g[1].filter(([k])=>isActive(k)).map(([k,card])=>{const t=TR[k];return `<details class="ritem"><summary>${ic('hourglass')}<span><span class="rn">${t.t}</span><br><span class="rs">${t.size} · ${t.status}${t.stale?' · '+t.stale:''}</span></span></summary><div>${trialPanel(k)}${card?`<p style="margin:6px 0 0"><a href="#${card}" data-jump="${card}">See the related treatment card →</a></p>`:''}</div></details>`}).join('')).join('');

  /* ===================== GENERIC GAP GRAPHIC ===================== */
  R.getElementById('gengap').innerHTML =
   gapBox('paw','Laboratory or animal research','Often measures ear damage or hearing — and often gives the treatment at the moment of injury.',`${mk('r')} Tinnitus often not measured`)+
   shift(['SPECIES','animals → people'],['TIMING','prevention → treatment'])+
   gapBox('ear','Research in a related condition','e.g. sudden hearing loss, where tinnitus may be measured only as a side outcome — if at all.',`${mk('r')} Different condition`)+
   shift(['OUTCOME','hearing → tinnitus'],['POPULATION','who was studied'])+
   gapBox('person','A small study in tinnitus','Often without a placebo, in one type of tinnitus, over a few weeks.',`${mk('y')} Tinnitus measured`)+
   shift(['DELIVERY','how it’s given'],['DOSE','how much'])+
   gapBox('info','The product claim','Check whether each change above is supported by research on the product actually being sold.','',true);

  /* ===================== COVERED ELSEWHERE ===================== */
  R.getElementById('else').innerHTML=ELSE.map(e=>`<a href="treatments/${e[1]}/"><b>${e[0]} →</b>${e[2]?`<span>${e[2]}</span>`:''}</a>`).join('');

  /* ===================== FILTER CONTROLS ===================== */
  function sitButtons(){return `<button type="button" class="sitbtn" data-sit="all" aria-pressed="${state.cat==='all'}"><span class="shape" aria-hidden="true"></span>All situations<span class="ct">${T.length}</span></button>`+ORDER.map(c=>`<button type="button" class="sitbtn" data-sit="${c}" aria-pressed="${state.cat===c}">${shape(c)}${SIT[c].short}<span class="ct">${counts[c]}</span></button>`).join('')}
  function typeChecks(){return Object.entries(TYPES).map(([k,v])=>`<label class="chk"><input type="checkbox" data-type="${k}" ${state.types.has(k)?'checked':''}> ${v}</label>`).join('')}
  function syncControls(){
   R.getElementById('railSit').innerHTML=sitButtons();
   R.getElementById('railType').innerHTML=typeChecks();
   R.getElementById('rOnly').checked=state.research;
   R.getElementById('mSitLabel').textContent='Situation: '+(state.cat==='all'?'All':SIT[state.cat].short);
   const n=state.types.size+(state.research?1:0)+(state.q?1:0);
   R.getElementById('mFilCount').textContent=n?`(${n})`:'';
  }
  function clearFilters(){state.cat='all';state.types.clear();state.research=false;state.q='';R.getElementById('q').value='';render()}
  function setCat(c,scroll){state.cat=c;render();if(scroll){const el=R.getElementById(c==='all'?'th':'sit-'+c);if(el)el.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}}

  /* ===================== DIALOG ===================== */
  const dlg=R.getElementById('dlg');
  function openDlg(title,body){R.getElementById('dlgT').innerHTML=title;R.getElementById('dlgB').innerHTML=body;if(!dlg.open)dlg.showModal()}
  dlg.addEventListener('click',e=>{if(e.target===dlg||e.target.closest('[data-close]'))dlg.close()});

  /* ===================== EVENTS ===================== */
  R.addEventListener('click',e=>{
   const tile=e.target.closest('[data-go]'); if(tile){setCat(tile.dataset.go,true);return}
   const sb=e.target.closest('[data-sit]'); if(sb){setCat(sb.dataset.sit,true); if(dlg.open)dlg.close(); return}
   const jx0=e.target.closest('[data-jumpx]'); if(jx0){jumpTo(jx0.dataset.jumpx);return}
   if(e.target.closest('dialog [data-close]')) return;
   const ex=e.target.closest('.card .explore'); if(ex){toggleCard(ex);return}
   const bd=e.target.closest('[data-badge]'); if(bd){const b=BADGES[bd.dataset.badge];const t=T.find(x=>x.id===bd.dataset.t);
     if(bd.dataset.badge==='underway'&&t.trials){openDlg(`${ic('hourglass')} Research underway`,t.trials.filter(isActive).map(trialPanel).join(''))}
     else if(bd.dataset.badge==='safety'){openDlg(`${ic('tri')} Safety note`,`<p>${badgeInfo(t,'safety',false)}</p><p><button type="button" class="explore" style="margin:0" data-jumpx="${t.id}">Explore the evidence</button></p>`)}
     else{openDlg(`${ic(b.ic)} ${badgeLabel(t,bd.dataset.badge)}`,`<p>${badgeInfo(t,bd.dataset.badge)}</p>`)}return}
   const jx=e.target.closest('[data-jumpx]'); if(jx){jumpTo(jx.dataset.jumpx);return}
   if(e.target.closest('[data-cov]')){openDlg(`${ic('mag')} Literature coverage`,`<p>${COVTIP}</p><p class="muted">Extensive · Moderate · Limited. Coverage is lower where important research is published in databases we could only partly search — especially Chinese, Korean, Russian, Iranian and Indian sources.</p>`);return}
   const j=e.target.closest('[data-jump]'); if(j){e.preventDefault();jumpTo(j.dataset.jump);return}
   const ha=e.target.closest('a[href^="#"]'); if(ha){e.preventDefault();jumpTo(ha.getAttribute('href').slice(1));return}
   const cx=e.target.closest('[data-xclose]'); if(cx){const b=R.querySelector(`#${cx.dataset.xclose} .explore`);toggleCard(b,false);R.getElementById(cx.dataset.xclose).scrollIntoView();b.focus({preventScroll:true});return}
  });
  R.addEventListener('change',e=>{
   if(e.target.matches('[data-type]')){const k=e.target.dataset.type;e.target.checked?state.types.add(k):state.types.delete(k);render();if(dlg.open)openFilterSheet()}
   if(e.target.id==='rOnly'||e.target.id==='rOnlyM'){state.research=e.target.checked;render();if(dlg.open)openFilterSheet()}
  });
  R.getElementById('q').addEventListener('input',e=>{state.q=e.target.value.trim().toLowerCase();render()});
  function toggleCard(btn,force){
   const card=btn&&btn.closest('.card'); if(!card) return;
   const xp=card.querySelector('.xp'), t=T.find(x=>x.id===card.id);
   const open = force===undefined ? btn.getAttribute('aria-expanded')!=='true' : force;
   if(open && innerWidth<1180){R.querySelectorAll('.explore[aria-expanded="true"]').forEach(b=>{if(b!==btn)toggleCard(b,false)})}
   if(open && !xp.dataset.filled){xp.innerHTML=fullCard(t)+`<div class="xclose"><button type="button" data-xclose="${t.id}">Close ▲</button></div>`;xp.dataset.filled='1';toneSummaries(xp)}
   xp.hidden=!open; btn.setAttribute('aria-expanded',open);
   btn.firstChild.textContent = open?'Hide the evidence ':'Explore the evidence ';
  }
  function jumpTo(id){if(dlg.open)dlg.close();if(!R.getElementById(id)){clearFilters()}const el=R.getElementById(id);if(!el)return;const b=el.querySelector('.explore');if(b&&b.getAttribute('aria-expanded')!=='true')toggleCard(b,true);el.scrollIntoView();if(!SINGLE)history.replaceState(null,'',location.pathname+location.search+'#'+id)}
  function openFilterSheet(){openDlg('Filter &amp; search',`<label class="search" style="margin-bottom:12px"><svg class="i" viewBox="0 0 24 24">${P.mag}</svg><input type="search" id="qM" placeholder="Name, brand or other name" value="${state.q.replace(/"/g,'&quot;')}" aria-label="Search treatments"></label><h4 style="font-size:.84rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)">Type</h4>${typeChecks()}<h4 style="font-size:.84rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-top:10px">Research</h4><label class="chk"><input type="checkbox" id="rOnlyM" ${state.research?'checked':''}> Research underway only</label><div style="display:flex;gap:10px;margin-top:14px"><button type="button" class="explore" style="margin:0" data-close>Show results</button></div>`);
   const qm=R.getElementById('qM'); qm.oninput=()=>{state.q=qm.value.trim().toLowerCase();R.getElementById('q').value=qm.value;render()}}
  R.getElementById('mSit').onclick=()=>openDlg('Evidence situation',`<div class="sheetlist">${sitButtons()}</div>`);
  R.getElementById('mFil').onclick=openFilterSheet;



  render();
  if(SINGLE&&anchor&&T.some(t=>t.id===anchor))setTimeout(()=>jumpTo(anchor),50);
  if(!SINGLE&&location.hash){const id=location.hash.slice(1);if(T.some(t=>t.id===id))setTimeout(()=>jumpTo(id),50)}
  }

  // single-file preview: js/app.js calls this hook each time the page is routed to
  (window.TA_PAGE_HOOKS = window.TA_PAGE_HOOKS || {})['emerging-unproven'] = init;
  if (!SINGLE) {
    // js/app.js awaits this promise before lifting the page-load gate (html.ta-loading)
    const go = () => { window.__TA_PAGE_READY = init(); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
  }
})();
