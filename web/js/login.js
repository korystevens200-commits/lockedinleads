(function () {
  const form = document.getElementById('loginForm');
  const errorEl = document.getElementById('loginError');
  const submit = document.getElementById('submitBtn');

  function nextUrl(user) {
    const params = new URLSearchParams(location.search);
    const next = params.get('next');
    // Only same-origin relative paths — never bounce a session to another host.
    if (next && next.startsWith('/') && !next.startsWith('//')) return next;
    return user.is_agency && !user.tenant ? '/admin/' : '/app/';
  }

  // Already signed in? Skip the form.
  API.me().then((data) => { if (data?.user) location.replace(nextUrl(data.user)); })
    .catch(() => {});

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    errorEl.classList.add('hidden');
    const email = form.email.value.trim();
    const password = form.password.value;
    if (!email || !password) {
      errorEl.textContent = 'Enter your email and password.';
      errorEl.classList.remove('hidden');
      return;
    }
    submit.disabled = true;
    submit.textContent = 'Signing in…';
    try {
      const data = await API.login(email, password);
      location.href = nextUrl(data.user);
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.remove('hidden');
      submit.disabled = false;
      submit.textContent = 'Sign in';
      form.password.select();
    }
  });
})();
