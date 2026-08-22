/**
 * dashboard.js — business-owner view: lead list, stats, notifications.
 * Polls the backend so it reflects leads captured in any session/device,
 * plus follow-ups and email notifications the server runs in the background.
 */

(function () {
  const business = ALM.getBusiness();
  let filter = 'all';
  let selectedLeadId = null;
  let seenIds = new Set(JSON.parse(sessionStorage.getItem('alm_seen_ids') || '[]'));
  let unread = parseInt(sessionStorage.getItem('alm_unread') || '0', 10);
  let currentLeads = [];

  const el = (id) => document.getElementById(id);

  const STATUS_LABEL = {
    new: 'New', qualified: 'Qualified', booked: 'Booked',
    'needs-follow-up': 'Needs Follow-up', lost: 'Lost', 'out-of-area': 'Out of Area',
  };

  function fmtTime(ts) {
    const d = new Date(ts);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' · ' +
      d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }

  function relTime(ts) {
    const diff = Date.now() - ts;
    const s = Math.floor(diff / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function renderStats() {
    const s = ALM.stats(currentLeads);
    el('statTotal').textContent = s.total;
    el('statQualified').textContent = s.qualified;
    el('statBooked').textContent = s.booked;
    el('statFollowUp').textContent = s.needsFollowUp;
    el('statConversion').textContent = s.conversion + '%';
  }

  function renderBell() {
    el('bellCount').textContent = unread;
    el('bellCount').classList.toggle('hidden', unread === 0);
    sessionStorage.setItem('alm_unread', String(unread));
  }

  function badge(cls, text) {
    return `<span class="badge badge-${cls}">${text}</span>`;
  }

  function emailBadge(l) {
    if (!l.emailStatus) return '';
    const map = {
      sent: { icon: '📧', label: 'Owner emailed', cls: 'text-emerald-600' },
      simulated: { icon: '📧', label: 'Owner emailed (simulated)', cls: 'text-amber-600' },
      failed: { icon: '⚠️', label: 'Email failed', cls: 'text-red-600' },
    };
    const info = map[l.emailStatus];
    if (!info) return '';
    return `<div class="text-[11px] ${info.cls} mt-1">${info.icon} ${info.label}</div>`;
  }

  function renderTable() {
    const leads = currentLeads.filter((l) => filter === 'all' || l.status === filter);
    const tbody = el('leadsBody');
    if (leads.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center text-slate-400 py-14 text-sm">No leads in this view yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = leads.map((l) => `
      <tr class="border-b border-slate-100 hover:bg-slate-50 cursor-pointer transition" data-id="${l.id}">
        <td class="py-3 px-4">
          <div class="font-medium text-slate-900">${l.name || '—'}</div>
          <div class="text-xs text-slate-400">${l.phone || ''}</div>
        </td>
        <td class="py-3 px-4 text-slate-600 max-w-[180px] truncate">${l.address || '—'}</td>
        <td class="py-3 px-4 text-slate-600">${l.homeSize ? l.homeSize.toUpperCase() : '—'}</td>
        <td class="py-3 px-4 text-slate-600 capitalize">${(l.cleaningType || '—').replace('-', ' ')}</td>
        <td class="py-3 px-4 text-slate-600 capitalize">${(l.frequency || '—').replace('-', ' ')}</td>
        <td class="py-3 px-4">${l.quote ? '$' + l.quote : '—'}</td>
        <td class="py-3 px-4">${badge(l.status, STATUS_LABEL[l.status] || l.status)} ${l.score && l.score !== 'pending' ? badge(l.score, l.score) : ''}${emailBadge(l)}</td>
        <td class="py-3 px-4 text-slate-400 text-xs">${relTime(l.updatedAt)}</td>
      </tr>
    `).join('');

    tbody.querySelectorAll('tr[data-id]').forEach((row) => {
      row.addEventListener('click', () => openDetail(row.dataset.id));
    });
  }

  function renderFilters() {
    document.querySelectorAll('[data-filter]').forEach((btn) => {
      btn.classList.toggle('bg-teal-600', btn.dataset.filter === filter);
      btn.classList.toggle('text-white', btn.dataset.filter === filter);
      btn.classList.toggle('text-slate-600', btn.dataset.filter !== filter);
      btn.classList.toggle('bg-white', btn.dataset.filter !== filter);
    });
  }

  function openDetail(id) {
    selectedLeadId = id;
    const l = currentLeads.find((x) => x.id === id);
    if (!l) return;
    el('detailOverlay').classList.remove('hidden');
    el('detailName').textContent = l.name || 'Unnamed lead';
    el('detailMeta').innerHTML = `${badge(l.status, STATUS_LABEL[l.status] || l.status)} ${l.score && l.score !== 'pending' ? badge(l.score, l.score) : ''}`;
    el('detailInfo').innerHTML = `
      <div><span class="text-slate-400">Phone</span><div class="font-medium">${l.phone || '—'}</div></div>
      <div><span class="text-slate-400">Address</span><div class="font-medium">${l.address || '—'}</div></div>
      <div><span class="text-slate-400">Home Size</span><div class="font-medium">${(l.homeSize || '—').toUpperCase()}</div></div>
      <div><span class="text-slate-400">Cleaning Type</span><div class="font-medium capitalize">${(l.cleaningType || '—').replace('-', ' ')}</div></div>
      <div><span class="text-slate-400">Frequency</span><div class="font-medium capitalize">${(l.frequency || '—').replace('-', ' ')}</div></div>
      <div><span class="text-slate-400">Preferred Date</span><div class="font-medium">${l.preferredDate || '—'}</div></div>
      <div><span class="text-slate-400">Quote</span><div class="font-medium">${l.quote ? '$' + l.quote : '—'}</div></div>
      <div><span class="text-slate-400">Booked Slot</span><div class="font-medium">${l.bookedSlot || '—'}</div></div>
      <div><span class="text-slate-400">SMS/Email Consent</span><div class="font-medium">${l.phoneConsent ? 'Given ✓' : '—'}</div></div>
      <div><span class="text-slate-400">Owner Notification</span><div class="font-medium">${l.emailStatus ? l.emailStatus : '—'}</div></div>
    `;
    el('detailTranscript').innerHTML = l.transcript.map((t) => `
      <div class="flex ${t.from === 'lead' ? 'justify-end' : 'justify-start'} mb-2">
        <div class="max-w-[85%] rounded-xl px-3 py-2 text-xs ${
          t.from === 'lead' ? 'bg-teal-600 text-white' : t.from === 'system' ? 'bg-amber-50 text-amber-800 border border-amber-200' : 'bg-slate-100 text-slate-700'
        }">
          ${t.from === 'system' ? '<div class="font-semibold mb-0.5">⚙️ Automation</div>' : ''}
          ${t.text}
          <div class="text-[10px] opacity-60 mt-1">${fmtTime(t.ts)}</div>
        </div>
      </div>
    `).join('') || '<p class="text-xs text-slate-400">No conversation yet.</p>';

    const followBtn = el('sendFollowUpBtn');
    followBtn.classList.toggle('hidden', l.status === 'booked' || l.status === 'out-of-area');
  }

  el('closeDetail').addEventListener('click', () => el('detailOverlay').classList.add('hidden'));

  el('sendFollowUpBtn').addEventListener('click', async () => {
    if (!selectedLeadId) return;
    await ALM.sendManualFollowUp(selectedLeadId);
    await refreshAll();
    openDetail(selectedLeadId);
  });

  document.querySelectorAll('[data-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      filter = btn.dataset.filter;
      renderFilters();
      renderTable();
    });
  });

  function showToast(lead) {
    const toast = document.createElement('div');
    toast.className = 'toast-in bg-white border border-slate-200 rounded-xl shadow-lg px-4 py-3.5 flex items-start gap-3 w-80';
    toast.innerHTML = `
      <div class="w-9 h-9 rounded-full bg-teal-100 flex items-center justify-center shrink-0 text-lg">🔔</div>
      <div class="min-w-0">
        <div class="font-semibold text-sm text-slate-900">New qualified lead</div>
        <div class="text-xs text-slate-500 mt-0.5 truncate">${lead.name} · ${(lead.cleaningType || '').replace('-', ' ')} · ${lead.homeSize?.toUpperCase() || ''}</div>
      </div>
    `;
    el('toastStack').appendChild(toast);
    setTimeout(() => toast.remove(), 6000);

    if (window.Notification && Notification.permission === 'granted') {
      new Notification(`New qualified lead — ${business.name}`, {
        body: `${lead.name} wants a ${lead.cleaningType} clean (${lead.homeSize}). Est. $${lead.quote}.`,
      });
    }
  }

  function checkForNewQualified() {
    currentLeads.forEach((l) => {
      const isNotifiable = ['qualified', 'booked', 'needs-follow-up'].includes(l.status);
      if (isNotifiable && !seenIds.has(l.id)) {
        seenIds.add(l.id);
        unread += 1;
        showToast(l);
      }
    });
    sessionStorage.setItem('alm_seen_ids', JSON.stringify([...seenIds]));
    renderBell();
  }

  async function refreshAll() {
    try {
      currentLeads = await ALM.listLeads();
    } catch (e) {
      console.error('Failed to load leads from server', e);
      return;
    }
    renderStats();
    renderTable();
    renderFilters();
    checkForNewQualified();
    if (selectedLeadId && !el('detailOverlay').classList.contains('hidden')) openDetail(selectedLeadId);
  }

  el('bellBtn').addEventListener('click', () => {
    unread = 0;
    renderBell();
  });

  el('notifyPermBtn')?.addEventListener('click', () => {
    if (window.Notification) Notification.requestPermission();
  });

  refreshAll();
  setInterval(refreshAll, 2500);
})();
