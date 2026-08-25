/**
 * Reports.
 *
 * Written for a business owner, not an analyst: plain words, one headline
 * number (appointments booked), and a funnel that shows exactly where leads
 * are being lost.
 */
(async function () {
  await Shell.init('reports', { title: 'Reports' });

  const area = document.getElementById('reportArea');
  const rangeSelect = document.getElementById('rangeSelect');
  const sub = document.getElementById('reportSub');
  let days = Number(localStorage.getItem('lil_range') || 30);
  rangeSelect.value = String(days);

  function funnel(s) {
    const steps = [
      ['Leads received', s.total_leads, 'var(--st-new)', 'Everyone who reached out'],
      ['Got a response', s.contacted_leads, 'var(--st-contacted)', 'The assistant replied'],
      ['Qualified', s.qualified_leads, 'var(--st-qualified)', 'Right service, right area, questions answered'],
      ['Appointments booked', s.appointments_booked, 'var(--st-booked)', 'A time on the calendar'],
      ['Customers won', s.customers_won, 'var(--st-customer)', 'Job completed'],
    ];
    const max = Math.max(1, s.total_leads);
    return `<div class="funnel">${steps.map(([label, value, color, hint]) => `
      <div class="funnel-step">
        <div class="funnel-top">
          <span class="funnel-label">${UI.esc(label)}</span>
          <span class="funnel-value">${UI.num(value)}
            <span class="tiny dim">${s.total_leads ? UI.pct((value / max) * 100) : '0%'}</span></span>
        </div>
        <div class="funnel-bar"><span style="width:${s.total_leads ? (value / max) * 100 : 0}%;background:${color}"></span></div>
        <div class="tiny dim">${UI.esc(hint)}</div>
      </div>`).join('')}</div>`;
  }

  /** Hand-drawn SVG bar chart — no chart library, no build step.
   *  The viewBox scales with the number of days so bars keep real width
   *  instead of collapsing to hairlines over a 90-day range. */
  function chart(series) {
    if (!series.length) return '<p class="small muted">No data in this range yet.</p>';
    const barW = 10, h = 100, w = series.length * barW;
    const max = Math.max(1, ...series.map((d) => Math.max(d.leads, d.appointments)));
    const gap = barW * 0.14;
    const half = (barW - gap * 3) / 2;
    const grid = [0.25, 0.5, 0.75, 1].map((f) =>
      `<line x1="0" y1="${h - f * h}" x2="${w}" y2="${h - f * h}"
             stroke="var(--border)" stroke-width="0.5" vector-effect="non-scaling-stroke"/>`).join('');
    const bars = series.map((d, i) => {
      const x = i * barW + gap;
      const lh = Math.max(d.leads ? 1.5 : 0, (d.leads / max) * h);
      const ah = Math.max(d.appointments ? 1.5 : 0, (d.appointments / max) * h);
      return `
        <rect x="${x}" y="${h - lh}" width="${half}" height="${lh}"
              fill="var(--st-new)" opacity="0.6"><title>${d.leads} leads</title></rect>
        <rect x="${x + half + gap}" y="${h - ah}" width="${half}" height="${ah}"
              fill="var(--accent)"><title>${d.appointments} appointments</title></rect>`;
    }).join('');
    const first = new Date(series[0].date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const last = new Date(series[series.length - 1].date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return `
      <svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img"
           aria-label="Daily leads and appointments">${grid}${bars}</svg>
      <div class="between mt-2 tiny dim"><span>${UI.esc(first)}</span><span>${UI.esc(last)}</span></div>
      <div class="chart-legend mt-3">
        <span><i style="background:var(--st-new);opacity:.55"></i>Leads</span>
        <span><i style="background:var(--accent)"></i>Appointments booked</span>
      </div>`;
  }

  function sources(list) {
    if (!list.length) return '<p class="small muted">No leads yet.</p>';
    return `<div class="stack gap-4">${list.map((s) => `
      <div>
        <div class="between mb-2">
          <span class="small strong">${UI.esc(s.label)}</span>
          <span class="small muted tabular">${UI.num(s.leads)} leads &middot;
            <span class="accent-text strong">${UI.num(s.booked)} booked</span></span>
        </div>
        <div class="progress"><span style="width:${Math.min(100, s.booking_rate)}%"></span></div>
        <div class="tiny dim mt-1">${UI.pct(s.booking_rate)} of these became appointments</div>
      </div>`).join('')}</div>`;
  }

  function plainSummary(s) {
    if (!s.total_leads) {
      return 'No leads have come in for this period yet. Once they do, this page shows exactly how many turned into appointments.';
    }
    const parts = [
      `You received <strong>${UI.num(s.total_leads)}</strong> lead${s.total_leads === 1 ? '' : 's'}.`,
      `The assistant responded to <strong>${UI.num(s.contacted_leads)}</strong> of them`,
      s.avg_response_seconds !== null ? `in an average of <strong>${UI.duration(s.avg_response_seconds)}</strong>.` : '.',
      `<strong>${UI.num(s.qualified_leads)}</strong> qualified, and`,
      `<strong>${UI.num(s.appointments_booked)}</strong> appointment${s.appointments_booked === 1 ? ' was' : 's were'} booked`,
      `— that's a <strong>${UI.pct(s.conversion_rate)}</strong> conversion rate.`,
    ];
    return parts.join(' ');
  }

  function render(data) {
    const s = data.summary;
    sub.textContent = days ? `Last ${days} days` : 'All time';
    area.innerHTML = `
      <div class="stat-grid mb-5">
        <div class="stat stat-hero">
          <div class="stat-label">${UI.icon('calendar', 13)}Appointments booked</div>
          <div class="stat-value">${UI.num(s.appointments_booked)}</div>
          <div class="stat-sub">The number that matters most</div>
        </div>
        <div class="stat">
          <div class="stat-label">${UI.icon('inbox', 13)}Leads generated</div>
          <div class="stat-value">${UI.num(s.total_leads)}</div>
          <div class="stat-sub">${UI.num(s.new_leads)} not yet worked</div>
        </div>
        <div class="stat">
          <div class="stat-label">${UI.icon('chat', 13)}Response rate</div>
          <div class="stat-value">${UI.pct(s.response_rate)}</div>
          <div class="stat-sub">${UI.num(s.contacted_leads)} leads answered</div>
        </div>
        <div class="stat">
          <div class="stat-label">${UI.icon('target', 13)}Booking rate</div>
          <div class="stat-value">${UI.pct(s.booking_rate)}</div>
          <div class="stat-sub">Of qualified leads</div>
        </div>
        <div class="stat">
          <div class="stat-label">${UI.icon('user', 13)}Customers won</div>
          <div class="stat-value">${UI.num(s.customers_won)}</div>
          <div class="stat-sub">Appointments marked completed</div>
        </div>
        <div class="stat">
          <div class="stat-label">${UI.icon('card', 13)}Revenue booked</div>
          <div class="stat-value">${UI.money(s.booked_value, { compact: true })}</div>
          <div class="stat-sub">${UI.money(s.won_value, { compact: true })} from completed jobs</div>
        </div>
        <div class="stat">
          <div class="stat-label">${UI.icon('bolt', 13)}Avg. response time</div>
          <div class="stat-value">${UI.duration(s.avg_response_seconds)}</div>
          <div class="stat-sub">Lead arriving to first reply</div>
        </div>
      </div>

      <div class="banner banner-accent mb-5">
        <div>${UI.icon('chart', 18)}</div>
        <div>${plainSummary(s)}</div>
      </div>

      <div class="grid-2">
        <section class="card">
          <div class="card-title mb-2">Leads vs appointments</div>
          <p class="small muted mb-4">Every day in this range.</p>
          ${chart(data.timeseries)}
        </section>
        <section class="card">
          <div class="card-title mb-2">Where leads are lost</div>
          <p class="small muted mb-4">Each step of the journey.</p>
          ${funnel(s)}
        </section>
      </div>

      <section class="card mt-4">
        <div class="card-title mb-2">Which sources actually book</div>
        <p class="small muted mb-4">Spend more where the booking rate is highest.</p>
        ${sources(data.sources)}
      </section>

      <p class="tiny dim mt-4">Revenue figures use the average job value you set for each service in
        Automation &rarr; Services. They are estimates, not invoices.</p>`;
  }

  async function load() {
    try {
      render(await API.get(`/api/reports?days=${days}`));
    } catch (err) {
      UI.errorToast(err);
      area.innerHTML = `<div class="banner banner-danger">Could not load reports. ${UI.esc(err.message)}</div>`;
    }
  }

  rangeSelect.addEventListener('change', () => {
    days = Number(rangeSelect.value);
    localStorage.setItem('lil_range', String(days));
    load();
  });

  area.innerHTML = '<div class="card"><div class="skeleton" style="height:280px"></div></div>';
  await load();
})();
