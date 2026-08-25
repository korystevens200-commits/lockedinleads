/** Billing: current plan, plan switching, Stripe checkout (or mock mode). */
(async function () {
  await Shell.init('billing', { title: 'Billing' });
  const area = document.getElementById('billingArea');

  function planCard(plan, current) {
    const isCurrent = current && current.plan && current.plan.id === plan.id;
    return `<div class="card${plan.highlight ? '' : ''}" style="${
      isCurrent ? 'border-color:var(--accent-line);background:linear-gradient(150deg,var(--accent-soft),transparent 60%)' : ''}">
      <div class="between mb-3">
        <div class="card-title">${UI.esc(plan.name)}</div>
        ${isCurrent ? '<span class="badge badge-plain badge-accent">Current</span>'
          : plan.highlight ? '<span class="badge badge-plain badge-info">Popular</span>' : ''}
      </div>
      <div class="stat-value" style="font-size:30px">${UI.money(plan.monthly_price)}<span
        class="small muted" style="font-weight:500">/mo</span></div>
      <div class="small muted mb-4">${UI.money(plan.setup_price)} one-time setup</div>
      <ul class="stack gap-2 mb-5">${plan.features.map((f) =>
        `<li class="row gap-2 small"><span class="accent-text">${UI.icon('check', 15)}</span>
          <span>${UI.esc(f)}</span></li>`).join('')}</ul>
      ${isCurrent ? '<button class="btn btn-ghost btn-block" disabled>Your plan</button>'
        : `<button class="btn btn-primary btn-block" data-plan="${UI.esc(plan.slug)}">Switch to ${UI.esc(plan.name)}</button>`}
    </div>`;
  }

  function render(data) {
    const sub = data.subscription;
    const statusTone = { active: 'accent', trialing: 'info', past_due: 'warm', cancelled: 'cold' };
    area.innerHTML = `
      ${data.stripe.mode === 'mock' ? `
        <div class="banner banner-warn mb-4">
          <div>${UI.icon('card', 18)}</div>
          <div><strong>Stripe is not connected on this server.</strong> Plan changes are recorded locally
            so you can test the flow — no card is charged. Add <span class="mono">STRIPE_SECRET_KEY</span>
            to go live.</div>
        </div>` : ''}

      <div class="card mb-5">
        <div class="between mb-4">
          <div>
            <div class="label">Current plan</div>
            <div class="card-title mt-1">${UI.esc(sub?.plan?.name || 'No plan selected')}</div>
          </div>
          ${sub ? `<span class="badge badge-plain badge-${statusTone[sub.status] || 'neutral'}">${
            UI.esc(sub.status.replace('_', ' '))}</span>` : ''}
        </div>
        <div class="kv kv-2">
          <div class="kv-item"><div class="kv-label">Monthly</div>
            <div class="kv-value">${sub?.plan ? UI.money(sub.plan.monthly_price) : '—'}</div></div>
          <div class="kv-item"><div class="kv-label">Setup fee</div>
            <div class="kv-value">${sub?.plan ? UI.money(sub.plan.setup_price) : '—'}
              ${sub?.setup_paid ? '<span class="badge badge-plain badge-accent" style="margin-left:6px">Paid</span>' : ''}</div></div>
          <div class="kv-item"><div class="kv-label">Renews</div>
            <div class="kv-value">${sub?.current_period_end ? UI.dateTime(sub.current_period_end) : '—'}</div></div>
          <div class="kv-item"><div class="kv-label">Account status</div>
            <div class="kv-value">${UI.esc(data.tenant_status)}</div></div>
        </div>
        ${sub && !sub.setup_paid && sub.plan ? `
          <button class="btn btn-outline btn-block mt-5" data-setup="${UI.esc(sub.plan.slug)}">
            Pay the ${UI.money(sub.plan.setup_price)} setup fee</button>` : ''}
      </div>

      <div class="section-head" style="margin-top:0"><div class="section-title">Plans</div></div>
      <div class="grid-3">${data.plans.map((p) => planCard(p, sub)).join('')}</div>

      <p class="tiny dim mt-4">Questions about billing? Contact your account manager.</p>`;

    area.querySelectorAll('[data-plan]').forEach((b) => b.addEventListener('click',
      () => checkout(b.dataset.plan, 'subscription', b)));
    area.querySelectorAll('[data-setup]').forEach((b) => b.addEventListener('click',
      () => checkout(b.dataset.setup, 'setup', b)));
  }

  async function checkout(planSlug, kind, button) {
    button.disabled = true;
    const original = button.textContent;
    button.textContent = 'Starting…';
    try {
      const result = await API.post('/api/billing/checkout', { plan_slug: planSlug, kind });
      if (result.mock) {
        UI.toast('Recorded in test mode', result.message);
        await load();
      } else if (result.url) {
        location.href = result.url;
      }
    } catch (err) {
      UI.errorToast(err);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  async function load() {
    try { render(await API.get('/api/billing')); } catch (err) { UI.errorToast(err); }
  }

  area.innerHTML = '<div class="card"><div class="skeleton" style="height:200px"></div></div>';
  await load();
  if (new URLSearchParams(location.search).get('checkout') === 'success') {
    UI.toast('Payment complete', 'Your plan is up to date.');
  }
})();
