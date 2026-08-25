/**
 * App shell: auth guard, navigation (sidebar on desktop, tab bar on mobile),
 * notification bell and the agency "viewing as client" banner.
 */
const Shell = (() => {
  let session = null;

  const NAV = [
    { key: 'dashboard', href: '/app/', label: 'Home', icon: 'home', tab: true },
    { key: 'leads', href: '/app/leads.html', label: 'Leads', icon: 'users', tab: true },
    { key: 'appointments', href: '/app/appointments.html', label: 'Calendar', icon: 'calendar', tab: true },
    { key: 'reports', href: '/app/reports.html', label: 'Reports', icon: 'chart', tab: true },
    { key: 'automation', href: '/app/automation.html', label: 'Automation', icon: 'settings', tab: true },
    { key: 'connect', href: '/app/connect.html', label: 'Lead sources', icon: 'link' },
    { key: 'billing', href: '/app/billing.html', label: 'Billing', icon: 'card' },
  ];

  async function init(activeKey, { title, subtitle } = {}) {
    try {
      const data = await API.me();
      session = data.user;
    } catch (err) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.href = `/login.html?next=${next}`;
      throw err;
    }

    if (session.is_agency && !session.tenant) {
      location.href = '/admin/';
      throw new Error('redirecting to agency console');
    }

    document.body.classList.add('app');
    renderChrome(activeKey, title, subtitle);
    refreshNotifications();
    setInterval(refreshNotifications, 45000);

    // Nudge unfinished setup — an unconfigured account cannot convert leads.
    const t = session.tenant;
    if (t && !t.onboarded_at && !location.pathname.includes('onboarding')) {
      showSetupBanner(t);
    }
    return session;
  }

  function renderChrome(activeKey, title, subtitle) {
    const t = session.tenant || {};
    document.body.insertAdjacentHTML('afterbegin', `
      <aside class="sidebar">
        <a class="sidebar-brand brand" href="/app/">
          <span class="brand-mark">${UI.icon('bolt', 16)}</span>
          <span class="brand-name">Lockedin<span>Leads</span></span>
        </a>
        <nav class="stack gap-1">
          ${NAV.map((item) => navItem(item, activeKey)).join('')}
        </nav>
        <div class="sidebar-foot stack gap-1">
          ${session.impersonating ? `<button class="nav-item" id="exitImpersonate">${UI.icon('back')}<span>Back to agency</span></button>` : ''}
          <button class="nav-item" id="themeBtnDesk">${UI.icon('moon')}<span>Theme</span></button>
          <button class="nav-item" id="logoutBtnDesk">${UI.icon('logout')}<span>Sign out</span></button>
          <div class="tiny dim" style="padding:8px 11px 0">${UI.esc(t.name || '')}</div>
        </div>
      </aside>

      <header class="topbar">
        <div class="brand mobile-only">
          <span class="brand-mark">${UI.icon('bolt', 16)}</span>
        </div>
        <div class="grow" style="min-width:0">
          <div class="topbar-title truncate">${UI.esc(title || t.name || 'Dashboard')}</div>
          ${subtitle ? `<div class="topbar-sub truncate">${UI.esc(subtitle)}</div>` : ''}
        </div>
        <button class="icon-btn" id="themeBtn" aria-label="Toggle theme">${UI.icon('sun')}</button>
        <button class="icon-btn" id="bellBtn" aria-label="Notifications">
          ${UI.icon('bell')}<span class="icon-badge hidden" id="bellCount">0</span>
        </button>
        <button class="icon-btn mobile-only" id="menuBtn" aria-label="Menu">${UI.icon('user')}</button>
      </header>

      <nav class="tabbar" aria-label="Main">
        ${NAV.filter((n) => n.tab).map((item) => tabItem(item, activeKey)).join('')}
      </nav>
    `);

    if (session.impersonating) {
      document.querySelector('.topbar').insertAdjacentHTML('afterend', `
        <div class="banner banner-warn" style="border-radius:0;border-left:0;border-right:0;border-top:0">
          <div class="grow"><strong>Viewing ${UI.esc(t.name)}</strong> as agency admin — changes affect this client's live account.</div>
          <button class="btn btn-sm btn-ghost" id="exitImpersonateTop">Exit</button>
        </div>`);
    }

    document.getElementById('themeBtn')?.addEventListener('click', swapTheme);
    document.getElementById('themeBtnDesk')?.addEventListener('click', swapTheme);
    document.getElementById('logoutBtnDesk')?.addEventListener('click', signOut);
    document.getElementById('bellBtn')?.addEventListener('click', openNotifications);
    document.getElementById('menuBtn')?.addEventListener('click', openMenu);
    ['exitImpersonate', 'exitImpersonateTop'].forEach((id) =>
      document.getElementById(id)?.addEventListener('click', exitImpersonation));
  }

  function navItem(item, activeKey) {
    return `<a class="nav-item${item.key === activeKey ? ' is-active' : ''}" href="${item.href}">
      ${UI.icon(item.icon)}<span>${UI.esc(item.label)}</span></a>`;
  }

  function tabItem(item, activeKey) {
    return `<a class="tab${item.key === activeKey ? ' is-active' : ''}" href="${item.href}">
      ${UI.icon(item.icon, 21)}<span>${UI.esc(item.label)}</span></a>`;
  }

  function swapTheme() {
    const mode = UI.toggleTheme();
    const svg = mode === 'light' ? UI.icon('moon') : UI.icon('sun');
    const btn = document.getElementById('themeBtn');
    if (btn) btn.innerHTML = svg;
  }

  async function signOut() {
    await API.logout();
    location.href = '/login.html';
  }

  async function exitImpersonation() {
    try {
      await API.post('/api/admin/impersonate', { tenant_id: null });
      location.href = '/admin/';
    } catch (err) { UI.errorToast(err); }
  }

  function openMenu() {
    const t = session.tenant || {};
    UI.modal({
      title: 'Account',
      body: `
        <div class="stack gap-3">
          <div class="card card-pad-sm">
            <div class="label">Signed in as</div>
            <div class="strong mt-1">${UI.esc(session.name || session.email)}</div>
            <div class="small muted">${UI.esc(session.email)}</div>
            <div class="small muted mt-2">${UI.esc(t.name || '')}</div>
          </div>
          ${NAV.filter((n) => !n.tab).map((n) =>
            `<a class="nav-item" href="${n.href}">${UI.icon(n.icon)}<span>${UI.esc(n.label)}</span></a>`).join('')}
          <a class="nav-item" href="/app/onboarding.html">${UI.icon('bolt')}<span>Setup wizard</span></a>
          ${session.is_agency ? `<a class="nav-item" href="/admin/">${UI.icon('building')}<span>Agency console</span></a>` : ''}
          <button class="nav-item" data-signout>${UI.icon('logout')}<span>Sign out</span></button>
        </div>`,
      onOpen(el, close) {
        el.querySelector('[data-signout]').addEventListener('click', signOut);
      },
    });
  }

  async function refreshNotifications() {
    try {
      const { notifications } = await API.get('/api/notifications');
      const unread = notifications.filter((n) => !n.read_at).length;
      const badge = document.getElementById('bellCount');
      if (badge) {
        badge.textContent = unread > 9 ? '9+' : String(unread);
        badge.classList.toggle('hidden', unread === 0);
      }
      Shell.notifications = notifications;
    } catch (err) { /* transient — the bell simply doesn't update */ }
  }

  function openNotifications() {
    const items = Shell.notifications || [];
    const body = items.length ? `<div class="stack gap-2">${items.map((n) => `
      <div class="card card-pad-sm${n.read_at ? '' : ' card-hover'}" style="${n.read_at ? 'opacity:.65' : ''}">
        <div class="between">
          <span class="badge badge-plain badge-${n.type === 'booked' ? 'accent' : n.type === 'handoff' ? 'warm' : 'info'}">${UI.esc(n.type.replace('_', ' '))}</span>
          <span class="tiny dim">${UI.relTime(n.created_at)}</span>
        </div>
        <div class="strong small mt-2">${UI.esc(n.title)}</div>
        ${n.body ? `<div class="tiny muted mt-1" style="white-space:pre-wrap">${UI.esc(n.body.slice(0, 240))}</div>` : ''}
        ${n.lead_id ? `<a class="btn btn-sm btn-ghost mt-3" href="/app/leads.html?lead=${encodeURIComponent(n.lead_id)}">Open lead</a>` : ''}
      </div>`).join('')}</div>`
      : `<div class="empty"><div class="empty-icon">${UI.icon('bell')}</div>
         <div class="empty-title">No notifications yet</div>
         <div class="small">New leads, qualifications and bookings show up here.</div></div>`;

    UI.modal({
      title: 'Notifications',
      body,
      footer: items.length ? `<button class="btn btn-ghost grow" data-close>Close</button>
        <button class="btn btn-primary grow" data-read>Mark all read</button>` : '',
      onOpen(el, close) {
        el.querySelector('[data-read]')?.addEventListener('click', async () => {
          try {
            await API.post('/api/notifications/read');
            await refreshNotifications();
            close();
          } catch (err) { UI.errorToast(err); }
        });
      },
    });
  }

  function showSetupBanner(tenant) {
    const main = document.querySelector('.app-main');
    if (!main) return;
    main.insertAdjacentHTML('afterbegin', `
      <div class="banner banner-accent mb-4">
        <div class="grow">
          <strong>Finish setting up ${UI.esc(tenant.name)}</strong>
          <div class="small muted mt-1">Add your services, areas and booking availability so the assistant can qualify and book properly.</div>
        </div>
        <a class="btn btn-sm btn-primary" href="/app/onboarding.html">Continue setup</a>
      </div>`);
  }

  function setCount(key, count) {
    const href = NAV.find((n) => n.key === key)?.href;
    if (!href) return;
    document.querySelectorAll(`.nav-item[href="${href}"], .tab[href="${href}"]`).forEach((el) => {
      let badge = el.querySelector('.nav-count, .tab-count');
      if (!count) { badge?.remove(); return; }
      if (!badge) {
        badge = document.createElement('span');
        badge.className = el.classList.contains('tab') ? 'tab-count' : 'nav-count';
        el.appendChild(badge);
      }
      badge.textContent = count > 99 ? '99+' : String(count);
    });
  }

  return { init, refreshNotifications, setCount, get session() { return session; } };
})();
