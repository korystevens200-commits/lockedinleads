/**
 * "Add lead" dialog — shared by the dashboard and the leads page.
 * Manual entry is the fastest path for a phone call the owner just took, so it
 * defaults to starting the assistant immediately.
 */
const LeadForm = (() => {
  const SOURCES = [
    ['manual', 'Manual entry'], ['phone_call', 'Phone call'], ['website_form', 'Website form'],
    ['facebook', 'Facebook lead ad'], ['instagram', 'Instagram lead ad'],
    ['google_ads', 'Google Ads'], ['google_business', 'Google Business'],
    ['crm', 'CRM'], ['other', 'Other'],
  ];

  function open(onCreated) {
    UI.modal({
      title: 'Add a lead',
      body: `
        <form id="leadForm" novalidate>
          <div class="field">
            <label for="lf-name">Name</label>
            <input class="input" id="lf-name" name="name" autocomplete="name" placeholder="Jenna Ortiz" />
          </div>
          <div class="field-row field-row-2">
            <div class="field">
              <label for="lf-phone">Phone</label>
              <input class="input" id="lf-phone" name="phone" type="tel" inputmode="tel"
                     autocomplete="tel" placeholder="(305) 555-0142" />
            </div>
            <div class="field">
              <label for="lf-email">Email</label>
              <input class="input" id="lf-email" name="email" type="email" inputmode="email"
                     autocomplete="email" placeholder="jenna@example.com" />
            </div>
          </div>
          <div class="field-row field-row-2">
            <div class="field">
              <label for="lf-service">Service requested</label>
              <input class="input" id="lf-service" name="service_requested" placeholder="Deep clean" />
            </div>
            <div class="field">
              <label for="lf-source">Where did it come from?</label>
              <select class="select" id="lf-source" name="source">
                ${SOURCES.map(([v, l]) => `<option value="${v}">${UI.esc(l)}</option>`).join('')}
              </select>
            </div>
          </div>
          <div class="field">
            <label for="lf-location">Location / area</label>
            <input class="input" id="lf-location" name="location" placeholder="Coral Gables" />
          </div>
          <div class="field">
            <label for="lf-notes">Notes</label>
            <textarea class="textarea" id="lf-notes" name="notes"
              placeholder="Anything they told you on the call…"></textarea>
          </div>
          <label class="checkbox mb-3">
            <input type="checkbox" name="start_ai" checked />
            <span><strong>Respond instantly</strong> — the assistant sends the first message and starts
            the follow-up sequence right away.</span>
          </label>
          <label class="checkbox">
            <input type="checkbox" name="consent" />
            <span>This person agreed to be contacted by text/email.</span>
          </label>
          <p class="field-error mt-3 hidden" id="lf-error"></p>
        </form>`,
      footer: `<button class="btn btn-ghost grow" data-close>Cancel</button>
               <button class="btn btn-primary grow" id="lf-save">Add lead</button>`,
      onOpen(el, close) {
        const form = el.querySelector('#leadForm');
        const error = el.querySelector('#lf-error');
        const save = el.querySelector('#lf-save');

        async function submit() {
          const values = UI.formValues(form);
          error.classList.add('hidden');
          if (!values.name && !values.phone && !values.email) {
            error.textContent = 'Add at least a name, phone number or email address.';
            error.classList.remove('hidden');
            return;
          }
          save.disabled = true;
          save.textContent = 'Adding…';
          try {
            const { lead } = await API.post('/api/leads', values);
            close();
            UI.toast('Lead added', values.start_ai ? 'The assistant is replying now.' : 'Saved without messaging.');
            if (onCreated) onCreated(lead);
          } catch (err) {
            save.disabled = false;
            save.textContent = 'Add lead';
            error.textContent = err.message;
            error.classList.remove('hidden');
            if (err.code === 'duplicate_lead' && err.lead_id) {
              error.insertAdjacentHTML('beforeend',
                ` <a class="accent-text" href="/app/leads.html?lead=${encodeURIComponent(err.lead_id)}">Open it</a>`);
            }
          }
        }
        save.addEventListener('click', submit);
        form.addEventListener('submit', (e) => { e.preventDefault(); submit(); });
      },
    });
  }

  return { open, SOURCES };
})();
