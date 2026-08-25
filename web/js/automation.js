/** Automation Center — everything an owner can tune without code. */
(async function () {
  await Shell.init('automation', { title: 'Automation' });

  const TABS = [
    ['ai', 'Assistant'], ['questions', 'Questions'], ['services', 'Services'], ['areas', 'Areas'],
    ['hours', 'Hours'], ['booking', 'Booking'], ['followups', 'Follow-ups'], ['notifications', 'Alerts'],
  ];
  const panel = document.getElementById('panel');
  const tabsEl = document.getElementById('sectionTabs');
  let cfg = null;
  let active = location.hash.replace('#', '') || 'ai';
  if (!TABS.some(([k]) => k === active)) active = 'ai';

  function renderTabs() {
    tabsEl.innerHTML = TABS.map(([key, label]) =>
      `<button class="chip${key === active ? ' is-active' : ''}" data-tab="${key}" role="tab"
        aria-selected="${key === active}">${UI.esc(label)}</button>`).join('');
    tabsEl.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => {
      active = b.dataset.tab;
      location.hash = active;
      renderTabs();
      renderPanel();
    }));
  }

  function renderPanel() {
    panel.innerHTML = SettingsForms.renderSection(active, cfg);
    SettingsForms.wireSection(active, panel);
    if (active === 'booking') renderSlotPreview();
  }

  function renderSlotPreview() {
    const slots = cfg.sample_slots || [];
    panel.insertAdjacentHTML('beforeend', `
      <div class="card mt-4">
        <div class="card-title mb-2">What the assistant would offer right now</div>
        <p class="small muted mb-4">Computed from your availability with booked times removed. Save to refresh.</p>
        ${slots.length ? `<div class="chip-row">${slots.map((s) =>
          `<span class="pill pill-accent">${UI.esc(s.label)}</span>`).join('')}</div>`
          : '<p class="small muted">No open times — widen your availability or raise the daily job limit.</p>'}
      </div>`);
  }

  async function load() {
    cfg = await API.get('/api/settings');
    renderTabs();
    renderPanel();
  }

  document.getElementById('saveBtn').addEventListener('click', async (e) => {
    e.target.disabled = true;
    e.target.textContent = 'Saving…';
    try {
      const patch = SettingsForms.readSections([active], panel);
      cfg = await API.patch('/api/settings', patch);
      renderPanel();
      UI.toast('Saved', 'The assistant is using these settings from now on.');
    } catch (err) {
      UI.errorToast(err);
    } finally {
      e.target.disabled = false;
      e.target.textContent = 'Save changes';
    }
  });

  document.getElementById('resetBtn').addEventListener('click', async () => {
    await load();
    UI.toast('Changes discarded');
  });

  panel.innerHTML = '<div class="card"><div class="skeleton" style="height:320px"></div></div>';
  try { await load(); } catch (err) { UI.errorToast(err); }
})();
