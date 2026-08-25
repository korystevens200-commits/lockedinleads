/**
 * Settings form sections, shared by the Automation Center and the onboarding
 * wizard so both edit exactly the same configuration.
 *
 * Each section exposes render(config) -> HTML and read(root) -> patch.
 */
const SettingsForms = (() => {
  const DAYS = [['mon', 'Monday'], ['tue', 'Tuesday'], ['wed', 'Wednesday'], ['thu', 'Thursday'],
                ['fri', 'Friday'], ['sat', 'Saturday'], ['sun', 'Sunday']];
  const TIMEZONES = [
    'America/New_York', 'America/Chicago', 'America/Denver', 'America/Phoenix',
    'America/Los_Angeles', 'America/Anchorage', 'Pacific/Honolulu', 'America/Toronto',
    'Europe/London', 'Australia/Sydney',
  ];
  const INDUSTRIES = [
    ['cleaning', 'Cleaning'], ['hvac', 'HVAC'], ['roofing', 'Roofing'], ['plumbing', 'Plumbing'],
    ['electrical', 'Electrical'], ['landscaping', 'Landscaping'], ['pest_control', 'Pest control'],
    ['med_spa', 'Med spa'], ['dental', 'Dental'], ['auto', 'Auto services'], ['other', 'Other'],
  ];
  const TONES = [
    ['friendly_professional', 'Friendly & professional'],
    ['warm_casual', 'Warm & casual'],
    ['direct_efficient', 'Direct & efficient'],
  ];

  const esc = UI.esc;

  function field(label, control, hint) {
    return `<div class="field"><label>${esc(label)}</label>${control}
      ${hint ? `<div class="field-hint">${hint}</div>` : ''}</div>`;
  }

  function input(name, value, opts = {}) {
    return `<input class="input" name="${name}" value="${esc(value ?? '')}"
      type="${opts.type || 'text'}" ${opts.inputmode ? `inputmode="${opts.inputmode}"` : ''}
      ${opts.min !== undefined ? `min="${opts.min}"` : ''} ${opts.max !== undefined ? `max="${opts.max}"` : ''}
      ${opts.placeholder ? `placeholder="${esc(opts.placeholder)}"` : ''} />`;
  }

  function select(name, value, options) {
    return `<select class="select" name="${name}">${options.map(([v, l]) =>
      `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  }

  function toggle(name, checked, title, sub) {
    return `<label class="switch mb-4" style="width:100%">
      <input type="checkbox" name="${name}" ${checked ? 'checked' : ''} />
      <span class="switch-track"></span>
      <span class="grow"><span class="switch-label">${esc(title)}</span>
        ${sub ? `<div class="field-hint">${esc(sub)}</div>` : ''}</span>
    </label>`;
  }

  // ------------------------------------------------------------- business
  const business = {
    title: 'Business information',
    blurb: 'The assistant introduces itself with this, and uses your timezone for every time it quotes.',
    render(cfg) {
      const b = cfg.business;
      return `<div data-section="business">
        ${field('Business name', input('name', b.name, { placeholder: 'Sparkle & Shine Cleaning Co.' }))}
        <div class="field-row field-row-2">
          ${field('Industry', select('industry', b.industry, INDUSTRIES))}
          ${field('Timezone', select('timezone', b.timezone,
            [...new Set([b.timezone, ...TIMEZONES])].map((t) => [t, t.replace('_', ' ')])))}
        </div>
        <div class="field-row field-row-2">
          ${field('Owner / contact name', input('contact_name', b.contact_name))}
          ${field('Business phone', input('contact_phone', b.contact_phone, { type: 'tel', inputmode: 'tel' }))}
        </div>
        <div class="field-row field-row-2">
          ${field('Notification email', input('contact_email', b.contact_email, { type: 'email', inputmode: 'email' }),
            'Where new-lead and booking alerts are sent.')}
          ${field('Website', input('website', b.website, { placeholder: 'https://' }))}
        </div>
        ${field('Address', input('address', b.address))}
      </div>`;
    },
    read(root) {
      const el = root.querySelector('[data-section="business"]');
      if (!el) return {};
      return { business: UI.formValues(el) };
    },
  };

  // ------------------------------------------------------------- services
  const services = {
    title: 'Services offered',
    blurb: 'The assistant may only mention these — and may only quote a price if you write one here.',
    render(cfg) {
      const list = cfg.services.length ? cfg.services : [{ name: '', description: '', price_note: '', avg_value: '', duration_minutes: 120 }];
      return `<div data-section="services">
        <div id="serviceRows">${list.map(serviceRow).join('')}</div>
        <button class="btn btn-ghost btn-sm" data-add-service>+ Add service</button>
      </div>`;
    },
    read(root) {
      const el = root.querySelector('[data-section="services"]');
      if (!el) return {};
      const items = [...el.querySelectorAll('.repeat-row')].map((row) => ({
        name: row.querySelector('[data-f="name"]').value.trim(),
        description: row.querySelector('[data-f="description"]').value.trim(),
        price_note: row.querySelector('[data-f="price_note"]').value.trim(),
        avg_value: row.querySelector('[data-f="avg_value"]').value,
        duration_minutes: row.querySelector('[data-f="duration_minutes"]').value,
      })).filter((s) => s.name);
      return { services: items };
    },
    wire(root) {
      const el = root.querySelector('[data-section="services"]');
      if (!el) return;
      el.querySelector('[data-add-service]')?.addEventListener('click', () => {
        el.querySelector('#serviceRows').insertAdjacentHTML('beforeend',
          serviceRow({ name: '', description: '', price_note: '', avg_value: '', duration_minutes: 120 }));
        bindRemove(el);
      });
      bindRemove(el);
    },
  };

  function serviceRow(s) {
    return `<div class="repeat-row">
      <div class="repeat-head">
        <span class="label">Service</span>
        <button class="btn btn-sm btn-quiet" data-remove aria-label="Remove service">${UI.icon('trash', 15)}</button>
      </div>
      <input class="input" data-f="name" value="${esc(s.name || '')}" placeholder="Deep Clean" />
      <input class="input" data-f="description" value="${esc(s.description || '')}"
             placeholder="What's included — the assistant repeats this" />
      <input class="input" data-f="price_note" value="${esc(s.price_note || '')}"
             placeholder="Pricing the assistant may quote, e.g. From $220 for a 3-bedroom" />
      <div class="field-row field-row-2">
        <div class="field" style="margin:0">
          <label>Average job value ($)</label>
          <input class="input" data-f="avg_value" type="number" min="0" step="10" inputmode="decimal"
                 value="${Number(s.avg_value || 0)}" />
        </div>
        <div class="field" style="margin:0">
          <label>Typical duration (minutes)</label>
          <input class="input" data-f="duration_minutes" type="number" min="15" max="960" step="15"
                 inputmode="numeric" value="${Number(s.duration_minutes || 120)}" />
        </div>
      </div>
    </div>`;
  }

  function bindRemove(scope) {
    scope.querySelectorAll('[data-remove]').forEach((b) => {
      b.onclick = () => {
        const rows = scope.querySelectorAll('.repeat-row');
        if (rows.length <= 1) { UI.toast('Keep at least one'); return; }
        b.closest('.repeat-row').remove();
      };
    });
  }

  // ---------------------------------------------------------------- areas
  const areas = {
    title: 'Service areas',
    blurb: 'Anything outside these is flagged rather than promised. Cities, neighbourhoods or ZIP codes.',
    render(cfg) {
      return `<div data-section="areas">
        <div class="field">
          <label for="areaInput">Add an area</label>
          <div class="row gap-2">
            <input class="input grow" id="areaInput" placeholder="Coral Gables, 33134, Miami Beach…" />
            <button class="btn btn-ghost" data-add-area>Add</button>
          </div>
          <div class="field-hint">Type or paste several separated by commas, then press Enter.</div>
        </div>
        <div class="chip-row" id="areaChips">${cfg.areas.map((a) => areaChip(a.name)).join('')}</div>
      </div>`;
    },
    read(root) {
      const el = root.querySelector('[data-section="areas"]');
      if (!el) return {};
      return { areas: [...el.querySelectorAll('#areaChips [data-area]')].map((c) => c.dataset.area) };
    },
    wire(root) {
      const el = root.querySelector('[data-section="areas"]');
      if (!el) return;
      const input = el.querySelector('#areaInput');
      const chips = el.querySelector('#areaChips');
      const add = () => {
        const existing = new Set([...chips.querySelectorAll('[data-area]')]
          .map((c) => c.dataset.area.toLowerCase()));
        input.value.split(',').map((v) => v.trim()).filter(Boolean).forEach((name) => {
          if (existing.has(name.toLowerCase())) return;
          existing.add(name.toLowerCase());
          chips.insertAdjacentHTML('beforeend', areaChip(name));
        });
        input.value = '';
        bindChips(chips);
      };
      el.querySelector('[data-add-area]').addEventListener('click', add);
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
      bindChips(chips);
    },
  };

  function areaChip(name) {
    return `<span class="chip" data-area="${esc(name)}">${esc(name)}
      <button class="chip-remove" data-remove-chip aria-label="Remove ${esc(name)}">&times;</button></span>`;
  }

  function bindChips(scope) {
    scope.querySelectorAll('[data-remove-chip]').forEach((b) => {
      b.onclick = (e) => { e.stopPropagation(); b.closest('[data-area]').remove(); };
    });
  }

  // ------------------------------------------------------------ questions
  const questions = {
    title: 'Qualification questions',
    blurb: 'What the assistant needs answered before it offers a time. One at a time, in this order.',
    render(cfg) {
      const list = cfg.questions.length ? cfg.questions
        : [{ field_key: 'service_needed', prompt: 'What service are you looking for?', answer_type: 'text', required: true, options: [] }];
      return `<div data-section="questions">
        <div id="questionRows">${list.map(questionRow).join('')}</div>
        <button class="btn btn-ghost btn-sm" data-add-question>+ Add question</button>
      </div>`;
    },
    read(root) {
      const el = root.querySelector('[data-section="questions"]');
      if (!el) return {};
      const items = [...el.querySelectorAll('.repeat-row')].map((row) => ({
        field_key: row.querySelector('[data-f="field_key"]').value.trim(),
        prompt: row.querySelector('[data-f="prompt"]').value.trim(),
        answer_type: row.querySelector('[data-f="answer_type"]').value,
        options: row.querySelector('[data-f="options"]').value,
        required: row.querySelector('[data-f="required"]').checked,
      })).filter((q) => q.prompt);
      return { questions: items };
    },
    wire(root) {
      const el = root.querySelector('[data-section="questions"]');
      if (!el) return;
      el.querySelector('[data-add-question]')?.addEventListener('click', () => {
        el.querySelector('#questionRows').insertAdjacentHTML('beforeend',
          questionRow({ field_key: '', prompt: '', answer_type: 'text', required: true, options: [] }));
        bindRemove(el);
      });
      bindRemove(el);
    },
  };

  function questionRow(q) {
    const types = [['text', 'Free text'], ['choice', 'Pick from options'], ['yes_no', 'Yes / no'], ['date', 'Date']];
    return `<div class="repeat-row">
      <div class="repeat-head">
        <span class="label">Question</span>
        <button class="btn btn-sm btn-quiet" data-remove aria-label="Remove question">${UI.icon('trash', 15)}</button>
      </div>
      <input class="input" data-f="prompt" value="${esc(q.prompt || '')}"
             placeholder="How many bedrooms and bathrooms?" />
      <div class="field-row field-row-2">
        <div class="field" style="margin:0">
          <label>Save answer as</label>
          <input class="input" data-f="field_key" value="${esc(q.field_key || '')}" placeholder="home_size" />
        </div>
        <div class="field" style="margin:0">
          <label>Answer type</label>
          <select class="select" data-f="answer_type">${types.map(([v, l]) =>
            `<option value="${v}"${v === q.answer_type ? ' selected' : ''}>${l}</option>`).join('')}</select>
        </div>
      </div>
      <input class="input" data-f="options" value="${esc((q.options || []).join(', '))}"
             placeholder="Options, comma separated (only for 'Pick from options')" />
      <label class="checkbox"><input type="checkbox" data-f="required" ${q.required ? 'checked' : ''} />
        <span>Required before the assistant offers an appointment</span></label>
    </div>`;
  }

  // ------------------------------------------------------------------- ai
  const ai = {
    title: 'AI behaviour',
    blurb: 'The assistant can never invent prices, availability, policies or services — it only uses what you configure here.',
    render(cfg) {
      const a = cfg.settings.ai;
      return `<div data-section="ai">
        <div class="field-row field-row-2">
          ${field('Assistant name', input('assistant_name', a.assistant_name, { placeholder: 'Aria' }))}
          ${field('Tone', select('tone', a.tone, TONES))}
        </div>
        ${field('Custom opening message (optional)',
          `<textarea class="textarea" name="custom_greeting" placeholder="Leave blank to let the assistant write it. Use {name} and {business}.">${esc(a.custom_greeting || '')}</textarea>`)}
        ${field('Extra instructions (optional)',
          `<textarea class="textarea" name="extra_instructions" placeholder="e.g. Always mention we're insured and bonded. Never promise same-day service.">${esc(a.extra_instructions || '')}</textarea>`,
          'Applied on top of the safety rules — it cannot be used to let the assistant invent prices.')}
        ${toggle('auto_respond', a.auto_respond, 'Respond to new leads automatically',
          'Turn off to review every lead before anything is sent.')}
        ${toggle('respond_outside_hours', a.respond_outside_hours, 'Reply outside business hours',
          'Recommended — replying in minutes is what turns leads into appointments.')}
        ${field('Hand to a human when the customer says…',
          input('handoff_keywords', (a.handoff_keywords || []).join(', '),
            { placeholder: 'manager, complaint, refund' }),
          'Comma separated. The assistant stops and alerts you instead of answering.')}
        ${field('Maximum assistant messages per lead',
          input('max_ai_messages', a.max_ai_messages, { type: 'number', min: 3, max: 100, inputmode: 'numeric' }),
          'A safety stop — after this the conversation is handed to you.')}
      </div>`;
    },
    read(root) {
      const el = root.querySelector('[data-section="ai"]');
      if (!el) return {};
      const v = UI.formValues(el);
      v.handoff_keywords = String(v.handoff_keywords || '').split(',').map((s) => s.trim()).filter(Boolean);
      return { settings: { ai: v } };
    },
  };

  // ---------------------------------------------------------------- hours
  const hours = {
    title: 'Business hours',
    blurb: 'Used for follow-up timing and for anything the assistant says about when you are open.',
    render(cfg) {
      return `<div data-section="hours">${DAYS.map(([key, label]) =>
        dayRow('hours', key, label, cfg.settings.hours.days[key] || [])).join('')}</div>`;
    },
    read(root) { return readDays(root, 'hours', 'hours'); },
    wire(root) { wireDays(root, 'hours'); },
  };

  const booking = {
    title: 'Booking availability',
    blurb: 'The only times the assistant can offer. Booked slots are removed automatically.',
    render(cfg) {
      const b = cfg.settings.booking;
      return `<div data-section="booking">
        ${toggle('enabled', b.enabled, 'Let the assistant book appointments',
          'Turn off and it will collect details and hand qualified leads to you instead.')}
        <div class="field-row field-row-2">
          ${field('Appointment length (minutes)', input('slot_minutes', b.slot_minutes, { type: 'number', min: 15, max: 480, inputmode: 'numeric' }))}
          ${field('Buffer between jobs (minutes)', input('buffer_minutes', b.buffer_minutes, { type: 'number', min: 0, max: 240, inputmode: 'numeric' }))}
        </div>
        <div class="field-row field-row-3">
          ${field('Earliest booking (hours from now)', input('lead_time_hours', b.lead_time_hours, { type: 'number', min: 0, max: 168, inputmode: 'numeric' }))}
          ${field('Max jobs per day', input('max_per_day', b.max_per_day, { type: 'number', min: 1, max: 50, inputmode: 'numeric' }))}
          ${field('Book up to (days ahead)', input('days_ahead', b.days_ahead, { type: 'number', min: 1, max: 90, inputmode: 'numeric' }))}
        </div>
        <div class="label mt-5 mb-3">Available hours for jobs</div>
        ${DAYS.map(([key, label]) => dayRow('booking', key, label, b.availability[key] || [])).join('')}
      </div>`;
    },
    read(root) {
      const el = root.querySelector('[data-section="booking"]');
      if (!el) return {};
      const values = UI.formValues(el);
      const days = readDays(root, 'booking', 'booking').settings?.booking?.days || {};
      return { settings: { booking: { ...values, availability: days } } };
    },
    wire(root) { wireDays(root, 'booking'); },
  };

  function dayRow(group, key, label, windows) {
    const w = windows[0] || null;
    return `<div class="hours-day" data-day-group="${group}" data-day="${key}">
      <div class="hours-name">${esc(label)}</div>
      <div class="hours-inputs">
        <label class="switch">
          <input type="checkbox" data-open ${w ? 'checked' : ''} aria-label="${esc(label)} open" />
          <span class="switch-track"></span>
        </label>
        <input class="input" type="time" data-start value="${esc(w ? w.start : '09:00')}"
               ${w ? '' : 'disabled'} aria-label="${esc(label)} opening time" />
        <span class="dim">to</span>
        <input class="input" type="time" data-end value="${esc(w ? w.end : '17:00')}"
               ${w ? '' : 'disabled'} aria-label="${esc(label)} closing time" />
        <span class="hours-closed${w ? ' hidden' : ''}">Closed</span>
      </div>
    </div>`;
  }

  function wireDays(root, group) {
    root.querySelectorAll(`[data-day-group="${group}"]`).forEach((row) => {
      const box = row.querySelector('[data-open]');
      box.addEventListener('change', () => {
        row.querySelectorAll('[data-start],[data-end]').forEach((i) => { i.disabled = !box.checked; });
        row.querySelector('.hours-closed').classList.toggle('hidden', box.checked);
      });
    });
  }

  function readDays(root, group, sectionKey) {
    const days = {};
    root.querySelectorAll(`[data-day-group="${group}"]`).forEach((row) => {
      const open = row.querySelector('[data-open]').checked;
      const start = row.querySelector('[data-start]').value;
      const end = row.querySelector('[data-end]').value;
      days[row.dataset.day] = open && start && end && start < end ? [{ start, end }] : [];
    });
    return { settings: { [sectionKey]: { days } } };
  }

  // ----------------------------------------------------------- follow-ups
  const followups = {
    title: 'Follow-up timing',
    blurb: 'Follow-ups stop the moment a lead replies, books, opts out or is closed — nobody gets spammed.',
    render(cfg) {
      const f = cfg.settings.followups;
      return `<div data-section="followups">
        ${toggle('enabled', f.enabled, 'Follow up automatically',
          'Most bookings come from a follow-up, not the first message.')}
        ${field('Send follow-ups after (minutes from the last message)',
          input('delays_minutes', f.delays_minutes.join(', '), { placeholder: '15, 240, 1440, 4320' }),
          'Comma separated. 15, 240, 1440, 4320 = 15 minutes, 4 hours, 1 day, 3 days.')}
        ${field('Maximum follow-ups', input('max_attempts', f.max_attempts,
          { type: 'number', min: 0, max: 10, inputmode: 'numeric' }),
          'After the last one the lead is marked "No response".')}
        ${toggle('only_business_hours', f.only_business_hours, 'Only send during business hours',
          'A follow-up due at 2am waits until you open.')}
      </div>`;
    },
    read(root) {
      const el = root.querySelector('[data-section="followups"]');
      if (!el) return {};
      return { settings: { followups: UI.formValues(el) } };
    },
  };

  // -------------------------------------------------------- notifications
  const notifications = {
    title: 'Notifications',
    blurb: 'How you hear about what the assistant is doing.',
    render(cfg) {
      const n = cfg.settings.notifications;
      const ev = n.events;
      return `<div data-section="notifications">
        ${toggle('email_enabled', n.email_enabled, 'Email me', '')}
        ${field('Email address', input('email_to', n.email_to, { type: 'email', inputmode: 'email' }),
          'Leave blank to use your business contact email.')}
        ${toggle('sms_enabled', n.sms_enabled, 'Text me', 'Requires SMS to be configured on the server.')}
        ${field('Mobile number', input('sms_to', n.sms_to, { type: 'tel', inputmode: 'tel' }))}
        <div class="label mt-5 mb-3">Tell me when…</div>
        ${toggle('ev_new_lead', ev.new_lead, 'A new lead arrives', '')}
        ${toggle('ev_qualified', ev.qualified, 'A lead is qualified', '')}
        ${toggle('ev_booked', ev.booked, 'An appointment is booked', '')}
        ${toggle('ev_handoff', ev.handoff, 'A conversation needs me', '')}
      </div>`;
    },
    read(root) {
      const el = root.querySelector('[data-section="notifications"]');
      if (!el) return {};
      const v = UI.formValues(el);
      return { settings: { notifications: {
        email_enabled: v.email_enabled, email_to: v.email_to,
        sms_enabled: v.sms_enabled, sms_to: v.sms_to,
        events: { new_lead: v.ev_new_lead, qualified: v.ev_qualified,
                  booked: v.ev_booked, handoff: v.ev_handoff },
      } } };
    },
  };

  /** Deep-merge section patches so several sections can touch settings.* */
  function mergePatches(patches) {
    const out = {};
    patches.forEach((patch) => {
      Object.entries(patch || {}).forEach(([key, value]) => {
        if (key === 'settings') {
          out.settings = out.settings || {};
          Object.entries(value).forEach(([section, sectionValue]) => {
            out.settings[section] = { ...(out.settings[section] || {}), ...sectionValue };
          });
        } else {
          out[key] = value;
        }
      });
    });
    return out;
  }

  const SECTIONS = { business, services, areas, questions, ai, hours, booking, followups, notifications };

  function renderSection(key, cfg) {
    const section = SECTIONS[key];
    return `<div class="card">
      <div class="card-title mb-2">${esc(section.title)}</div>
      <p class="small muted mb-5">${esc(section.blurb)}</p>
      ${section.render(cfg)}
    </div>`;
  }

  function wireSection(key, root) {
    SECTIONS[key].wire?.(root);
  }

  function readSections(keys, root) {
    return mergePatches(keys.map((k) => SECTIONS[k].read(root)));
  }

  return { SECTIONS, renderSection, wireSection, readSections, mergePatches, DAYS };
})();
