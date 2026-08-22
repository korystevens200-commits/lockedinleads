/**
 * chat.js — the customer-facing "AI" qualification flow.
 * Scripted state machine today; swap the respond() step logic for a real
 * LLM call later without touching the rendering or persistence code.
 */

(function () {
  const business = ALM.getBusiness();

  const els = {
    log: document.getElementById('chatLog'),
    inputRow: document.getElementById('chatInputRow'),
    launcher: document.getElementById('chatLauncher'),
    panel: document.getElementById('chatPanel'),
    closeBtn: document.getElementById('chatClose'),
  };

  let lead = null;

  const HOME_SIZES = [
    { v: 'studio', l: 'Studio' }, { v: '1br', l: '1 Bedroom' },
    { v: '2br', l: '2 Bedroom' }, { v: '3br', l: '3 Bedroom' }, { v: '4br+', l: '4+ Bedroom' },
  ];
  const CLEAN_TYPES = [
    { v: 'standard', l: 'Standard Clean' }, { v: 'deep', l: 'Deep Clean' }, { v: 'move-in-out', l: 'Move In/Out' },
  ];
  const FREQUENCIES = [
    { v: 'one-time', l: 'One-time' }, { v: 'weekly', l: 'Weekly' },
    { v: 'biweekly', l: 'Every 2 Weeks' }, { v: 'monthly', l: 'Monthly' },
  ];

  function scrollToBottom() {
    els.log.scrollTop = els.log.scrollHeight;
  }

  function addBubble(from, html) {
    const wrap = document.createElement('div');
    wrap.className = `flex ${from === 'lead' ? 'justify-end' : 'justify-start'} mb-3 bubble-in`;
    const bubble = document.createElement('div');
    bubble.className =
      from === 'lead'
        ? 'max-w-[80%] bg-teal-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm shadow-sm'
        : 'max-w-[80%] bg-white border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-slate-700 shadow-sm';
    bubble.innerHTML = html;
    wrap.appendChild(bubble);
    els.log.appendChild(wrap);
    scrollToBottom();
  }

  function addTyping() {
    const wrap = document.createElement('div');
    wrap.id = 'typingBubble';
    wrap.className = 'flex justify-start mb-3 bubble-in';
    wrap.innerHTML = `<div class="bg-white border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm flex gap-1">
      <span class="typing-dot w-1.5 h-1.5 bg-slate-400 rounded-full"></span>
      <span class="typing-dot w-1.5 h-1.5 bg-slate-400 rounded-full"></span>
      <span class="typing-dot w-1.5 h-1.5 bg-slate-400 rounded-full"></span>
    </div>`;
    els.log.appendChild(wrap);
    scrollToBottom();
  }

  function removeTyping() {
    document.getElementById('typingBubble')?.remove();
  }

  async function aiSay(text, opts = {}) {
    addTyping();
    await new Promise((r) => setTimeout(r, opts.delay ?? 550));
    removeTyping();
    addBubble('ai', text);
    if (lead) await ALM.appendTranscript(lead.id, { from: 'ai', text: stripHtml(text) });
  }

  function stripHtml(html) {
    const d = document.createElement('div');
    d.innerHTML = html;
    return d.textContent || '';
  }

  async function leadSay(text) {
    addBubble('lead', escapeHtml(text));
    if (lead) await ALM.appendTranscript(lead.id, { from: 'lead', text });
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function renderTextInput(placeholder, onSubmit, opts = {}) {
    els.inputRow.innerHTML = '';
    const form = document.createElement('form');
    form.className = 'flex gap-2';
    form.innerHTML = `
      <input type="${opts.type || 'text'}" autocomplete="off" placeholder="${escapeHtml(placeholder)}"
        class="flex-1 border border-slate-300 rounded-xl px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent" />
      <button type="submit" class="bg-teal-600 hover:bg-teal-700 text-white rounded-xl px-4 py-2.5 text-sm font-medium transition">Send</button>
    `;
    const input = form.querySelector('input');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const val = input.value.trim();
      if (!val) return;
      els.inputRow.innerHTML = '';
      await leadSay(val);
      onSubmit(val);
    });
    els.inputRow.appendChild(form);
    setTimeout(() => input.focus(), 50);
  }

  /** Phone step ships with a required TCPA-style consent checkbox. */
  function renderPhoneInput(onSubmit) {
    els.inputRow.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.innerHTML = `
      <form class="flex gap-2 mb-2">
        <input type="tel" autocomplete="off" placeholder="(305) 555-0100"
          class="flex-1 border border-slate-300 rounded-xl px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent" />
        <button type="submit" disabled
          class="bg-teal-600 disabled:bg-slate-300 disabled:cursor-not-allowed hover:enabled:bg-teal-700 text-white rounded-xl px-4 py-2.5 text-sm font-medium transition">Send</button>
      </form>
      <label class="flex items-start gap-2 text-[11px] leading-snug text-slate-500 cursor-pointer select-none">
        <input type="checkbox" class="mt-0.5 accent-teal-600" />
        <span>By submitting my number, I agree to receive texts and emails from ${business.name} about my quote and appointment. Msg &amp; data rates may apply. Reply STOP to opt out.</span>
      </label>
      <p class="hidden text-[11px] text-red-500 mt-1" data-error>Please check the box above to continue.</p>
    `;
    const form = wrap.querySelector('form');
    const input = form.querySelector('input');
    const checkbox = wrap.querySelector('input[type=checkbox]');
    const submitBtn = form.querySelector('button');
    const errorEl = wrap.querySelector('[data-error]');

    checkbox.addEventListener('change', () => {
      submitBtn.disabled = !checkbox.checked;
      if (checkbox.checked) errorEl.classList.add('hidden');
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const val = input.value.trim();
      if (!val) return;
      if (!checkbox.checked) {
        errorEl.classList.remove('hidden');
        return;
      }
      els.inputRow.innerHTML = '';
      await leadSay(val);
      onSubmit(val);
    });
    els.inputRow.appendChild(wrap);
    setTimeout(() => input.focus(), 50);
  }

  function renderChips(options, onSubmit) {
    els.inputRow.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'flex flex-wrap gap-2';
    options.forEach((opt) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip bg-white border border-teal-200 text-teal-700 hover:bg-teal-50 rounded-full px-4 py-2 text-sm font-medium shadow-sm';
      btn.textContent = opt.l;
      btn.addEventListener('click', async () => {
        els.inputRow.innerHTML = '';
        await leadSay(opt.l);
        onSubmit(opt.v, opt.l);
      });
      wrap.appendChild(btn);
    });
    els.inputRow.appendChild(wrap);
  }

  async function patch(fields) {
    lead = await ALM.updateLead(lead.id, { ...fields, lastActivityAt: Date.now() });
    return lead;
  }

  async function start() {
    lead = await ALM.createLead({});
    await aiSay(`Hi! I'm <b>Aria</b>, the virtual assistant for <b>${business.name}</b>. I can get you an instant quote and grab a spot on the schedule — takes about a minute. What's your name?`);
    renderTextInput('Your full name…', handleName);
  }

  async function handleName(val) {
    await patch({ name: val });
    await aiSay(`Nice to meet you, ${val.split(' ')[0]}! What's the best phone number to reach you at?`);
    renderPhoneInput(handlePhone);
  }

  async function handlePhone(val) {
    await patch({ phone: val, phoneConsent: true });
    await aiSay(`Got it. What's the service address? (Street + city is great.)`);
    renderTextInput('123 Main St, Miami, FL', handleAddress);
  }

  async function handleAddress(val) {
    await patch({ address: val });
    if (!ALM.inServiceArea(val)) {
      await patch({ status: 'out-of-area', score: 'out-of-area' });
      await aiSay(`Thanks! Unfortunately that's just outside our current service area (${business.serviceAreas.join(', ')}). I've saved your info and someone will reach out if we expand nearby. 💙`);
      els.inputRow.innerHTML = `<p class="text-xs text-slate-400 text-center w-full">Conversation ended</p>`;
      return;
    }
    await aiSay(`Great news — we service that area! What size is the home?`);
    renderChips(HOME_SIZES, handleHomeSize);
  }

  async function handleHomeSize(val) {
    await patch({ homeSize: val });
    await aiSay(`Perfect. What kind of cleaning are you looking for?`);
    renderChips(CLEAN_TYPES, handleCleanType);
  }

  async function handleCleanType(val) {
    await patch({ cleaningType: val });
    await aiSay(`And how often would you like this service?`);
    renderChips(FREQUENCIES, handleFrequency);
  }

  async function handleFrequency(val) {
    await patch({ frequency: val });
    await aiSay(`Last question — what date works best for your first cleaning?`);
    renderTextInput('e.g. Aug 28, or "next Tuesday"', handleDate);
  }

  async function handleDate(val) {
    await patch({ preferredDate: val });

    const q = ALM.qualifyLead(lead);
    const quote = ALM.estimateQuote(lead);
    await patch({ quote, status: q.qualified ? 'qualified' : 'needs-follow-up', score: q.score });

    await aiSay(
      `You're all set, ${lead.name.split(' ')[0]}! Based on a ${labelFor(HOME_SIZES, lead.homeSize)}, ${labelFor(CLEAN_TYPES, lead.cleaningType).toLowerCase()}, ${labelFor(FREQUENCIES, lead.frequency).toLowerCase()} — your estimate is <b>$${quote}</b>.`,
      { delay: 700 }
    );

    if (q.qualified) {
      await aiSay(`Want to lock in ${lead.preferredDate}? Here are a few open slots:`);
      const slots = [
        { v: `${lead.preferredDate}, 9:00 AM`, l: `${lead.preferredDate}, 9:00 AM` },
        { v: `${lead.preferredDate}, 1:00 PM`, l: `${lead.preferredDate}, 1:00 PM` },
        { v: `${lead.preferredDate}, 4:00 PM`, l: `${lead.preferredDate}, 4:00 PM` },
      ];
      renderChips(slots, handleBooking);
    } else {
      els.inputRow.innerHTML = `<p class="text-xs text-slate-400 text-center w-full">Conversation ended</p>`;
    }
  }

  async function handleBooking(val) {
    await patch({ status: 'booked', bookedSlot: val });
    await aiSay(`🎉 You're booked for <b>${val}</b>! A confirmation text is on its way to ${lead.phone}. Thanks for choosing ${business.name}!`);
    els.inputRow.innerHTML = `<p class="text-xs text-emerald-600 font-medium text-center w-full">✓ Appointment booked</p>`;
  }

  function labelFor(list, v) {
    return list.find((o) => o.v === v)?.l || v;
  }

  function openChat() {
    els.panel.classList.remove('hidden', 'pointer-events-none', 'opacity-0', 'translate-y-4');
    els.launcher.classList.add('hidden');
    if (!lead) start();
  }

  function closeChat() {
    els.panel.classList.add('hidden');
    els.launcher.classList.remove('hidden');
  }

  els.launcher.addEventListener('click', openChat);
  els.closeBtn.addEventListener('click', closeChat);
})();
