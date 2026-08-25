/**
 * Agency console shell. Separate from the client shell because the navigation,
 * the data and the permissions are different — an agency admin manages
 * accounts; a client owner works leads.
 */
const AdminShell = (() => {
  let session = null;

  const NAV = [
    { key: 'clients', href: '/admin/', label: 'Clients', icon: 'building', tab: true },
    { key: 'plans', href: '/admin/#plans', label: 'Plans', icon: 'card', tab: true },
    { key: 'health', href: '/admin/#health', label: 'Health', icon: 'shield', tab: true },
    { key: 'app', href: '/app/', label: 'Client view', icon: 'home', tab: true },
  ];

  async function init(active = 'clients') {
    try {
      const data = await API.me();
      session = data.user;
    } catch (err) {
      location.href = '/login.html?next=' + encodeURIComponent(location.pathname);
      throw err;
    }
    if (!session.is_agency) {
      location.href = '/app/';
      throw new Error('not an agency admin');
    }
    document.body.classList.add('app');
    document.body.insertAdjacentHTML('afterbegin', `
      <aside class="sidebar">
        <a class="sidebar-brand brand" href="/admin/">
          <span class="brand-mark">${UI.icon('bolt', 16)}</span>
          <span class="brand-name">Lockedin<span>Leads</span></span>
        </a>
        <div class="tiny dim" style="padding:0 11px 12px">Agency console</div>
        <nav class="stack gap-1">
          ${NAV.map((n) => `<a class="nav-item${n.key === active ? ' is-active' : ''}"
            href="${n.href}">${UI.icon(n.icon)}<span>${UI.esc(n.label)}</span></a>`).join('')}
        </nav>
        <div class="sidebar-foot stack gap-1">
          <button class="nav-item" id="themeBtnDesk">${UI.icon('moon')}<span>Theme</span></button>
          <button class="nav-item" id="logoutBtnDesk">${UI.icon('logout')}<span>Sign out</span></button>
          <div class="tiny dim" style="padding:8px 11px 0">${UI.esc(session.email)}</div>
        </div>
      </aside>
      <header class="topbar">
        <div class="brand mobile-only"><span class="brand-mark">${UI.icon('bolt', 16)}</span></div>
        <div class="grow"><div class="topbar-title">Agency console</div></div>
        <button class="icon-btn" id="themeBtn" aria-label="Toggle theme">${UI.icon('sun')}</button>
        <button class="icon-btn" id="logoutBtn" aria-label="Sign out">${UI.icon('logout')}</button>
      </header>
      <nav class="tabbar">
        ${NAV.map((n) => `<a class="tab${n.key === active ? ' is-active' : ''}" href="${n.href}">
          ${UI.icon(n.icon, 21)}<span>${UI.esc(n.label)}</span></a>`).join('')}
      </nav>`);

    const swap = () => {
      const mode = UI.toggleTheme();
      const btn = document.getElementById('themeBtn');
      if (btn) btn.innerHTML = mode === 'light' ? UI.icon('moon') : UI.icon('sun');
    };
    document.getElementById('themeBtn').addEventListener('click', swap);
    document.getElementById('themeBtnDesk').addEventListener('click', swap);
    const out = async () => { await API.logout(); location.href = '/login.html'; };
    document.getElementById('logoutBtn').addEventListener('click', out);
    document.getElementById('logoutBtnDesk').addEventListener('click', out);
    return session;
  }

  /** Open a client's own dashboard as that client. */
  async function viewAs(tenantId) {
    try {
      await API.post('/api/admin/impersonate', { tenant_id: tenantId });
      location.href = '/app/';
    } catch (err) { UI.errorToast(err); }
  }

  return { init, viewAs, get session() { return session; } };
})();
