/** Calendar — appointments grouped by day, upcoming first. */
(async function () {
  await Shell.init('appointments', { title: 'Calendar' });
  const area = document.getElementById('apptArea');
  const sub = document.getElementById('apptSub');

  function dayKey(ms) {
    return new Date(Number(ms)).toLocaleDateString(undefined,
      { weekday: 'long', month: 'short', day: 'numeric' });
  }

  function card(a) {
    const past = a.starts_at < Date.now();
    return `<div class="record" style="cursor:pointer" data-lead="${UI.esc(a.lead_id)}">
      <div class="record-top">
        <div class="grow" style="min-width:0">
          <div class="record-name truncate">${UI.esc(a.lead_name)}</div>
          <div class="record-meta truncate">${UI.esc(a.service || 'Appointment')}${
            a.lead_phone ? ' · ' + UI.esc(a.lead_phone) : ''}</div>
        </div>
        <span class="badge badge-${a.status === 'cancelled' ? 'LOST'
          : a.status === 'completed' ? 'CUSTOMER' : a.status === 'no_show' ? 'NO_RESPONSE' : 'BOOKED'}">
          ${UI.esc(a.status.replace('_', ' '))}</span>
      </div>
      <div class="record-foot">
        <span class="strong" style="color:var(--text)">${UI.timeOnly(a.starts_at)} – ${UI.timeOnly(a.ends_at)}</span>
        ${a.value ? `<span>${UI.money(a.value)}</span>` : ''}
        <span style="margin-left:auto" class="${past ? 'dim' : 'accent-text'}">${UI.relTime(a.starts_at)}</span>
      </div>
    </div>`;
  }

  function render(appointments) {
    const active = appointments.filter((a) => a.status !== 'cancelled');
    const upcoming = active.filter((a) => a.starts_at >= Date.now());
    const value = upcoming.reduce((sum, a) => sum + Number(a.value || 0), 0);
    sub.textContent = upcoming.length
      ? `${UI.num(upcoming.length)} upcoming · ${UI.money(value)} of booked work`
      : 'No upcoming appointments yet.';

    if (!appointments.length) {
      area.innerHTML = `<div class="card"><div class="empty">
        <div class="empty-icon">${UI.icon('calendar')}</div>
        <div class="empty-title">Nothing booked yet</div>
        <div class="small">Qualified leads are offered your open times automatically.
          Check Automation &rarr; Booking availability if nothing is being offered.</div>
      </div></div>`;
      return;
    }

    const groups = new Map();
    appointments.slice().sort((a, b) => a.starts_at - b.starts_at).forEach((a) => {
      const key = dayKey(a.starts_at);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(a);
    });

    area.innerHTML = [...groups.entries()].map(([day, items]) => `
      <section class="mb-5">
        <div class="section-head" style="margin-top:0">
          <div class="section-title">${UI.esc(day)}</div>
          <span class="tiny dim">${items.length} appointment${items.length === 1 ? '' : 's'}</span>
        </div>
        <div class="record-list">${items.map(card).join('')}</div>
      </section>`).join('');

    area.querySelectorAll('[data-lead]').forEach((el) => el.addEventListener('click',
      () => { location.href = `/app/leads.html?lead=${encodeURIComponent(el.dataset.lead)}`; }));
  }

  area.innerHTML = '<div class="card"><div class="skeleton" style="height:200px"></div></div>';
  try {
    const { appointments } = await API.get('/api/appointments?days=90');
    render(appointments);
  } catch (err) { UI.errorToast(err); }
})();
