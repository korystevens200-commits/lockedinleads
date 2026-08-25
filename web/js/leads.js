/**
 * Leads list. Table on desktop, tappable cards on mobile — same data, layout
 * chosen by what the device can actually show.
 */
(async function () {
  await Shell.init('leads', { title: 'Leads' });

  const els = {
    area: document.getElementById('leadsArea'),
    filters: document.getElementById('statusFilters'),
    search: document.getElementById('searchInput'),
    sub: document.getElementById('leadsSub'),
  };
  let status = new URLSearchParams(location.search).get('status') || '';
  let query = '';
  let leads = [];
  let counts = {};

  function renderFilters() {
    const all = [['', 'All'], ...UI.STATUSES.map((s) => [s, UI.STATUS_LABEL[s]])];
    els.filters.innerHTML = all.map(([value, label]) => {
      const count = value ? (counts[value] || 0) : (counts.TOTAL || 0);
      return `<button class="chip${value === status ? ' is-active' : ''}" data-status="${value}"
        role="tab" aria-selected="${value === status}">
        ${UI.esc(label)}<span class="tiny dim">${count}</span></button>`;
    }).join('');
    els.filters.querySelectorAll('[data-status]').forEach((b) => b.addEventListener('click', () => {
      status = b.dataset.status;
      load();
    }));
  }

  const OPEN = ['NEW', 'CONTACTED', 'QUALIFIED'];

  function assistantCell(lead) {
    if (lead.opted_out) return '<span class="badge badge-plain badge-cold">Opted out</span>';
    // Once a lead is booked, won or closed there is nothing for the assistant
    // to be "active" on — showing a state there is just noise.
    if (!OPEN.includes(lead.status)) return '<span class="dim">—</span>';
    return lead.ai_active
      ? '<span class="badge badge-plain badge-accent">AI active</span>'
      : '<span class="badge badge-plain badge-warm">Human</span>';
  }

  function nextAction(lead) {
    if (lead.opted_out) return { text: 'Opted out', tone: 'dim' };
    if (!lead.ai_active && ['NEW', 'CONTACTED', 'QUALIFIED'].includes(lead.status))
      return { text: 'Waiting on you', tone: 'accent-text strong' };
    if (lead.status === 'QUALIFIED') return { text: 'Ready to book', tone: 'accent-text strong' };
    if (lead.next_followup_at) return { text: `Follow-up ${UI.relTime(lead.next_followup_at)}`, tone: 'muted' };
    if (lead.status === 'BOOKED') return { text: 'Booked', tone: 'accent-text' };
    if (lead.status === 'CUSTOMER') return { text: 'Won', tone: 'accent-text' };
    return { text: '—', tone: 'dim' };
  }

  function renderTable() {
    if (!leads.length) {
      els.area.innerHTML = `<div class="card"><div class="empty">
        <div class="empty-icon">${UI.icon('inbox')}</div>
        <div class="empty-title">${query || status ? 'No leads match this view' : 'No leads yet'}</div>
        <div class="small">${query || status
          ? 'Try clearing the search or filter.'
          : 'Connect a lead source or add one manually — the assistant replies the moment it arrives.'}</div>
      </div></div>`;
      return;
    }

    const rows = leads.map((lead) => {
      const action = nextAction(lead);
      return { lead, action };
    });

    els.area.innerHTML = `
      <div class="card card-flush desktop-only">
        <div class="table-wrap">
          <table class="data">
            <thead><tr>
              <th>Lead</th><th>Source</th><th>Service</th><th>Status</th>
              <th>Assistant</th><th>Next step</th><th>Value</th><th>Updated</th>
            </tr></thead>
            <tbody>${rows.map(({ lead, action }) => `
              <tr data-id="${UI.esc(lead.id)}" tabindex="0">
                <td>
                  <div class="strong">${UI.esc(lead.name || 'Unnamed lead')}</div>
                  <div class="tiny dim">${UI.esc(lead.phone || lead.email || '—')}</div>
                </td>
                <td class="small muted nowrap">${UI.esc(lead.source_label)}</td>
                <td class="small muted">${UI.esc(lead.service_requested || '—')}</td>
                <td>${UI.statusBadge(lead.status)}</td>
                <td>${assistantCell(lead)}</td>
                <td class="small ${action.tone} nowrap">${UI.esc(action.text)}</td>
                <td class="small tabular">${lead.estimated_value ? UI.money(lead.estimated_value) : '—'}</td>
                <td class="tiny dim nowrap">${UI.relTime(lead.updated_at)}</td>
              </tr>`).join('')}</tbody>
          </table>
        </div>
      </div>

      <div class="record-list mobile-only">${rows.map(({ lead, action }) => `
        <button class="record" data-id="${UI.esc(lead.id)}">
          <div class="record-top">
            <div class="grow" style="min-width:0">
              <div class="record-name truncate">${UI.esc(lead.name || 'Unnamed lead')}</div>
              <div class="record-meta truncate">${UI.esc(lead.phone || lead.email || lead.source_label)}</div>
            </div>
            ${UI.statusBadge(lead.status)}
          </div>
          <div class="record-meta mt-2 truncate">${UI.esc(lead.service_requested || '—')}${
            lead.location ? ' · ' + UI.esc(lead.location) : ''}</div>
          <div class="record-foot">
            <span class="${action.tone}">${UI.esc(action.text)}</span>
            ${lead.estimated_value ? `<span>${UI.money(lead.estimated_value)}</span>` : ''}
            <span style="margin-left:auto">${UI.relTime(lead.updated_at)}</span>
          </div>
        </button>`).join('')}</div>`;

    els.area.querySelectorAll('[data-id]').forEach((row) => {
      row.addEventListener('click', () => LeadPanel.open(row.dataset.id, load));
      row.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); LeadPanel.open(row.dataset.id, load); }
      });
    });
  }

  async function load() {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (query) params.set('q', query);
    try {
      const data = await API.get(`/api/leads?${params}`);
      leads = data.leads;
      counts = data.counts;
      renderFilters();
      renderTable();
      const openCount = (counts.NEW || 0) + (counts.CONTACTED || 0) + (counts.QUALIFIED || 0);
      els.sub.textContent = `${UI.num(counts.TOTAL || 0)} total · ${UI.num(openCount)} still open · ${
        UI.num((counts.BOOKED || 0) + (counts.CUSTOMER || 0))} booked or won`;
    } catch (err) {
      UI.errorToast(err);
    }
  }

  els.search.addEventListener('input', UI.debounce(() => {
    query = els.search.value.trim();
    load();
  }));
  document.getElementById('newLeadBtn').addEventListener('click', () =>
    LeadForm.open((lead) => { load(); LeadPanel.open(lead.id, load); }));

  els.area.innerHTML = `<div class="card"><div class="skeleton" style="height:220px"></div></div>`;
  await load();

  // Deep link: /app/leads.html?lead=… opens straight into the conversation.
  const deepLink = new URLSearchParams(location.search).get('lead');
  if (deepLink) LeadPanel.open(deepLink, load);

  setInterval(() => { if (!document.querySelector('.detail-sheet')) load(); }, 25000);
})();
