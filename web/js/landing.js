/**
 * Marketing site behaviour: live pricing from the API, the ROI calculator,
 * scroll reveals and icon injection.
 *
 * Pricing is never hardcoded here — it is read from /api/public/config so the
 * agency can change plans without touching the site.
 */
(function () {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  // Inline the icon set into placeholders (keeps the markup readable).
  $$('[data-icon]').forEach((el) => { el.innerHTML = UI.icon(el.dataset.icon, 18); });
  $('#year').textContent = new Date().getFullYear();

  // ------------------------------------------------------------- pricing
  let plans = [];

  function renderPricing() {
    const grid = $('#priceGrid');
    if (!plans.length) {
      grid.innerHTML = '<p class="muted" style="text-align:center">Pricing is available on request.</p>';
      return;
    }
    grid.innerHTML = plans.map((p) => `
      <div class="price-card${p.highlight ? ' featured' : ''}">
        ${p.highlight ? '<span class="price-tag">Most popular</span>' : ''}
        <div class="price-name">${UI.esc(p.name)}</div>
        <div class="price-amount">${UI.money(p.monthly_price)}<span>/month</span></div>
        <div class="price-setup">${UI.money(p.setup_price)} one-time setup</div>
        <ul class="price-features">${p.features.map((f) =>
          `<li><span class="tick">${UI.icon('check', 16)}</span><span>${UI.esc(f)}</span></li>`).join('')}</ul>
        <a class="btn ${p.highlight ? 'btn-primary' : 'btn-ghost'} btn-block" href="#book" data-book>Book a Demo</a>
      </div>`).join('');
    bindBookLinks();
  }

  // ------------------------------------------------------------ ROI calc
  function calcRoi() {
    const leads = Math.max(0, Number($('#roiLeads').value) || 0);
    const value = Math.max(0, Number($('#roiValue').value) || 0);
    const rate = Math.min(100, Math.max(0, Number($('#roiRate').value) || 0));
    const lift = Math.min(100 - rate, Math.max(0, Number($('#roiLift').value) || 0));

    // Round through every step: floating-point noise otherwise shows up as
    // "$2,400.00" instead of "$2,400" and "8.000000000000002" extra jobs.
    const round1 = (n) => Math.round(n * 10) / 10;
    const round2 = (n) => Math.round(n * 100) / 100;
    const now = round1(leads * (rate / 100));
    const then = round1(leads * ((rate + lift) / 100));
    const delta = round1(then - now);
    const extra = round2(delta * value);

    // The plan used for the comparison comes from the live catalogue.
    const plan = plans.find((p) => p.highlight) || plans[1] || plans[0];
    const cost = plan ? plan.monthly_price : 0;

    $('#roiNow').textContent = now.toFixed(now % 1 === 0 ? 0 : 1);
    $('#roiThen').textContent = then.toFixed(then % 1 === 0 ? 0 : 1);
    $('#roiDelta').textContent = delta.toFixed(delta % 1 === 0 ? 0 : 1);
    $('#roiExtra').textContent = UI.money(extra);
    $('#roiYear').textContent = UI.money(round2(extra * 12));
    $('#roiCost').textContent = plan ? `−${UI.money(cost)}` : '—';
    const net = round2(extra - cost);
    const netEl = $('#roiNet');
    netEl.textContent = UI.money(net);
    netEl.className = net >= 0 ? 'accent-text' : '';
    netEl.style.color = net >= 0 ? '' : 'var(--danger)';
  }

  ['#roiLeads', '#roiValue', '#roiRate', '#roiLift'].forEach((sel) => {
    $(sel)?.addEventListener('input', calcRoi);
  });

  // -------------------------------------------------------- book a demo
  let bookingUrl = '';

  function bindBookLinks() {
    $$('[data-book]').forEach((el) => {
      if (bookingUrl) {
        el.setAttribute('href', bookingUrl);
        el.setAttribute('target', '_blank');
        el.setAttribute('rel', 'noopener');
      } else {
        el.setAttribute('href', '#book');
      }
    });
  }

  // ----------------------------------------------------- scroll reveals
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
    $$('.reveal').forEach((el) => observer.observe(el));
  } else {
    $$('.reveal').forEach((el) => el.classList.add('in'));
  }

  // ------------------------------------------------------------- boot
  fetch('/api/public/config', { headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data) throw new Error('no config');
      plans = data.plans || [];
      bookingUrl = data.booking_url || '';
      renderPricing();
      calcRoi();
      bindBookLinks();
      if (data.contact_email) {
        const link = $('#contactLink');
        link.href = `mailto:${data.contact_email}`;
        link.textContent = 'Contact';
        link.classList.remove('hidden');
      }
    })
    .catch(() => {
      renderPricing();
      calcRoi();
    });
})();
