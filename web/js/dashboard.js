/**
 * Dashboard.
 *
 * Ordered around the one number the product is sold on — APPOINTMENTS BOOKED —
 * then the work that produces more of them: leads waiting on a decision.
 */
(async function () {
  await Shell.init('dashboard', { title: 'Dashboard' });

  const els = {
    stats: document.getElementById('statsArea'),
    attention: document.getElementById('attentionList'),
    upcoming: document.getElementById('upcomingList'),
    activity: document.getElementById('activityList'),
    sub: document.getElementById('pageSub'),
    range: document.getElementById('rangeSelect'),
  };
  let days = Number(localStorage.getItem('lil_range') || 30);
  if (els.range) els.range.value = String(days);

  function statCard(label, value, sub, opts = {}) {
    return `<div class="stat">
      <div class="stat-label">${opts.icon ? UI.icon(opts.icon, 13) : ''}${UI.esc(label)}</div>
      <div class="stat-value">${value}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
    </div>`;
  }

  function renderStats(s) {
    const rangeLabel = days ? `last ${days} days` : 'all time';
    // The hero carries the number the product is sold on, plus speed-to-lead —
    // the two figures an owner should see before anything else.
    els.stats.innerHTML = `<div class="stat-grid">
      <div class="stat stat-hero">
        <div class="stat-label">${UI.icon('calendar', 13)}Appointments booked</div>
        <div class="stat-value">${UI.num(s.appointments_booked)}</div>
        <div class="stat-sub">${UI.num(s.upcoming_appointments)} upcoming &middot; ${UI.esc(rangeLabel)}</div>
        <div class="row gap-2 mt-3" style="padding-top:12px;border-top:1px solid var(--accent-line)">
          ${UI.icon('bolt', 14)}
          <span class="small"><strong>${UI.duration(s.avg_response_seconds)}</strong>
            <span class="muted">average response time</span></span>
        </div>
      </div>
      ${statCard('Total leads', UI.num(s.total_leads),
        `${UI.num(s.new_leads)} still new`, { icon: 'inbox' })}
      ${statCard('Contacted', UI.num(s.contacted_leads),
        `${UI.pct(s.response_rate)} of all leads reached`, { icon: 'chat' })}
      ${statCard('Qualified', UI.num(s.qualified_leads),
        `${UI.pct(s.qualification_rate)} qualification rate`, { icon: 'target' })}
      ${statCard('Conversion rate', UI.pct(s.conversion_rate),
        'Leads that became appointments', { icon: 'chart' })}
      ${statCard('Follow-ups pending', UI.num(s.followups_pending),
        s.followups_pending ? 'Queued and sending automatically' : 'Nothing waiting', { icon: 'clock' })}
      ${statCard('Pipeline value', UI.money(s.pipeline_value, { compact: true }),
        `${UI.money(s.booked_value, { compact: true })} booked &middot; ${UI.money(s.won_value, { compact: true })} won`,
        { icon: 'card' })}
    </div>`;
  }

  function leadRow(lead, reason) {
    return `<a class="record" href="/app/leads.html?lead=${encodeURIComponent(lead.id)}">
      <div class="record-top">
        <div class="grow" style="min-width:0">
          <div class="record-name truncate">${UI.esc(lead.name || 'Unnamed lead')}</div>
          <div class="record-meta truncate">${UI.esc(lead.service_requested || lead.source_label)}${
            lead.location ? ' · ' + UI.esc(lead.location) : ''}</div>
        </div>
        ${UI.statusBadge(lead.status)}
      </div>
      <div class="record-foot">
        <span class="accent-text strong">${UI.esc(reason)}</span>
        <span style="margin-left:auto">${UI.relTime(lead.updated_at)}</span>
      </div>
    </a>`;
  }

  function renderAttention(leads) {
    // Priority order = closest to a booking first; a stalled hot lead is the
    // most expensive thing in the pipeline.
    const scored = [];
    leads.forEach((lead) => {
      if (lead.status === 'QUALIFIED') scored.push([1, lead, 'Ready to book']);
      else if (!lead.ai_active && ['NEW', 'CONTACTED'].includes(lead.status))
        scored.push([2, lead, 'Waiting on you']);
      else if (lead.status === 'NEW') scored.push([3, lead, 'Just arrived']);
      else if (lead.status === 'CONTACTED' && lead.followup_count >= 2)
        scored.push([4, lead, `Follow-up ${lead.followup_count} sent`]);
    });
    scored.sort((a, b) => a[0] - b[0] || b[1].updated_at - a[1].updated_at);

    els.attention.innerHTML = scored.length
      ? `<div class="record-list">${scored.slice(0, 6).map(([, l, r]) => leadRow(l, r)).join('')}</div>`
      : `<div class="empty"><div class="empty-icon">${UI.icon('check')}</div>
         <div class="empty-title">All caught up</div>
         <div class="small">Every lead has been answered. New ones appear here automatically.</div></div>`;
  }

  function renderUpcoming(appointments) {
    els.upcoming.innerHTML = appointments.length
      ? `<div class="record-list">${appointments.map((a) => `
          <a class="record" href="/app/leads.html?lead=${encodeURIComponent(a.lead_id)}">
            <div class="record-top">
              <div class="grow" style="min-width:0">
                <div class="record-name truncate">${UI.esc(a.lead_name)}</div>
                <div class="record-meta truncate">${UI.esc(a.service || 'Appointment')}</div>
              </div>
              <span class="badge badge-BOOKED">${UI.esc(a.status)}</span>
            </div>
            <div class="record-foot">
              <span class="strong" style="color:var(--text)">${UI.esc(a.when)}</span>
              ${a.value ? `<span style="margin-left:auto">${UI.money(a.value)}</span>` : ''}
            </div>
          </a>`).join('')}</div>`
      : `<div class="empty"><div class="empty-icon">${UI.icon('calendar')}</div>
         <div class="empty-title">No appointments scheduled</div>
         <div class="small">Qualified leads get offered your open times automatically.</div></div>`;
  }

  const ACTIVITY_TONE = {
    booked: 'accent', customer: 'accent', qualified: 'warm', handoff: 'warm',
    opt_out: 'cold', lost: 'cold', out_of_area: 'cold', no_response: 'cold',
  };

  function renderActivity(items) {
    els.activity.innerHTML = items.length
      ? `<div class="stack gap-3">${items.map((a) => `
          <div class="row gap-3" style="align-items:flex-start">
            <span class="badge badge-plain badge-${ACTIVITY_TONE[a.type] || 'neutral'}"
                  style="margin-top:2px">${UI.esc(a.type.replace(/_/g, ' '))}</span>
            <div class="grow" style="min-width:0">
              <div class="small">${UI.esc(a.message)}</div>
              <div class="tiny dim mt-1">${UI.relTime(a.created_at)}</div>
            </div>
          </div>`).join('')}</div>`
      : `<div class="empty small">Nothing has happened yet.</div>`;
  }

  async function load() {
    try {
      const data = await API.get(`/api/dashboard?days=${days}`);
      renderStats(data.summary);
      renderAttention(data.recent_leads);
      renderUpcoming(data.upcoming_appointments);
      renderActivity(data.activity);
      const s = data.summary;
      els.sub.textContent = s.total_leads
        ? `${UI.num(s.appointments_booked)} appointment${s.appointments_booked === 1 ? '' : 's'} booked from ${UI.num(s.total_leads)} leads`
        : 'No leads yet — connect a source or add one manually to see the assistant work.';
      Shell.setCount('leads', data.summary.status_counts.NEW + data.summary.handoffs_pending);
      document.title = `${s.appointments_booked} booked — LockedinLeads`;
    } catch (err) {
      UI.errorToast(err);
      els.stats.innerHTML = `<div class="banner banner-danger">Could not load your dashboard. ${UI.esc(err.message)}</div>`;
    }
  }

  els.range?.addEventListener('change', () => {
    days = Number(els.range.value);
    localStorage.setItem('lil_range', String(days));
    load();
  });
  document.getElementById('newLeadBtn').addEventListener('click', () => LeadForm.open(() => load()));

  els.stats.innerHTML = `<div class="stat-grid">${Array.from({ length: 7 }, (_, i) =>
    `<div class="stat${i === 0 ? ' stat-hero' : ''}">
       <div class="stat-label skeleton">Loading</div>
       <div class="stat-value skeleton">000</div></div>`).join('')}</div>`;
  await load();
  setInterval(load, 30000);   // the pipeline moves without a refresh
})();
