/** Single client account view for the agency. */
(async function () {
  await AdminShell.init('clients');
  const area = document.getElementById('clientArea');
  const nameEl = document.getElementById('clientName');
  const subEl = document.getElementById('clientSub');
  const tenantId = new URLSearchParams(location.search).get('id');
  let data = null;

  if (!tenantId) {
    area.innerHTML = '<div class="banner banner-danger">No client selected.</div>';
    return;
  }

  function render() {
    const t = data.tenant;
    const s = data.summary;
    const sub = data.subscription;
    nameEl.textContent = t.name;
    subEl.textContent = `${t.industry} · ${t.timezone} · created ${UI.relTime(t.created_at)}`;

    area.innerHTML = `
      <div class="row gap-2 mb-4" style="flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" id="viewAsBtn">${UI.icon('home', 16)} Open their dashboard</button>
        <button class="btn btn-ghost btn-sm" id="editBtn">Edit account</button>
        <button class="btn btn-ghost btn-sm" id="addUserBtn">Add a login</button>
        ${t.status === 'active'
          ? '<button class="btn btn-ghost btn-sm" data-status="paused">Pause account</button>'
          : '<button class="btn btn-ghost btn-sm" data-status="active">Activate account</button>'}
      </div>

      <div class="stat-grid mb-5">
        <div class="stat stat-hero">
          <div class="stat-label">${UI.icon('calendar', 13)}Appointments booked</div>
          <div class="stat-value">${UI.num(s.appointments_booked)}</div>
          <div class="stat-sub">Last 30 days &middot; ${UI.num(s.upcoming_appointments)} upcoming</div>
        </div>
        <div class="stat"><div class="stat-label">Leads</div>
          <div class="stat-value">${UI.num(s.total_leads)}</div>
          <div class="stat-sub">${UI.num(s.new_leads)} unworked</div></div>
        <div class="stat"><div class="stat-label">Conversion</div>
          <div class="stat-value">${UI.pct(s.conversion_rate)}</div>
          <div class="stat-sub">Leads to appointments</div></div>
        <div class="stat"><div class="stat-label">Response time</div>
          <div class="stat-value">${UI.duration(s.avg_response_seconds)}</div>
          <div class="stat-sub">Average first reply</div></div>
        <div class="stat"><div class="stat-label">Customers won</div>
          <div class="stat-value">${UI.num(s.customers_won)}</div>
          <div class="stat-sub">${UI.money(s.won_value, { compact: true })} completed</div></div>
      </div>

      <div class="grid-2">
        <section class="card">
          <div class="card-title mb-4">Account</div>
          <div class="kv kv-2">
            <div class="kv-item"><div class="kv-label">Status</div>
              <div class="kv-value">${UI.esc(t.status)}</div></div>
            <div class="kv-item"><div class="kv-label">Setup complete</div>
              <div class="kv-value">${t.onboarded_at ? 'Yes · ' + UI.relTime(t.onboarded_at)
                : `Step ${t.onboarding_step} of 7`}</div></div>
            <div class="kv-item"><div class="kv-label">Plan</div>
              <div class="kv-value">${UI.esc(sub?.plan?.name || 'None')}</div></div>
            <div class="kv-item"><div class="kv-label">Billing</div>
              <div class="kv-value">${sub ? UI.esc(sub.status) : '—'}${
                sub?.setup_paid ? ' · setup paid' : sub ? ' · setup unpaid' : ''}</div></div>
            <div class="kv-item"><div class="kv-label">Contact</div>
              <div class="kv-value">${UI.esc(t.contact_name || '—')}</div></div>
            <div class="kv-item"><div class="kv-label">Email</div>
              <div class="kv-value">${UI.esc(t.contact_email || '—')}</div></div>
            <div class="kv-item"><div class="kv-label">Services</div>
              <div class="kv-value">${data.services.length} configured</div></div>
            <div class="kv-item"><div class="kv-label">Service areas</div>
              <div class="kv-value">${data.areas.length} configured</div></div>
          </div>
          ${data.services.length === 0 || data.areas.length === 0 ? `
            <div class="banner banner-warn mt-4">
              <div>${UI.icon('bolt', 16)}</div>
              <div>This account cannot qualify leads properly until services and service areas
                are set. Open their dashboard to finish setup.</div>
            </div>` : ''}
        </section>

        <section class="card">
          <div class="card-title mb-4">Logins</div>
          ${data.users.length ? `<div class="stack gap-2">${data.users.map((u) => `
            <div class="between card card-pad-sm">
              <div style="min-width:0">
                <div class="small strong truncate">${UI.esc(u.name || u.email)}</div>
                <div class="tiny dim truncate">${UI.esc(u.email)} · ${UI.esc(u.role)}</div>
              </div>
              <span class="tiny dim nowrap">${u.last_login_at ? UI.relTime(u.last_login_at) : 'never signed in'}</span>
            </div>`).join('')}</div>`
            : '<p class="small muted">No logins yet — this client cannot sign in.</p>'}
        </section>
      </div>

      <section class="card card-flush mt-4">
        <div class="card-head"><div class="card-title">Recent leads</div></div>
        <div class="card-body">
          ${data.recent_leads.length ? `<div class="record-list">${data.recent_leads.map((l) => `
            <div class="record" style="cursor:default">
              <div class="record-top">
                <div class="grow" style="min-width:0">
                  <div class="record-name truncate">${UI.esc(l.name || 'Unnamed lead')}</div>
                  <div class="record-meta truncate">${UI.esc(l.source_label)}${
                    l.service_requested ? ' · ' + UI.esc(l.service_requested) : ''}</div>
                </div>
                ${UI.statusBadge(l.status)}
              </div>
              <div class="record-foot"><span>${UI.relTime(l.created_at)}</span></div>
            </div>`).join('')}</div>`
            : '<p class="small muted">No leads yet.</p>'}
        </div>
      </section>

      <section class="card mt-4">
        <div class="card-title mb-4">Activity</div>
        ${data.activity.length ? `<div class="stack gap-3">${data.activity.map((a) => `
          <div class="row gap-3" style="align-items:flex-start">
            <span class="badge badge-plain badge-neutral" style="margin-top:2px">${
              UI.esc(a.type.replace(/_/g, ' '))}</span>
            <div class="grow"><div class="small">${UI.esc(a.message)}</div>
              <div class="tiny dim mt-1">${UI.relTime(a.created_at)}</div></div>
          </div>`).join('')}</div>`
          : '<p class="small muted">Nothing yet.</p>'}
      </section>`;

    document.getElementById('viewAsBtn').addEventListener('click', () => AdminShell.viewAs(tenantId));
    document.getElementById('editBtn').addEventListener('click', editAccount);
    document.getElementById('addUserBtn').addEventListener('click', addUser);
    area.querySelectorAll('[data-status]').forEach((b) => b.addEventListener('click', async () => {
      const next = b.dataset.status;
      if (next === 'paused' && !(await UI.confirmDialog('Pause this account?',
        'The assistant stops replying and following up for this client until you reactivate it.',
        'Pause account'))) return;
      try {
        await API.patch(`/api/admin/clients/${encodeURIComponent(tenantId)}`, { status: next });
        UI.toast(next === 'paused' ? 'Account paused' : 'Account activated');
        await load();
      } catch (err) { UI.errorToast(err); }
    }));
  }

  function editAccount() {
    const t = data.tenant;
    UI.modal({
      title: 'Edit account',
      body: `<form id="editForm">
        <div class="field"><label for="ef-name">Business name</label>
          <input class="input" id="ef-name" name="name" value="${UI.esc(t.name)}" /></div>
        <div class="field-row field-row-2">
          <div class="field"><label for="ef-contact">Owner name</label>
            <input class="input" id="ef-contact" name="contact_name" value="${UI.esc(t.contact_name)}" /></div>
          <div class="field"><label for="ef-phone">Phone</label>
            <input class="input" id="ef-phone" name="contact_phone" value="${UI.esc(t.contact_phone)}" /></div>
        </div>
        <div class="field"><label for="ef-email">Contact email</label>
          <input class="input" id="ef-email" name="contact_email" type="email"
                 value="${UI.esc(t.contact_email)}" /></div>
        <div class="field"><label for="ef-plan">Plan</label>
          <select class="select" id="ef-plan" name="plan_slug">
            <option value="">Leave unchanged</option>
            ${(data.plans || []).map((p) => `<option value="${UI.esc(p.slug)}">${UI.esc(p.name)}</option>`).join('')}
          </select></div>
        <p class="field-error hidden" id="ef-error"></p>
      </form>`,
      footer: `<button class="btn btn-ghost grow" data-close>Cancel</button>
               <button class="btn btn-primary grow" data-save>Save</button>`,
      onOpen(el, close) {
        el.querySelector('[data-save]').addEventListener('click', async (e) => {
          e.target.disabled = true;
          const error = el.querySelector('#ef-error');
          try {
            const v = UI.formValues(el.querySelector('#editForm'));
            if (!v.plan_slug) delete v.plan_slug;
            await API.patch(`/api/admin/clients/${encodeURIComponent(tenantId)}`, v);
            close();
            UI.toast('Account updated');
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

  function addUser() {
    UI.modal({
      title: 'Add a login',
      body: `<form id="userForm">
        <div class="field"><label for="uf-name">Name</label>
          <input class="input" id="uf-name" name="name" /></div>
        <div class="field"><label for="uf-email">Email</label>
          <input class="input" id="uf-email" name="email" type="email" required /></div>
        <div class="field"><label for="uf-pass">Temporary password</label>
          <input class="input" id="uf-pass" name="password" type="text" /></div>
        <div class="field"><label for="uf-role">Role</label>
          <select class="select" id="uf-role" name="role">
            <option value="owner">Owner — full access including billing</option>
            <option value="staff">Staff — leads and conversations only</option>
          </select></div>
        <p class="field-error hidden" id="uf-error"></p>
      </form>`,
      footer: `<button class="btn btn-ghost grow" data-close>Cancel</button>
               <button class="btn btn-primary grow" data-save>Create login</button>`,
      onOpen(el, close) {
        el.querySelector('#uf-pass').value = Array.from(
          crypto.getRandomValues(new Uint8Array(9)), (b) => b.toString(36)).join('').slice(0, 14);
        el.querySelector('[data-save]').addEventListener('click', async (e) => {
          e.target.disabled = true;
          const error = el.querySelector('#uf-error');
          error.classList.add('hidden');
          try {
            const v = UI.formValues(el.querySelector('#userForm'));
            await API.post(`/api/admin/clients/${encodeURIComponent(tenantId)}/users`, v);
            close();
            UI.toast('Login created', 'Send them the email and temporary password.');
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
      const [detail, plansData] = await Promise.all([
        API.get(`/api/admin/clients/${encodeURIComponent(tenantId)}`),
        API.get('/api/admin/plans'),
      ]);
      data = { ...detail, plans: plansData.plans };
      render();
    } catch (err) {
      UI.errorToast(err);
      area.innerHTML = `<div class="banner banner-danger">${UI.esc(err.message)}</div>`;
    }
  }

  area.innerHTML = '<div class="card"><div class="skeleton" style="height:240px"></div></div>';
  await load();
})();
