/**
 * Customer-facing chat widget.
 *
 * The lead-capture step comes first on purpose: a name and a way to reach them
 * is what makes the conversation recoverable if they close the tab, and it is
 * where consent is recorded.
 */
(function () {
  const params = new URLSearchParams(location.search);
  const slug = (params.get('b') || params.get('business') || '').trim();

  const els = {
    shell: document.getElementById('shell'),
    business: document.getElementById('chatBusiness'),
    assistant: document.getElementById('chatAssistant'),
    avatar: document.getElementById('chatAvatar'),
    scroll: document.getElementById('chatScroll'),
    convo: document.getElementById('convo'),
    foot: document.getElementById('chatFoot'),
    intro: document.getElementById('chatIntro'),
    introTitle: document.getElementById('introTitle'),
    introBody: document.getElementById('introBody'),
  };
  els.avatar.innerHTML = UI.icon('chat', 20);

  let token = sessionStorage.getItem('lil_chat_token_' + slug) || null;
  let poller = null;
  let lastCount = 0;

  if (!slug) {
    els.business.textContent = 'Not available';
    els.assistant.textContent = 'No business selected';
    els.foot.innerHTML = `<div class="banner banner-danger">
      This chat link is missing its business code. Please use the link the business gave you.</div>`;
    return;
  }

  async function call(path, options = {}) {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
    return data;
  }

  // ------------------------------------------------------------- capture
  function renderCapture() {
    els.foot.innerHTML = `
      <form id="startForm" novalidate>
        <div class="field">
          <label for="cw-name">Your name</label>
          <input class="input" id="cw-name" name="name" autocomplete="name" placeholder="Jenna Ortiz" required />
        </div>
        <div class="field">
          <label for="cw-phone">Mobile number</label>
          <input class="input" id="cw-phone" name="phone" type="tel" inputmode="tel"
                 autocomplete="tel" placeholder="(305) 555-0142" />
        </div>
        <div class="field">
          <label for="cw-email">Email <span class="dim" style="font-weight:400">(optional)</span></label>
          <input class="input" id="cw-email" name="email" type="email" inputmode="email"
                 autocomplete="email" placeholder="you@example.com" />
        </div>
        <label class="checkbox mb-3">
          <input type="checkbox" name="consent" id="cw-consent" />
          <span id="consentText">I agree to be contacted about my enquiry. Message and data rates may
            apply. Reply STOP at any time to opt out.</span>
        </label>
        <p class="field-error hidden mb-3" id="cw-error" role="alert"></p>
        <button class="btn btn-primary btn-block btn-lg" type="submit" id="cw-start">Start</button>
      </form>`;

    const form = document.getElementById('startForm');
    const error = document.getElementById('cw-error');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      error.classList.add('hidden');
      const values = UI.formValues(form);
      if (!values.name.trim()) return fail('Please enter your name.');
      if (!values.phone.trim() && !values.email.trim())
        return fail('Add a mobile number or an email so we can get back to you.');
      if (!values.consent) return fail('Please tick the box so we can reply to you.');

      const button = document.getElementById('cw-start');
      button.disabled = true;
      button.textContent = 'Starting…';
      try {
        const data = await call(`/api/chat/${encodeURIComponent(slug)}/start`, {
          method: 'POST', body: JSON.stringify(values),
        });
        token = data.token;
        sessionStorage.setItem('lil_chat_token_' + slug, token);
        applyBusiness(data.business);
        els.intro.classList.add('hidden');
        renderMessages(data.messages);
        renderComposer();
        startPolling();
      } catch (err) {
        button.disabled = false;
        button.textContent = 'Start';
        fail(err.message);
      }

      function fail(message) {
        error.textContent = message;
        error.classList.remove('hidden');
      }
    });
  }

  // ----------------------------------------------------------- composer
  function renderComposer() {
    els.foot.innerHTML = `
      <div class="composer-row">
        <textarea class="textarea grow" id="cwInput" rows="1" placeholder="Type your reply…"
                  aria-label="Your message"></textarea>
        <button class="btn btn-primary btn-icon" id="cwSend" aria-label="Send">${UI.icon('send')}</button>
      </div>
      <div class="chat-legal">Reply STOP at any time to stop messages.</div>`;

    const input = document.getElementById('cwInput');
    const send = document.getElementById('cwSend');
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
    });
    send.addEventListener('click', submit);
    setTimeout(() => input.focus(), 120);

    async function submit() {
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      input.style.height = 'auto';
      send.disabled = true;
      appendLocal(text);
      showTyping();
      try {
        const data = await call('/api/chat/message', {
          method: 'POST', body: JSON.stringify({ token, text }),
        });
        renderMessages(data.messages);
      } catch (err) {
        hideTyping();
        UI.toast(err.message, '', 'error');
      } finally {
        send.disabled = false;
      }
    }
  }

  function appendLocal(text) {
    els.convo.insertAdjacentHTML('beforeend', `
      <div class="msg msg-out msg-human"><div class="msg-bubble">${UI.esc(text)}</div></div>`);
    scrollDown();
  }

  function showTyping() {
    if (document.getElementById('typingRow')) return;
    els.convo.insertAdjacentHTML('beforeend', `
      <div class="msg msg-lead" id="typingRow"><div class="msg-bubble">
        <span class="typing"><i></i><i></i><i></i></span></div></div>`);
    scrollDown();
  }

  function hideTyping() { document.getElementById('typingRow')?.remove(); }

  /** The lead is on the right; the business (AI or a person) on the left. */
  function renderMessages(messages) {
    hideTyping();
    lastCount = messages.length;
    els.convo.innerHTML = messages.map((m) => {
      const mine = m.role === 'lead';
      return `<div class="msg ${mine ? 'msg-out msg-human' : 'msg-lead'}">
        <div class="msg-bubble">${UI.esc(m.body)}</div>
        <div class="msg-time">${UI.timeOnly(m.created_at)}</div>
      </div>`;
    }).join('');
    scrollDown();
  }

  function scrollDown() {
    requestAnimationFrame(() => { els.scroll.scrollTop = els.scroll.scrollHeight; });
  }

  function applyBusiness(business) {
    if (!business) return;
    els.business.textContent = business.name;
    els.assistant.textContent = `${business.assistant} is online`;
    document.title = `Chat with ${business.name}`;
    els.introTitle.textContent = `Chat with ${business.name}`;
  }

  // Polls so a reply typed by the business owner in their dashboard shows up here.
  function startPolling() {
    if (poller) clearInterval(poller);
    poller = setInterval(async () => {
      if (document.hidden) return;
      try {
        const data = await call(`/api/chat/messages?token=${encodeURIComponent(token)}`);
        if (data.messages.length !== lastCount) renderMessages(data.messages);
      } catch (err) {
        clearInterval(poller);
        poller = null;
      }
    }, 6000);
  }

  // --------------------------------------------------------------- boot
  async function resume() {
    try {
      const data = await call(`/api/chat/messages?token=${encodeURIComponent(token)}`);
      els.intro.classList.add('hidden');
      renderMessages(data.messages);
      renderComposer();
      startPolling();
      els.business.textContent = document.title.replace('Chat with ', '') || 'Chat';
      els.assistant.textContent = 'Online';
      return true;
    } catch (err) {
      sessionStorage.removeItem('lil_chat_token_' + slug);
      token = null;
      return false;
    }
  }

  (async function boot() {
    els.business.textContent = 'Chat';
    els.assistant.textContent = 'Online';
    if (token && (await resume())) return;
    renderCapture();
  })();
})();
