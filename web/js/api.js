/**
 * API client.
 *
 * Sends the session's CSRF token on every state-changing request and funnels
 * every error into one place, so pages only deal with data.
 */
const API = (() => {
  let csrfToken = null;

  function setCsrf(token) {
    csrfToken = token || null;
    if (token) sessionStorage.setItem('lil_csrf', token);
  }

  function getCsrf() {
    return csrfToken || sessionStorage.getItem('lil_csrf');
  }

  class ApiError extends Error {
    constructor(message, status, code, extra) {
      super(message);
      this.status = status;
      this.code = code;
      Object.assign(this, extra || {});
    }
  }

  async function request(path, { method = 'GET', body, redirectOn401 = true } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const token = getCsrf();
    if (token && method !== 'GET') headers['X-CSRF-Token'] = token;

    let response;
    try {
      response = await fetch(path, {
        method,
        headers,
        credentials: 'same-origin',
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      throw new ApiError('Network problem — check your connection and try again.', 0, 'network');
    }

    if (response.status === 401 && redirectOn401 && !path.startsWith('/api/auth/')) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.href = `/login.html?next=${next}`;
      throw new ApiError('Signed out', 401, 'unauthenticated');
    }
    if (response.status === 204) return null;

    let data = null;
    try {
      data = await response.json();
    } catch (err) {
      if (!response.ok) throw new ApiError('Unexpected server response.', response.status);
      return null;
    }
    if (!response.ok) {
      const { error, code, ...extra } = data || {};
      throw new ApiError(error || 'Something went wrong.', response.status, code, extra);
    }
    return data;
  }

  return {
    ApiError,
    setCsrf,
    get: (p) => request(p),
    post: (p, body) => request(p, { method: 'POST', body: body || {} }),
    patch: (p, body) => request(p, { method: 'PATCH', body: body || {} }),
    del: (p) => request(p, { method: 'DELETE' }),
    raw: request,

    async me() {
      const data = await request('/api/auth/me', { redirectOn401: false });
      if (data?.csrf_token) setCsrf(data.csrf_token);
      return data;
    },
    async login(email, password) {
      const data = await request('/api/auth/login', {
        method: 'POST', body: { email, password }, redirectOn401: false,
      });
      setCsrf(data.csrf_token);
      return data;
    },
    async logout() {
      try { await request('/api/auth/logout', { method: 'POST' }); } catch (e) { /* already gone */ }
      sessionStorage.removeItem('lil_csrf');
    },
  };
})();
