/* Phones only: collapsible filters on the treatments browser (private preview).
   Does not touch js/app.js. It reads the chips app.js renders and clicks them, so the filtering logic is unchanged.
   Larger screens: the panel is always visible and the bar is hidden by CSS; nothing here changes the desktop page. */
(function () {
  'use strict';
  var mq = window.matchMedia('(max-width:639px)');
  var btn = document.getElementById('tfilter-btn'), panel = document.getElementById('tfilters'),
      nEl = document.getElementById('tfilter-n'), ctEl = document.getElementById('tfilter-ct'),
      clearBtn = document.getElementById('tfilter-clear'), done = document.getElementById('tfilter-done'),
      input = document.getElementById('tsearch'), tcount = document.getElementById('tcount');
  if (!btn || !panel) return;
  var ORIGINAL_PLACEHOLDER = input ? input.getAttribute('placeholder') : '';

  function setOpen(open) {
    panel.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function activeChips() {
    return Array.prototype.filter.call(panel.querySelectorAll('.chip[aria-pressed="true"]'), function (c) {
      return !(c.hasAttribute('data-cat') && c.getAttribute('data-cat') === '') && !(c.hasAttribute('data-type') && c.getAttribute('data-type') === '');
    });
  }
  function sync() {
    var n = activeChips().length;
    nEl.hidden = n === 0; nEl.textContent = String(n);
    clearBtn.hidden = n === 0;
    btn.setAttribute('aria-label', 'Filters' + (n ? ', ' + n + ' active' : ''));
    var txt = tcount ? tcount.textContent.replace(' shown', '') : '';
    ctEl.textContent = txt.indexOf('treatment') >= 0 ? txt : (txt ? txt + ' treatments' : '');
    if (done) { var lbl = txt ? 'Show ' + (txt.indexOf('treatment') >= 0 ? txt : txt + ' treatments') : 'Show treatments'; if (done.textContent !== lbl) done.textContent = lbl; }
  }
  function placeholder() { if (input) input.setAttribute('placeholder', mq.matches ? 'Search treatments…' : ORIGINAL_PLACEHOLDER); }

  btn.addEventListener('click', function () { setOpen(!panel.classList.contains('open')); });
  if (done) done.addEventListener('click', function () {
    setOpen(false);
    var h = document.querySelector('.tres-head'); if (h) h.scrollIntoView({ block: 'start', behavior: 'smooth' });
    btn.focus({ preventScroll: true });
  });
  clearBtn.addEventListener('click', function () {
    var c = panel.querySelector('#cat-chips .chip[data-cat=""]'); if (c) c.click();
    var t = panel.querySelector('#type-chips .chip[data-type=""]'); if (t) t.click();
    activeChips().forEach(function (x) { x.click(); });
    sync();
  });
  panel.addEventListener('keydown', function (e) { if (e.key === 'Escape') { setOpen(false); btn.focus(); } });
  var mo = new MutationObserver(sync);
  // watch only the chip groups (not the "Show" button, which sync() rewrites) so the observer cannot trigger itself
  ['cat-chips', 'type-chips', 'flag-chips'].forEach(function (id) {
    var g = document.getElementById(id); if (g) mo.observe(g, { attributes: true, attributeFilter: ['aria-pressed'], subtree: true, childList: true });
  });
  if (tcount) mo.observe(tcount, { childList: true, characterData: true, subtree: true });
  if (mq.addEventListener) mq.addEventListener('change', function () { placeholder(); setOpen(false); }); else if (mq.addListener) mq.addListener(placeholder);
  placeholder(); sync();
  // arriving from a link such as ?cat=... or ?flag=avail: keep the panel closed; the active count and the results heading show what is applied
})();
