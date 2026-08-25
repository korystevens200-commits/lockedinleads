/** Agency console: portfolio, MRR, client management, plans and health. */
(async function () {
  await AdminShell.init('clients');
  const area = document.getElementById('adminArea');
  const sub = document.getElementById('adminSub');
  let data = null;

  const STATUS_TONE = { active: 'accent', onboarding: 'info', paused: 'warm', cancelled: 'cold' };

  function stats(o) {
    return `<div class="stat-grid mb-5">
      <div class="stat stat-hero">
        <div class="stat-label">${UI.icon('card', 13)}Monthly recurring revenue</div>
        <div class="stat-value">${UI.money(o.mrr, { compact: true })}</div>
        <div class="stat-sub">${UI.money(o.annual_run_rate, { compact: true })} annual run rate</div>
        ${o.pending_setup_revenue ? `<div class="row gap-2 mt-3"
          style="padding-top:12px;border-top:1px solid var(--accent-line)">
          ${UI.icon('clock', 14)}<span class="small">
            <strong>${UI.money(o.pending_setup_revenue)}</strong>
            <span class="muted">in setup fees not yet collected</span></span></div>` : ''}
      </div>
      <div class="stat"><div class="stat-label">${UI.icon('building', 13)}Clients</div>
        <div class="stat-value">${UI.num(o.clients_total)}</div>
        <div class="stat-sub">${UI.num(o.clients_onboarding)} still onboarding${
          o.clients.some((c) => c.is_demo) ? ' · demo account not counted' : ''}</div></div>
      <div class="stat"><div class="stat-label">${UI.icon('check', 13)}Active clients</div>
        <div class="stat-value">${UI.num(o.clients_active)}</div>
        <div class="stat-sub">Billing and live</div></div>
      <div class="stat"><div class="stat-label">${UI.icon('inbox', 13)}Leads processed</div>
        <div class="stat-value">${UI.num(o.leads_processed)}</div>
        <div class="stat-sub">Across every account</div></div>
      <div class="stat"><div class="stat-label">${UI.icon('calendar', 13)}Appointments generated</div>
        <div class="stat-value">${UI.num(o.appointments_generated)}</div>
        <div class="stat-sub">The number clients pay for</div></div>
    </div>`;
  }

  function clientRow(c) {
    return `
      <tr data-open="${UI.esc(c.id)}" tabindex="0">
        <td>
          <div class="strong">${UI.esc(c.name)}${c.is_demo
            ? ' <span class="badge badge-plain badge-info">Demo</span>' : ''}</div>
          <div class="tiny dim">${UI.esc(c.industry)} · ${UI.esc(c.slug)}</div>
        </td>
        <td><span class="badge badge-plain badge-${STATUS_TONE[c.status] || 'neutral'}">${UI.esc(c.status)}</span></td>
        <td class="small muted">${UI.esc(c.plan || '—')}</td>
        <td class="small tabular">${c.monthly_price ? UI.money(c.monthly_price) + '/mo' : '—'}</td>
        <td class="small tabular">${UI.num(c.leads)}</td>
        <td class="small tabular accent-text strong">${UI.num(c.appointments)}</td>
        <td class="small tabular">${UI.pct(c.conversion_rate)}</td>
        <td class="tiny dim nowrap">${c.last_lead_at ? UI.relTime(c.last_lead_at) : 'no leads yet'}</td>
        <td><button class="btn btn-sm btn-ghost" data-view="${UI.esc(c.id)}">Open</button></td>
      </tr>`;
  }

  function clientCard(c) {
    return `<div class="record" data-open="${UI.esc(c.id)}">
      <div class="record-top">
        <div class="grow" style="min-width:0">
          <div class="record-name truncate">${UI.esc(c.name)}</div>
          <div class="record-meta truncate">${UI.esc(c.plan || 'No plan')}${
            c.monthly_price ? ' · ' + UI.money(c.monthly_price) + '/mo' : ''}</div>
        </div>
        <span class="badge badge-plain badge-${STATUS_TONE[c.status] || 'neutral'}">${UI.esc(c.status)}</span>
      </div>
      <div class="record-foot">
        <span>${UI.num(c.leads)} leads</span>
        <span class="accent-text strong">${UI.num(c.appointments)} booked</span>
        <span style="margin-left:auto">${c.last_lead_at ? UI.relTime(c.last_lead_at) : '—'}</span>
      </div>
    </div>`;
  }

  function healthSection(h) {
    const tone = { ok: 'accent', degraded: 'warm', error: 'hot' };
    return `<section class="card mt-4" id="health">
      <div class="between mb-4">
        <div class="card-title">System health</div>
        <span class="badge badge-plain badge-${tone[h.overall]}">${
          h.overall === 'ok' ? 'All systems normal' : h.overall === 'degraded' ? 'Running in simulated mode' : 'Attention needed'}</span>
      </div>
      <div class="stack gap-3">${h.checks.map((c) => `
        <div class="row gap-3">
          <span class="dot" style="background:var(--${c.status === 'ok' ? 'accent' : c.status === 'degraded' ? 'warn' : 'danger'})"></span>
          <div class="grow" style="min-width:0">
            <div class="small strong">${UI.esc(c.name)}</div>
            <div class="tiny dim">${UI.esc(c.detail)}</div>
          </div>
        </div>`).join('')}</div>
      <p class="tiny dim mt-4">"Simulated" means the feature works end to end but nothing leaves the
        server — add the matching credentials to go live.</p>
    </section>`;
  }

  function plansSection(plans) {
    return `<section class="card mt-4" id="plans">
      <div class="between mb-2">
        <div class="card-title">Plans &amp; pricing</div>
        <button class="btn btn-sm btn-ghost" id="addPlanBtn">+ Plan</button>
      </div>
      <p class="small muted mb-4">Prices here drive the marketing site, client billing and MRR —
        nothing is hardcoded.</p>
      <div class="record-list">${plans.map((p) => `
        <div class="record" data-plan="${UI.esc(p.id)}">
          <div class="record-top">
            <div class="grow">
              <div class="record-name">${UI.esc(p.name)}
                ${p.highlight ? '<span class="badge badge-plain badge-accent">Featured</span>' : ''}
                ${p.active ? '' : '<span class="badge badge-plain badge-cold">Hidden</span>'}</div>
              <div class="record-meta">${UI.money(p.setup_price)} setup &middot;
                ${UI.money(p.monthly_price)}/month</div>
            </div>
            <span class="btn btn-sm btn-quiet">Edit</span>
          </div>
          <div class="record-foot">
            <span class="tiny">${p.features.length} features</span>
            <span class="tiny ${p.stripe_price_id ? 'accent-text' : 'dim'}" style="margin-left:auto">
              ${p.stripe_price_id ? 'Stripe price linked' : 'No Stripe price set'}</span>
          </div>
        </div>`).join('')}</div>
    </section>`;
  }

  function render() {
    const o = data.overview;
    sub.textContent = `${UI.num(o.clients_active)} active of ${UI.num(o.clients_total)} clients · ${
      UI.money(o.mrr)} MRR`;
    area.innerHTML = `
      ${stats(o)}
      <section class="card card-flush">
        <div class="card-head"><div class="card-title">Clients</div></div>
        ${o.clients.length ? `
          <div class="table-wrap desktop-only">
            <table class="data">
              <thead><tr><th>Client</th><th>Status</th><th>Plan</th><th>MRR</th><th>Leads</th>
                <th>Booked</th><th>Conv.</th><th>Last lead</th><th></th></tr></thead>
              <tbody>${o.clients.map(clientRow).join('')}</tbody>
            </table>
          </div>
          <div class="card-body mobile-only">
            <div class="record-list">${o.clients.map(clientCard).join('')}</div>
          </div>`
          : `<div class="empty"><div class="empty-icon">${UI.icon('building')}</div>
             <div class="empty-title">No clients yet</div>
             <div class="small">Add your first client to get them live.</div></div>`}
      </section>
      ${plansSection(data.plans)}
      ${healthSection(data.health)}`;

    area.querySelectorAll('[data-open]').forEach((el) => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('[data-view]')) return;
        location.href = `/admin/client.html?id=${encodeURIComponent(el.dataset.open)}`;
      });
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') location.href = `/admin/client.html?id=${encodeURIComponent(el.dataset.open)}`;
      });
    });
    area.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', (e) => {
      e.stopPropagation();
      AdminShell.viewAs(b.dataset.view);
    }));
    area.querySelectorAll('[data-plan]').forEach((el) => el.addEventListener('click',
      () => editPlan(data.plans.find((p) => p.id === el.dataset.plan))));
    document.getElementById('addPlanBtn').addEventListener('click', () => editPlan(null));

    if (location.hash) document.querySelector(location.hash)?.scrollIntoView({ behavior: 'smooth' });
  }

  // ------------------------------------------------------------ new client
  function newClient() {
    UI.modal({
      title: 'Add a client',
      body: `<form id="clientForm">
        <div class="field"><label for="cf-name">Business name</label>
          <input class="input" id="cf-name" name="name" required placeholder="Miami Shine Cleaning" /></div>
        <div class="field-row field-row-2">
          <div class="field"><label for="cf-industry">Industry</label>
            <select class="select" id="cf-industry" name="industry">
              ${['cleaning', 'hvac', 'roofing', 'plumbing', 'electrical', 'landscaping',
                 'pest_control', 'med_spa', 'dental', 'other'].map((i) =>
                `<option value="${i}">${UI.esc(i.replace('_', ' '))}</option>`).join('')}
            </select></div>
          <div class="field"><label for="cf-plan">Plan</label>
            <select class="select" id="cf-plan" name="plan_slug">
              ${data.plans.filter((p) => p.active).map((p) =>
                `<option value="${UI.esc(p.slug)}"${p.highlight ? ' selected' : ''}>${
                  UI.esc(p.name)} — ${UI.money(p.monthly_price)}/mo</option>`).join('')}
            </select></div>
        </div>
        <div class="field-row field-row-2">
          <div class="field"><label for="cf-contact">Owner name</label>
            <input class="input" id="cf-contact" name="contact_name" /></div>
          <div class="field"><label for="cf-phone">Phone</label>
            <input class="input" id="cf-phone" name="contact_phone" type="tel" /></div>
        </div>
        <div class="field"><label for="cf-tz">Timezone</label>
          <select class="select" id="cf-tz" name="timezone">
            ${['America/New_York', 'America/Chicago', 'America/Denver', 'America/Phoenix',
               'America/Los_Angeles'].map((t) => `<option value="${t}">${t.replace('_', ' ')}</option>`).join('')}
          </select></div>
        <div class="divider mt-4 mb-4"></div>
        <p class="small muted mb-4">Create their sign-in now, or leave blank and add it later.</p>
        <div class="field"><label for="cf-email">Owner email</label>
          <input class="input" id="cf-email" name="owner_email" type="email" /></div>
        <div class="field"><label for="cf-pass">Temporary password</label>
          <input class="input" id="cf-pass" name="owner_password" type="text"
                 placeholder="At least 10 characters" /></div>
        <p class="field-error hidden" id="cf-error"></p>
      </form>`,
      footer: `<button class="btn btn-ghost grow" data-close>Cancel</button>
               <button class="btn btn-primary grow" data-save>Create client</button>`,
      onOpen(el, close) {
        el.querySelector('#cf-pass').value = Array.from(
          crypto.getRandomValues(new Uint8Array(9)), (b) => b.toString(36)).join('').slice(0, 14);
        el.querySelector('[data-save]').addEventListener('click', async (e) => {
          const error = el.querySelector('#cf-error');
          error.classList.add('hidden');
          e.target.disabled = true;
          try {
            const values = UI.formValues(el.querySelector('#clientForm'));
            const result = await API.post('/api/admin/clients', values);
            close();
            UI.toast('Client created', values.owner_email
              ? 'Send them their sign-in details to start onboarding.'
              : 'Add a login for them when ready.');
            location.href = `/admin/client.html?id=${encodeURIComponent(result.tenant.id)}`;
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove('hidden');
            e.target.disabled = false;
          }
        });
      },
    });
  }

  // ------------------------------------------------------------ plan editor
  function editPlan(plan) {
    const isNew = !plan;
    UI.modal({
      title: isNew ? 'Add a plan' : `Edit ${plan.name}`,
      body: `<form id="planForm">
        <div class="field"><label for="pf-name">Plan name</label>
          <input class="input" id="pf-name" name="name" value="${UI.esc(plan?.name || '')}" /></div>
        <div class="field-row field-row-2">
          <div class="field"><label for="pf-setup">Setup fee ($)</label>
            <input class="input" id="pf-setup" name="setup" type="number" min="0" step="50"
                   inputmode="decimal" value="${plan ? plan.setup_price : 1000}" /></div>
          <div class="field"><label for="pf-monthly">Monthly ($)</label>
            <input class="input" id="pf-monthly" name="monthly" type="number" min="0" step="50"
                   inputmode="decimal" value="${plan ? plan.monthly_price : 1000}" /></div>
        </div>
        <div class="field"><label for="pf-features">Features (one per line)</label>
          <textarea class="textarea" id="pf-features" name="features" rows="6">${
            UI.esc((plan?.features || []).join('\\n'))}</textarea></div>
        <div class="field-row field-row-2">
          <div class="field"><label for="pf-price-id">Stripe subscription price ID</label>
            <input class="input mono" id="pf-price-id" name="stripe_price_id"
                   value="${UI.esc(plan?.stripe_price_id || '')}" placeholder="price_..." /></div>
          <div class="field"><label for="pf-setup-id">Stripe setup price ID</label>
            <input class="input mono" id="pf-setup-id" name="stripe_setup_price_id"
                   value="${UI.esc(plan?.stripe_setup_price_id || '')}" placeholder="price_..." /></div>
        </div>
        <label class="switch mb-3"><input type="checkbox" name="highlight" ${plan?.highlight ? 'checked' : ''} />
          <span class="switch-track"></span><span class="switch-label">Feature this plan</span></label>
        <label class="switch"><input type="checkbox" name="active" ${plan === null || plan.active ? 'checked' : ''} />
          <span class="switch-track"></span><span class="switch-label">Show publicly</span></label>
        <p class="field-error hidden mt-3" id="pf-error"></p>
      </form>`,
      footer: `<button class="btn btn-ghost grow" data-close>Cancel</button>
               <button class="btn btn-primary grow" data-save>Save plan</button>`,
      onOpen(el, close) {
        el.querySelector('[data-save]').addEventListener('click', async (e) => {
          const error = el.querySelector('#pf-error');
          error.classList.add('hidden');
          e.target.disabled = true;
          const v = UI.formValues(el.querySelector('#planForm'));
          const payload = {
            name: v.name,
            setup_cents: Math.round(Number(v.setup || 0) * 100),
            monthly_cents: Math.round(Number(v.monthly || 0) * 100),
            features: String(v.features || '').split('\n').map((s) => s.trim()).filter(Boolean),
            highlight: v.highlight, active: v.active,
            stripe_price_id: v.stripe_price_id, stripe_setup_price_id: v.stripe_setup_price_id,
          };
          try {
            if (isNew) await API.post('/api/admin/plans', payload);
            else await API.patch(`/api/admin/plans/${encodeURIComponent(plan.id)}`, payload);
            close();
            UI.toast('Plan saved', 'Pricing updated everywhere it appears.');
            await load();
          } catch (err) {
            error.textContent = err.message;
            error.classList.remove('hidden');
            e.target.disabled = false;
          }
        });
      },
    });
  }

  async function load() {
    try {
      data = await API.get('/api/admin/overview');
      render();
    } catch (err) {
      UI.errorToast(err);
      area.innerHTML = `<div class="banner banner-danger">Could not load the console. ${UI.esc(err.message)}</div>`;
    }
  }

  document.getElementById('newClientBtn').addEventListener('click', () => {
    if (!data) return;
    newClient();
  });

  area.innerHTML = '<div class="card"><div class="skeleton" style="height:260px"></div></div>';
  await load();
})();
