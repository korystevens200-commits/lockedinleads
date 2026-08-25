/**
 * Seven-step setup wizard.
 *
 * Every step writes straight through to the same settings the assistant reads,
 * so the test conversation in step 7 is running against the real configuration
 * — not a preview of one.
 */
(async function () {
  await Shell.init('dashboard', { title: 'Setup' });

  const STEPS = [
    { key: 'business', label: 'Business', sections: ['business'] },
    { key: 'services', label: 'Services', sections: ['services'] },
    { key: 'areas', label: 'Service areas', sections: ['areas'] },
    { key: 'questions', label: 'Questions', sections: ['questions'] },
    { key: 'booking', label: 'Booking', sections: ['hours', 'booking'] },
    { key: 'connect', label: 'Lead sources', sections: [] },
    { key: 'test', label: 'Test the AI', sections: [] },
  ];

  const els = {
    steps: document.getElementById('wizSteps'),
    panel: document.getElementById('wizPanel'),
    back: document.getElementById('backBtn'),
    next: document.getElementById('nextBtn'),
    title: document.getElementById('wizTitle'),
    sub: document.getElementById('wizSub'),
  };
  let cfg = null;
  let index = 0;
  let testHistory = [];

  function renderSteps() {
    els.steps.innerHTML = STEPS.map((step, i) => `
      <div class="wizard-step${i === index ? ' is-active' : i < index ? ' is-done' : ''}">
        <span class="wizard-num">${i < index ? '&check;' : i + 1}</span>${UI.esc(step.label)}
      </div>`).join('');
    els.steps.children[index]?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
  }

  async function renderStep() {
    renderSteps();
    const step = STEPS[index];
    els.back.disabled = index === 0;
    els.next.textContent = index === STEPS.length - 1 ? 'Finish setup' : 'Save & continue';

    if (step.sections.length) {
      els.panel.innerHTML = step.sections.map((s) => SettingsForms.renderSection(s, cfg)).join('');
      step.sections.forEach((s) => SettingsForms.wireSection(s, els.panel));
    } else if (step.key === 'connect') {
      await renderConnect();
    } else {
      renderTest();
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function renderConnect() {
    els.panel.innerHTML = '<div class="card"><div class="skeleton" style="height:200px"></div></div>';
    try {
      const data = await API.get('/api/api-keys');
      els.panel.innerHTML = `
        <div class="card">
          <div class="card-title mb-2">Where will leads come from?</div>
          <p class="small muted mb-5">Connect at least one now, or skip and do it later — manual entry
            works from day one either way.</p>
          <div class="field">
            <label>Point your website form here</label>
            <div class="copy-row">
              <input class="input grow" value="${UI.esc(data.form_url)}" readonly />
              <button class="btn btn-ghost btn-icon" data-copy="${UI.esc(data.form_url)}"
                aria-label="Copy form URL">${UI.icon('copy')}</button>
            </div>
            <div class="field-hint">Standard field names are detected automatically.</div>
          </div>
          <div class="field">
            <label>Or share your chat link</label>
            <div class="copy-row">
              <input class="input grow" value="${UI.esc(data.chat_url)}" readonly />
              <button class="btn btn-ghost btn-icon" data-copy="${UI.esc(data.chat_url)}"
                aria-label="Copy chat URL">${UI.icon('copy')}</button>
            </div>
          </div>
          <div class="field">
            <label>Webhook for Zapier, Facebook or Google lead ads</label>
            <div class="copy-row">
              <input class="input grow" value="${UI.esc(data.webhook_url)}" readonly />
              <button class="btn btn-ghost btn-icon" data-copy="${UI.esc(data.webhook_url)}"
                aria-label="Copy webhook URL">${UI.icon('copy')}</button>
            </div>
            <div class="field-hint">Send it with an <span class="mono">X-API-Key</span> header.
              ${data.keys.length ? 'You already have a key.' : ''}</div>
          </div>
          ${data.keys.length ? '' : `<button class="btn btn-ghost btn-sm" id="wizKeyBtn">Create an API key</button>`}
          <p class="small muted mt-4">Full details and delivery logs live in
            <a class="accent-text" href="/app/connect.html">Lead sources</a>.</p>
        </div>`;
      els.panel.querySelectorAll('[data-copy]').forEach((b) =>
        b.addEventListener('click', () => UI.copy(b.dataset.copy)));
      document.getElementById('wizKeyBtn')?.addEventListener('click', async () => {
        try {
          const { key } = await API.post('/api/api-keys', { label: 'Setup' });
          UI.modal({
            title: 'Your API key',
            body: `<div class="banner banner-warn mb-4"><div>${UI.icon('shield', 18)}</div>
                     <div><strong>Copy it now</strong> — it is stored hashed and never shown again.</div></div>
                   <div class="copy-row"><input class="input grow" value="${UI.esc(key)}" readonly />
                     <button class="btn btn-primary btn-icon" data-k aria-label="Copy">${UI.icon('copy')}</button></div>`,
            footer: '<button class="btn btn-primary btn-block" data-close>Done</button>',
            onOpen(m) { m.querySelector('[data-k]').addEventListener('click', () => UI.copy(key, 'Copied')); },
            onClose: renderConnect,
          });
        } catch (err) { UI.errorToast(err); }
      });
    } catch (err) { UI.errorToast(err); }
  }

  function renderTest() {
    els.panel.innerHTML = `
      <div class="card">
        <div class="card-title mb-2">Test the assistant</div>
        <p class="small muted mb-4">This runs your real configuration — same services, areas, questions and
          open times a customer would get. Nothing is saved and nobody is messaged.</p>
        <div class="card card-flush" style="background:var(--bg)">
          <div class="convo" id="testConvo" style="max-height:340px"></div>
          <div class="convo-composer">
            <div class="composer-row">
              <input class="input grow" id="testInput" placeholder="Type what a customer might say…"
                     aria-label="Customer message" />
              <button class="btn btn-primary btn-icon" id="testSend" aria-label="Send">${UI.icon('send')}</button>
            </div>
            <div class="chip-row mt-3">
              <button class="chip" data-quick="I need a deep clean">"I need a deep clean"</button>
              <button class="chip" data-quick="How much do you charge?">"How much do you charge?"</button>
              <button class="chip" data-quick="Do you cover my area?">"Do you cover my area?"</button>
              <button class="chip btn-quiet" id="testReset">Start over</button>
            </div>
          </div>
        </div>
        <div id="testMeta" class="mt-4"></div>
      </div>`;

    document.getElementById('testSend').addEventListener('click', sendTest);
    document.getElementById('testInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sendTest();
    });
    document.getElementById('testReset').addEventListener('click', () => {
      testHistory = [];
      renderTestConvo();
      startTest();
    });
    els.panel.querySelectorAll('[data-quick]').forEach((b) => b.addEventListener('click', () => {
      document.getElementById('testInput').value = b.dataset.quick;
      sendTest();
    }));
    if (!testHistory.length) startTest(); else renderTestConvo();
  }

  function renderTestConvo() {
    const convo = document.getElementById('testConvo');
    if (!convo) return;
    convo.innerHTML = testHistory.length ? testHistory.map((m) => `
      <div class="msg msg-${m.role} ${m.role === 'lead' ? 'msg-lead' : 'msg-out'}">
        <div class="msg-bubble">${UI.esc(m.body)}</div>
      </div>`).join('')
      : `<div class="msg msg-ai msg-out"><div class="msg-bubble typing-wrap">
           <span class="typing"><i></i><i></i><i></i></span></div></div>`;
    convo.scrollTop = convo.scrollHeight;
  }

  async function startTest() {
    renderTestConvo();
    try {
      const result = await API.post('/api/ai/test', { history: [] });
      testHistory = [{ role: 'ai', body: result.reply, meta: result.meta }];
      renderTestConvo();
      showTestMeta(result);
    } catch (err) { UI.errorToast(err); }
  }

  async function sendTest() {
    const input = document.getElementById('testInput');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    testHistory.push({ role: 'lead', body: text });
    renderTestConvo();
    try {
      const result = await API.post('/api/ai/test', { history: testHistory, text });
      testHistory.push({ role: 'ai', body: result.reply, meta: result.meta });
      renderTestConvo();
      showTestMeta(result);
    } catch (err) { UI.errorToast(err); }
  }

  function showTestMeta(result) {
    const meta = document.getElementById('testMeta');
    if (!meta) return;
    meta.innerHTML = `<div class="row gap-2" style="flex-wrap:wrap">
      <span class="pill">Intent: <strong>${UI.esc(result.intent.replace(/_/g, ' '))}</strong></span>
      <span class="pill${result.qualified ? ' pill-accent' : ''}">
        ${result.qualified ? 'Qualified' : 'Still qualifying'}</span>
      <span class="pill">Engine: <strong>${UI.esc(result.provider)}</strong></span>
      ${result.slots.length ? `<span class="pill">${result.slots.length} open time${
        result.slots.length === 1 ? '' : 's'} available</span>`
        : '<span class="pill">No open times — check booking availability</span>'}
    </div>`;
  }

  async function saveCurrentStep() {
    const step = STEPS[index];
    if (!step.sections.length) return true;
    const patch = SettingsForms.readSections(step.sections, els.panel);
    if (step.key === 'services' && !(patch.services || []).length) {
      UI.toast('Add at least one service', 'The assistant can only offer what you list here.', 'error');
      return false;
    }
    if (step.key === 'areas' && !(patch.areas || []).length) {
      UI.toast('Add at least one service area', 'Otherwise every lead looks out of area.', 'error');
      return false;
    }
    try {
      cfg = await API.patch('/api/settings', patch);
      return true;
    } catch (err) {
      UI.errorToast(err);
      return false;
    }
  }

  els.next.addEventListener('click', async () => {
    els.next.disabled = true;
    try {
      if (!(await saveCurrentStep())) return;
      if (index < STEPS.length - 1) {
        index += 1;
        await API.post('/api/onboarding/step', { step: index + 1 });
        await renderStep();
      } else {
        await finish();
      }
    } finally {
      els.next.disabled = false;
    }
  });

  els.back.addEventListener('click', async () => {
    if (index === 0) return;
    index -= 1;
    await renderStep();
  });

  async function finish() {
    try {
      await API.post('/api/onboarding/complete');
    } catch (err) {
      UI.errorToast(err);
      return;
    }
    els.steps.classList.add('hidden');
    document.querySelector('.wizard-actions').classList.add('hidden');
    els.title.textContent = 'You’re live';
    els.sub.textContent = '';
    els.panel.innerHTML = `
      <div class="card" style="text-align:center;padding:44px 24px;
           background:linear-gradient(160deg,var(--accent-soft),transparent 60%);border-color:var(--accent-line)">
        <div style="width:62px;height:62px;margin:0 auto 18px;border-radius:20px;background:var(--accent);
             color:var(--accent-ink);display:grid;place-items:center">${UI.icon('check', 32)}</div>
        <h2 style="font-size:26px;margin-bottom:8px">Your LockedinLeads system is ready.</h2>
        <p class="lead-text" style="max-width:460px;margin:0 auto 24px">
          Every lead that arrives from now on gets an instant response, gets qualified, gets followed up,
          and gets offered a real time on your calendar &mdash; 24/7.</p>
        <div class="row gap-3 center" style="flex-wrap:wrap">
          <a class="btn btn-primary btn-lg" href="/app/">Go to dashboard</a>
          <a class="btn btn-ghost btn-lg" href="/app/connect.html">Connect a lead source</a>
        </div>
      </div>`;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  els.panel.innerHTML = '<div class="card"><div class="skeleton" style="height:320px"></div></div>';
  try {
    cfg = await API.get('/api/settings');
    index = Math.min(Math.max((cfg.business.onboarding_step || 1) - 1, 0), STEPS.length - 1);
    await renderStep();
  } catch (err) { UI.errorToast(err); }
})();
