/**
 * Lead sources: API keys, webhook URL, website form endpoint and chat widget.
 * A key is shown exactly once — only its hash is stored server-side.
 */
(async function () {
  await Shell.init('connect', { title: 'Lead sources' });
  const area = document.getElementById('connectArea');

  function copyField(label, value, hint) {
    const id = 'c' + Math.random().toString(36).slice(2, 8);
    return `<div class="field">
      <label for="${id}">${UI.esc(label)}</label>
      <div class="copy-row">
        <input class="input grow" id="${id}" value="${UI.esc(value)}" readonly />
        <button class="btn btn-ghost btn-icon" data-copy="${UI.esc(value)}"
          aria-label="Copy ${UI.esc(label)}">${UI.icon('copy')}</button>
      </div>
      ${hint ? `<div class="field-hint">${hint}</div>` : ''}
    </div>`;
  }

  function render(data) {
    const curl = `curl -X POST ${data.webhook_url} \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Jenna Ortiz",
    "phone": "(305) 555-0142",
    "email": "jenna@example.com",
    "service": "Deep Clean",
    "city": "Coral Gables",
    "message": "Looking for a quote this week"
  }'`;

    area.innerHTML = `
      <div class="banner banner-accent mb-4">
        <div>${UI.icon('bolt', 18)}</div>
        <div><strong>Any of these fires the assistant instantly.</strong> A lead that arrives at 11pm
          gets a reply at 11pm.</div>
      </div>

      <div class="grid-2">
        <section class="card">
          <div class="card-title mb-2">Website form &amp; chat</div>
          <p class="small muted mb-4">No API key needed — these are tied to your account's public address.</p>
          ${copyField('Form POST endpoint', data.form_url,
            'Point your existing website form here. Standard field names (name, phone, email, message) are detected automatically.')}
          ${copyField('Chat widget link', data.chat_url,
            'Share it directly, or link it from a "Get a quote" button.')}
          <a class="btn btn-ghost btn-sm" href="${UI.esc(data.chat_url)}" target="_blank" rel="noopener">
            Open the chat widget</a>
        </section>

        <section class="card">
          <div class="card-title mb-2">API keys</div>
          <p class="small muted mb-4">For Zapier, Facebook / Google lead ads, or your CRM. A key is shown
            once when created — store it somewhere safe.</p>
          <div id="keyList" class="stack gap-2 mb-4">${
            data.keys.length ? data.keys.map((k) => `
              <div class="between card card-pad-sm">
                <div style="min-width:0">
                  <div class="small strong truncate">${UI.esc(k.label)}</div>
                  <div class="tiny dim mono">${UI.esc(k.key_prefix)}…
                    ${k.revoked_at ? '· revoked' : k.last_used_at ? '· used ' + UI.relTime(k.last_used_at) : '· never used'}</div>
                </div>
                ${k.revoked_at ? '' : `<button class="btn btn-sm btn-quiet" data-revoke="${UI.esc(k.id)}">Revoke</button>`}
              </div>`).join('')
            : '<p class="small muted">No API keys yet.</p>'}</div>
          <button class="btn btn-primary btn-sm" id="newKeyBtn">Create API key</button>
        </section>
      </div>

      <section class="card mt-4">
        <div class="card-title mb-2">Webhook endpoint</div>
        <p class="small muted mb-4">Send a POST with your API key. Facebook, Google Ads, Typeform, JotForm,
          WPForms and Zapier payload shapes are all understood — the fields are mapped for you.</p>
        ${copyField('Webhook URL', data.webhook_url)}
        <div class="label mb-2">Example</div>
        <div class="code-block">${UI.esc(curl)}</div>
      </section>

      <section class="card mt-4">
        <div class="card-title mb-2">Recent deliveries</div>
        ${data.recent_events.length ? `<div class="stack gap-2">${data.recent_events.map((e) => `
          <div class="between card card-pad-sm">
            <div style="min-width:0">
              <div class="small">
                <span class="badge badge-plain badge-${e.status === 'accepted' ? 'accent' : 'hot'}">${UI.esc(e.status)}</span>
                <span class="muted">${UI.esc(e.source)}</span>
              </div>
              ${e.reason ? `<div class="tiny dim mt-1">${UI.esc(e.reason)}</div>` : ''}
            </div>
            <span class="tiny dim nowrap">${UI.relTime(e.created_at)}</span>
          </div>`).join('')}</div>`
          : '<p class="small muted">Nothing received yet. Send a test request and it will show up here.</p>'}
      </section>`;

    area.querySelectorAll('[data-copy]').forEach((b) =>
      b.addEventListener('click', () => UI.copy(b.dataset.copy)));
    area.querySelectorAll('[data-revoke]').forEach((b) => b.addEventListener('click', async () => {
      if (!(await UI.confirmDialog('Revoke this key?',
        'Anything using it stops being able to send leads immediately.', 'Revoke'))) return;
      try {
        await API.del(`/api/api-keys/${encodeURIComponent(b.dataset.revoke)}`);
        UI.toast('Key revoked');
        load();
      } catch (err) { UI.errorToast(err); }
    }));
    document.getElementById('newKeyBtn').addEventListener('click', createKey);
  }

  function createKey() {
    UI.modal({
      title: 'Create an API key',
      body: `<div class="field"><label for="keyLabel">What is it for?</label>
        <input class="input" id="keyLabel" placeholder="Zapier, Facebook ads, website" /></div>`,
      footer: `<button class="btn btn-ghost grow" data-close>Cancel</button>
               <button class="btn btn-primary grow" data-create>Create key</button>`,
      onOpen(el, close) {
        el.querySelector('[data-create]').addEventListener('click', async () => {
          const label = el.querySelector('#keyLabel').value.trim() || 'Default';
          try {
            const { key } = await API.post('/api/api-keys', { label });
            close();
            UI.modal({
              title: 'Your new API key',
              body: `<div class="banner banner-warn mb-4"><div>${UI.icon('shield', 18)}</div>
                       <div><strong>Copy this now.</strong> It is stored hashed and cannot be shown again.</div></div>
                     <div class="copy-row">
                       <input class="input grow" value="${UI.esc(key)}" readonly id="newKeyValue" />
                       <button class="btn btn-primary btn-icon" data-copy-key aria-label="Copy">${UI.icon('copy')}</button>
                     </div>`,
              footer: '<button class="btn btn-primary btn-block" data-close>Done</button>',
              onOpen(m) {
                m.querySelector('[data-copy-key]').addEventListener('click', () => UI.copy(key, 'API key copied'));
                m.querySelector('#newKeyValue').select();
              },
              onClose: load,
            });
          } catch (err) { UI.errorToast(err); }
        });
      },
    });
  }

  async function load() {
    try { render(await API.get('/api/api-keys')); } catch (err) { UI.errorToast(err); }
  }

  area.innerHTML = '<div class="card"><div class="skeleton" style="height:240px"></div></div>';
  await load();
})();
