/**
 * UI helpers: escaping, formatting, toasts, modals, icons.
 * Every value that reaches the DOM goes through esc() or textContent — lead
 * names and messages are attacker-controlled text.
 */
const UI = (() => {
  const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function esc(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/[&<>"']/g, (c) => ESCAPES[c]);
  }

  function money(value, { cents = false, compact = false } = {}) {
    const n = Number(value || 0) / (cents ? 100 : 1);
    if (compact && Math.abs(n) >= 10000) {
      return '$' + (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1) + 'k';
    }
    return n.toLocaleString(undefined, {
      style: 'currency', currency: 'USD',
      minimumFractionDigits: n % 1 === 0 ? 0 : 2, maximumFractionDigits: 2,
    });
  }

  function num(value) {
    return Number(value || 0).toLocaleString();
  }

  function pct(value) {
    return `${Number(value || 0).toFixed(Number(value) % 1 === 0 ? 0 : 1)}%`;
  }

  function relTime(ms) {
    if (!ms) return '—';
    const diff = Date.now() - Number(ms);
    const future = diff < 0;
    const s = Math.floor(Math.abs(diff) / 1000);
    let out;
    if (s < 45) out = 'just now';
    else if (s < 3600) out = `${Math.floor(s / 60)}m`;
    else if (s < 86400) out = `${Math.floor(s / 3600)}h`;
    else if (s < 2592000) out = `${Math.floor(s / 86400)}d`;
    else out = new Date(Number(ms)).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    if (out === 'just now') return out;
    return future ? `in ${out}` : `${out} ago`;
  }

  function dateTime(ms) {
    if (!ms) return '—';
    return new Date(Number(ms)).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  }

  function timeOnly(ms) {
    if (!ms) return '';
    return new Date(Number(ms)).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }

  function duration(seconds) {
    if (seconds === null || seconds === undefined) return '—';
    const s = Number(seconds);
    if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
    if (s < 3600) return `${Math.round(s / 60)}m`;
    return `${(s / 3600).toFixed(1)}h`;
  }

  function initials(name) {
    return (name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0] || '').join('').toUpperCase() || '?';
  }

  const STATUS_LABEL = {
    NEW: 'New', CONTACTED: 'Contacted', QUALIFIED: 'Qualified', BOOKED: 'Booked',
    NO_RESPONSE: 'No response', LOST: 'Lost', CUSTOMER: 'Customer',
  };
  const STATUSES = Object.keys(STATUS_LABEL);

  function statusBadge(status) {
    return `<span class="badge badge-${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>`;
  }

  function scoreBadge(score) {
    if (!score || score === 'unscored') return '';
    return `<span class="badge badge-plain badge-${esc(score)}">${esc(score)}</span>`;
  }

  // ---------------------------------------------------------------- toasts
  function toastStack() {
    let el = document.querySelector('.toast-stack');
    if (!el) {
      el = document.createElement('div');
      el.className = 'toast-stack';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }
    return el;
  }

  function toast(title, body = '', kind = '') {
    const el = document.createElement('div');
    el.className = `toast${kind ? ' toast-' + kind : ''}`;
    el.innerHTML = `<div class="grow"><div class="toast-title">${esc(title)}</div>${
      body ? `<div class="toast-body">${esc(body)}</div>` : ''}</div>`;
    toastStack().appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity .2s, transform .2s';
      el.style.opacity = '0';
      el.style.transform = 'translateY(6px)';
      setTimeout(() => el.remove(), 220);
    }, kind === 'error' ? 6000 : 4000);
    return el;
  }

  function errorToast(err) {
    console.error(err);
    toast(err?.message || 'Something went wrong.', '', 'error');
  }

  // ---------------------------------------------------------------- modal
  function modal({ title, body, footer, size = '', onOpen, onClose }) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal ${size}" role="dialog" aria-modal="true" aria-label="${esc(title || 'Dialog')}">
        <div class="modal-grab"></div>
        <div class="modal-head">
          <div class="grow"><div class="card-title">${esc(title || '')}</div></div>
          <button class="icon-btn" data-close aria-label="Close">${icon('x')}</button>
        </div>
        <div class="modal-body">${body || ''}</div>
        ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
      </div>`;
    const close = () => {
      backdrop.remove();
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKey);
      if (onClose) onClose();
    };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', close));
    document.addEventListener('keydown', onKey);
    document.body.appendChild(backdrop);
    document.body.style.overflow = 'hidden';
    const first = backdrop.querySelector('input, textarea, select, button:not([data-close])');
    if (first) setTimeout(() => first.focus(), 60);
    if (onOpen) onOpen(backdrop, close);
    return { el: backdrop, close };
  }

  function confirmDialog(title, message, confirmLabel = 'Confirm') {
    return new Promise((resolve) => {
      const m = modal({
        title,
        body: `<p class="muted" style="font-size:14.5px">${esc(message)}</p>`,
        footer: `<button class="btn btn-ghost grow" data-close>Cancel</button>
                 <button class="btn btn-primary grow" data-ok>${esc(confirmLabel)}</button>`,
        onOpen(el, close) {
          el.querySelector('[data-ok]').addEventListener('click', () => { close(); resolve(true); });
        },
        onClose() { resolve(false); },
      });
      return m;
    });
  }

  async function copy(text, label = 'Copied to clipboard') {
    try {
      await navigator.clipboard.writeText(text);
      toast(label);
    } catch (e) {
      // Clipboard API needs a secure context; fall back so http://localhost works.
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); toast(label); } catch (_) { toast('Copy failed', '', 'error'); }
      ta.remove();
    }
  }

  // ----------------------------------------------------------------- icons
  const ICONS = {
    home: 'M3 10.5 12 3l9 7.5M5 9.6V20a1 1 0 0 0 1 1h3.5v-6h5v6H18a1 1 0 0 0 1-1V9.6',
    users: 'M16 20v-1.8a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4V20M9 10.2a3.6 3.6 0 1 0 0-7.2 3.6 3.6 0 0 0 0 7.2M22 20v-1.8a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
    chat: 'M21 11.5a8.4 8.4 0 0 1-9 8.4 8.9 8.9 0 0 1-3.9-.9L3 20.5l1.5-4.6A8.4 8.4 0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4z',
    calendar: 'M8 2v3M16 2v3M3.5 9h17M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z',
    chart: 'M3 3v17a1 1 0 0 0 1 1h17M7.5 15.5l4-4.5 3 3 5-6.5',
    settings: 'M12 15.4a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z',
    bell: 'M18 8A6 6 0 1 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0',
    plus: 'M12 5v14M5 12h14',
    x: 'M18 6 6 18M6 6l12 12',
    search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35',
    back: 'M19 12H5M12 19l-7-7 7-7',
    chevron: 'M9 18l6-6-6-6',
    check: 'M20 6 9 17l-5-5',
    bolt: 'M13 2 3 14h8l-1 8 10-12h-8l1-8z',
    phone: 'M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.4-1.2a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z',
    mail: 'M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM22 7l-10 6L2 7',
    building: 'M3 21h18M5 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16M15 21V9h4a2 2 0 0 1 2 2v10M9 7h2M9 11h2M9 15h2',
    shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
    link: 'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7',
    card: 'M3 6h18a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1zM2 10h20',
    logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
    sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
    moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
    send: 'M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z',
    robot: 'M12 2v3M5 8h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2zM9 13v2M15 13v2',
    user: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
    clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
    trash: 'M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6',
    copy: 'M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1zM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1',
    target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
    inbox: 'M22 12h-6l-2 3h-4l-2-3H2M5.5 5h13a2 2 0 0 1 1.8 1.1l3.2 5.9V18a2 2 0 0 1-2 2H2.5a2 2 0 0 1-2-2v-6l3.2-5.9A2 2 0 0 1 5.5 5z',
  };

  function icon(name, size = 20) {
    const path = ICONS[name] || ICONS.chevron;
    return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
  }

  // ----------------------------------------------------------------- theme
  function initTheme() {
    const saved = localStorage.getItem('lil_theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
  }

  function toggleTheme() {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('lil_theme', next);
    return next;
  }

  function debounce(fn, wait = 280) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
  }

  function formValues(root) {
    const out = {};
    root.querySelectorAll('[name]').forEach((el) => {
      if (el.type === 'checkbox') out[el.name] = el.checked;
      else if (el.type === 'radio') { if (el.checked) out[el.name] = el.value; }
      else out[el.name] = el.value;
    });
    return out;
  }

  return {
    esc, money, num, pct, relTime, dateTime, timeOnly, duration, initials,
    statusBadge, scoreBadge, STATUS_LABEL, STATUSES,
    toast, errorToast, modal, confirmDialog, copy, icon, initTheme, toggleTheme,
    debounce, formValues,
  };
})();
UI.initTheme();
