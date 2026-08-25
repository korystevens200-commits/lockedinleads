/**
 * Lead detail panel: conversation, qualification, booking, and the
 * AI Active / Human Takeover control.
 *
 * Full-screen sheet on mobile, side panel on desktop. Everything an owner needs
 * to rescue a stalled lead is reachable without leaving this panel.
 */
const LeadPanel = (() => {
  let state = { lead: null, messages: [], appointments: [], questions: [], tab: 'chat' };
  let el = null;
  let poll = null;
  let onChange = null;

  async function open(leadId, changeCallback) {
    onChange = changeCallback;
    close(false);
    render(true);
    await load(leadId);
    poll = setInterval(() => load(state.lead?.id, true), 8000);
    history.replaceState(null, '', `?lead=${encodeURIComponent(leadId)}`);
  }

  function close(clearUrl = true) {
    if (poll) { clearInterval(poll); poll = null; }
    el?.remove();
    el = null;
    document.body.style.overflow = '';
    if (clearUrl) history.replaceState(null, '', location.pathname);
  }

  async function load(leadId, quiet = false) {
    if (!leadId) return;
    try {
      const data = await API.get(`/api/leads/${encodeURIComponent(leadId)}`);
      const grew = data.messages.length !== state.messages.length;
      state = { ...state, ...data };
      render();
      if (grew || !quiet) scrollConvo();
    } catch (err) {
      if (!quiet) UI.errorToast(err);
    }
  }

  function scrollConvo() {
    const convo = el?.querySelector('#convoScroll');
    if (convo) convo.scrollTop = convo.scrollHeight;
  }

  // ------------------------------------------------------------ rendering
  function render(skeleton = false) {
    const lead = state.lead;
    if (!el) {
      el = document.createElement('div');
      el.className = 'detail-sheet';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-label', 'Lead details');
      document.body.appendChild(el);
      document.body.style.overflow = 'hidden';
    }
    if (skeleton || !lead) {
      el.innerHTML = `<div class="detail-head"><div class="grow"><div class="skeleton" style="height:20px;width:150px"></div></div></div>
        <div class="detail-body"><div class="card-body"><div class="skeleton" style="height:120px"></div></div></div>`;
      return;
    }

    el.innerHTML = `
      <div class="detail-head">
        <button class="icon-btn" data-close aria-label="Close">${UI.icon('back')}</button>
        <div class="grow" style="min-width:0">
          <div class="row gap-2" style="flex-wrap:wrap">
            <span class="card-title truncate">${UI.esc(lead.name || 'Unnamed lead')}</span>
            ${UI.statusBadge(lead.status)}${UI.scoreBadge(lead.score)}
          </div>
          <div class="tiny dim mt-1 truncate">
            ${UI.esc(lead.source_label)}${lead.location ? ' · ' + UI.esc(lead.location) : ''}
            · added ${UI.relTime(lead.created_at)}
          </div>
        </div>
        <div class="row gap-1">
          ${lead.phone ? `<a class="icon-btn" href="tel:${UI.esc(lead.phone.replace(/[^\\d+]/g, ''))}"
             aria-label="Call">${UI.icon('phone')}</a>` : ''}
          ${lead.email ? `<a class="icon-btn" href="mailto:${UI.esc(lead.email)}"
             aria-label="Email">${UI.icon('mail')}</a>` : ''}
        </div>
      </div>

      <div class="detail-tabs">
        <button class="detail-tab${state.tab === 'chat' ? ' is-active' : ''}" data-tab="chat">Conversation</button>
        <button class="detail-tab${state.tab === 'details' ? ' is-active' : ''}" data-tab="details">Details</button>
        <button class="detail-tab${state.tab === 'booking' ? ' is-active' : ''}" data-tab="booking">Booking</button>
      </div>

      <div class="detail-body">${
        state.tab === 'chat' ? chatTab(lead)
        : state.tab === 'details' ? detailsTab(lead)
        : bookingTab(lead)}</div>`;

    wire(lead);
    if (state.tab === 'chat') scrollConvo();
  }

  function chatTab(lead) {
    const canMessage = !lead.opted_out;
    return `
      <div style="padding:12px 12px 0">${aiToggle(lead)}</div>
      <div class="convo" id="convoScroll">${
        state.messages.length ? state.messages.map(messageBubble).join('') : emptyConversation(lead)
      }</div>
      ${lead.next_followup_at ? `<div class="tiny dim center" style="padding:6px 12px">
         ${UI.icon('clock', 12)}&nbsp;Next automatic follow-up ${UI.esc(state.next_followup_label || '')}
       </div>` : ''}
      <div class="convo-composer">
        ${canMessage ? `
          <div class="composer-row">
            <textarea class="textarea grow" id="composer" rows="1"
              placeholder="Reply as ${UI.esc(Shell.session?.tenant?.name || 'the business')}…"
              aria-label="Your reply"></textarea>
            <button class="btn btn-primary btn-icon" id="sendBtn" aria-label="Send">${UI.icon('send')}</button>
          </div>
          <div class="row gap-2 mt-3" style="flex-wrap:wrap">
            <button class="btn btn-sm btn-ghost" id="followupBtn">Send follow-up now</button>
            <button class="btn btn-sm btn-quiet" id="simulateBtn">Simulate customer reply</button>
          </div>
          <p class="tiny dim mt-2">Sending a message by hand switches this lead to Human takeover.</p>`
        : `<div class="banner banner-warn">
             <div>${UI.icon('shield', 16)}</div>
             <div><strong>This lead opted out.</strong> No further messages can be sent to them.</div>
           </div>`}
      </div>`;
  }

  /** The right prompt depends on why there is nothing here yet. */
  function emptyConversation(lead) {
    let hint;
    if (lead.opted_out) hint = 'This lead opted out before any message was sent.';
    else if (!lead.ai_active) hint = 'The assistant is paused. Switch it on above, or send the first message yourself.';
    else if (lead.next_followup_at) hint = 'The first message is queued and will send automatically. Use "Send follow-up now" to send it immediately.';
    else hint = 'Use "Send follow-up now" to send the first message, or write one yourself.';
    return `<div class="empty"><div class="empty-icon">${UI.icon('chat')}</div>
      <div class="empty-title">No messages yet</div>
      <div class="small">${UI.esc(hint)}</div></div>`;
  }

  function aiToggle(lead) {
    const on = lead.ai_active && !lead.opted_out;
    return `
      <div class="ai-toggle${on ? ' is-on' : ''}">
        <div>${UI.icon(on ? 'robot' : 'user', 20)}</div>
        <div class="ai-toggle-text">
          <div class="ai-toggle-title">${on ? 'AI Active' : 'Human takeover'}</div>
          <div class="ai-toggle-sub">${on
            ? 'Replying, qualifying and following up automatically'
            : 'The assistant is paused — replies are up to you'}</div>
        </div>
        <label class="switch" title="${on ? 'Pause the assistant' : 'Hand back to the assistant'}">
          <input type="checkbox" id="aiSwitch" ${on ? 'checked' : ''}
            ${lead.opted_out ? 'disabled' : ''} aria-label="AI active" />
          <span class="switch-track"></span>
        </label>
      </div>`;
  }

  function messageBubble(msg) {
    if (msg.role === 'system') {
      return `<div class="msg-system">${UI.esc(msg.body)}</div>`;
    }
    const outbound = msg.role !== 'lead';
    const who = msg.role === 'ai' ? 'Assistant' : msg.role === 'human'
      ? (msg.meta?.author || 'You') : '';
    return `
      <div class="msg msg-${msg.role} ${outbound ? 'msg-out' : 'msg-lead'}">
        <div class="msg-bubble">${UI.esc(msg.body)}</div>
        <div class="msg-time">${who ? UI.esc(who) + ' · ' : ''}${UI.dateTime(msg.created_at)}${
          msg.channel && msg.channel !== 'chat' ? ' · ' + UI.esc(msg.channel) : ''}</div>
      </div>`;
  }

  function detailsTab(lead) {
    const answers = Object.entries(lead.qualification || {});
    const byKey = Object.fromEntries((state.questions || []).map((q) => [q.field_key, q.prompt]));
    return `<div class="card-body stack gap-5">
      <div>
        <div class="label mb-3">Contact</div>
        <div class="kv kv-2">
          ${kv('Name', lead.name)}${kv('Phone', lead.phone)}
          ${kv('Email', lead.email)}${kv('Location', lead.location)}
          ${kv('Service requested', lead.service_requested)}${kv('Source', lead.source_label)}
          ${kv('Consent to contact', lead.consent ? 'Given' : 'Not recorded')}
          ${kv('First response', lead.first_response_ms ? UI.duration(lead.first_response_ms / 1000) : 'Not sent yet')}
          ${kv('Last contacted', lead.last_contact_at ? UI.relTime(lead.last_contact_at) : 'Never')}
          ${kv('Follow-ups sent', String(lead.followup_count || 0))}
        </div>
      </div>

      <div>
        <div class="label mb-3">Qualification answers</div>
        ${answers.length ? `<div class="kv">${answers.map(([k, v]) =>
          kv(byKey[k] || k.replace(/_/g, ' '), v)).join('')}</div>`
          : '<p class="small muted">Nothing collected yet — the assistant records answers as they come in.</p>'}
      </div>

      <div>
        <div class="label mb-3">Status &amp; value</div>
        <div class="field">
          <label for="statusSelect">Status</label>
          <select class="select" id="statusSelect">
            ${UI.STATUSES.map((s) => `<option value="${s}"${s === lead.status ? ' selected' : ''}>${
              UI.esc(UI.STATUS_LABEL[s])}</option>`).join('')}
          </select>
        </div>
        <div class="field">
          <label for="valueInput">Estimated value ($)</label>
          <input class="input" id="valueInput" type="number" min="0" step="10"
                 value="${Number(lead.estimated_value || 0)}" inputmode="decimal" />
        </div>
        <div class="field">
          <label for="notesInput">Notes</label>
          <textarea class="textarea" id="notesInput"
            placeholder="Anything the team should know…">${UI.esc(lead.notes || '')}</textarea>
        </div>
        ${lead.close_reason ? `<p class="small muted mb-3">Closed because: ${UI.esc(lead.close_reason)}</p>` : ''}
        <button class="btn btn-primary btn-block" id="saveDetails">Save changes</button>
      </div>
    </div>`;
  }

  function kv(label, value) {
    return `<div class="kv-item"><div class="kv-label">${UI.esc(label)}</div>
      <div class="kv-value">${UI.esc(value || '—')}</div></div>`;
  }

  function bookingTab(lead) {
    const appts = state.appointments || [];
    return `<div class="card-body stack gap-5">
      <div>
        <div class="label mb-3">Appointments</div>
        ${appts.length ? `<div class="record-list">${appts.map((a) => `
          <div class="record" style="cursor:default">
            <div class="record-top">
              <div>
                <div class="record-name">${UI.esc(a.service || 'Appointment')}</div>
                <div class="record-meta">${UI.dateTime(a.starts_at)}</div>
              </div>
              <span class="badge badge-${a.status === 'cancelled' ? 'LOST' : a.status === 'completed' ? 'CUSTOMER' : 'BOOKED'}">${UI.esc(a.status)}</span>
            </div>
            <div class="record-foot">
              ${a.value ? `<span>${UI.money(a.value)}</span>` : ''}
              ${a.status === 'scheduled' ? `
                <span style="margin-left:auto" class="row gap-2">
                  <button class="btn btn-sm btn-ghost" data-appt-complete="${UI.esc(a.id)}">Mark completed</button>
                  <button class="btn btn-sm btn-quiet" data-appt-cancel="${UI.esc(a.id)}">Cancel</button>
                </span>` : ''}
            </div>
          </div>`).join('')}</div>`
          : '<p class="small muted">No appointment yet.</p>'}
      </div>
      <div>
        <div class="label mb-3">Book a time manually</div>
        <p class="small muted mb-3">These are real open slots from your availability, with booked times removed.</p>
        <div id="slotList" class="chip-row"><span class="small dim">Loading open times…</span></div>
      </div>
    </div>`;
  }

  // ------------------------------------------------------------- behaviour
  function wire(lead) {
    el.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => {
      close();
      if (onChange) onChange();
    }));
    el.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => {
      state.tab = b.dataset.tab;
      render();
      if (state.tab === 'booking') loadSlots();
    }));

    const aiSwitch = el.querySelector('#aiSwitch');
    aiSwitch?.addEventListener('change', async () => {
      try {
        const { lead: updated } = await API.post(`/api/leads/${encodeURIComponent(lead.id)}/ai`,
          { active: aiSwitch.checked });
        state.lead = updated;
        render();
        UI.toast(updated.ai_active ? 'Assistant re-activated' : 'Human takeover on',
          updated.ai_active ? 'It will follow up automatically again.' : 'Automatic replies are paused.');
        if (onChange) onChange();
      } catch (err) {
        aiSwitch.checked = !aiSwitch.checked;
        UI.errorToast(err);
      }
    });

    const composer = el.querySelector('#composer');
    const sendBtn = el.querySelector('#sendBtn');
    if (composer) {
      composer.addEventListener('input', () => {
        composer.style.height = 'auto';
        composer.style.height = Math.min(composer.scrollHeight, 130) + 'px';
      });
      composer.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
      });
    }
    sendBtn?.addEventListener('click', send);

    async function send() {
      const body = composer.value.trim();
      if (!body) return;
      sendBtn.disabled = true;
      try {
        await API.post(`/api/leads/${encodeURIComponent(lead.id)}/messages`, { body });
        composer.value = '';
        composer.style.height = 'auto';
        await load(lead.id);
        if (onChange) onChange();
      } catch (err) {
        UI.errorToast(err);
      } finally {
        sendBtn.disabled = false;
      }
    }

    el.querySelector('#followupBtn')?.addEventListener('click', async (e) => {
      e.target.disabled = true;
      try {
        await API.post(`/api/leads/${encodeURIComponent(lead.id)}/followup`);
        await load(lead.id);
        UI.toast('Follow-up sent');
        if (onChange) onChange();
      } catch (err) { UI.errorToast(err); } finally { e.target.disabled = false; }
    });

    el.querySelector('#simulateBtn')?.addEventListener('click', () => {
      UI.modal({
        title: 'Simulate a customer reply',
        body: `<p class="small muted mb-4">Runs a message through the real assistant so you can see how it
                 responds — nothing is sent to the customer.</p>
               <div class="field"><label for="simText">Customer says</label>
                 <input class="input" id="simText" placeholder="Deep clean, 3 bed 2 bath in Coral Gables" /></div>`,
        footer: `<button class="btn btn-ghost grow" data-close>Cancel</button>
                 <button class="btn btn-primary grow" data-run>Run</button>`,
        onOpen(m, closeModal) {
          const run = async () => {
            const text = m.querySelector('#simText').value.trim();
            if (!text) return;
            closeModal();
            try {
              await API.post(`/api/leads/${encodeURIComponent(lead.id)}/simulate`, { text });
              await load(lead.id);
              if (onChange) onChange();
            } catch (err) { UI.errorToast(err); }
          };
          m.querySelector('[data-run]').addEventListener('click', run);
          m.querySelector('#simText').addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
        },
      });
    });

    el.querySelector('#saveDetails')?.addEventListener('click', async (e) => {
      e.target.disabled = true;
      try {
        await API.patch(`/api/leads/${encodeURIComponent(lead.id)}`, {
          status: el.querySelector('#statusSelect').value,
          estimated_value: el.querySelector('#valueInput').value,
          notes: el.querySelector('#notesInput').value,
        });
        await load(lead.id);
        UI.toast('Lead updated');
        if (onChange) onChange();
      } catch (err) { UI.errorToast(err); } finally { e.target.disabled = false; }
    });

    el.querySelectorAll('[data-appt-complete]').forEach((b) => b.addEventListener('click', () =>
      updateAppointment(b.dataset.apptComplete, 'completed', 'Marked completed — lead is now a customer.')));
    el.querySelectorAll('[data-appt-cancel]').forEach((b) => b.addEventListener('click', async () => {
      if (!(await UI.confirmDialog('Cancel appointment?',
        'The time slot will be freed up for another lead.', 'Cancel appointment'))) return;
      updateAppointment(b.dataset.apptCancel, 'cancelled', 'Appointment cancelled.');
    }));
  }

  async function updateAppointment(id, status, message) {
    try {
      await API.patch(`/api/appointments/${encodeURIComponent(id)}`, { status });
      await load(state.lead.id);
      UI.toast(message);
      if (onChange) onChange();
    } catch (err) { UI.errorToast(err); }
  }

  async function loadSlots() {
    const target = el.querySelector('#slotList');
    if (!target) return;
    try {
      const { slots } = await API.get(`/api/leads/${encodeURIComponent(state.lead.id)}/slots?count=8`);
      if (!slots.length) {
        target.innerHTML = `<p class="small muted">No open times in your availability window.
          Check Automation → Booking availability.</p>`;
        return;
      }
      target.innerHTML = slots.map((s) =>
        `<button class="chip" data-slot="${s.starts_at}" data-end="${s.ends_at}">${UI.esc(s.label)}</button>`).join('');
      target.querySelectorAll('[data-slot]').forEach((b) => b.addEventListener('click', async () => {
        b.disabled = true;
        try {
          await API.post(`/api/leads/${encodeURIComponent(state.lead.id)}/appointments`, {
            starts_at: Number(b.dataset.slot), ends_at: Number(b.dataset.end),
          });
          await load(state.lead.id);
          UI.toast('Appointment booked', 'The owner notification has gone out.');
          if (onChange) onChange();
        } catch (err) { UI.errorToast(err); b.disabled = false; }
      }));
    } catch (err) {
      target.innerHTML = `<p class="small muted">Could not load open times.</p>`;
    }
  }

  return { open, close };
})();
