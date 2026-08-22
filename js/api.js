/**
 * api.js — thin fetch client for the Python backend (server.py).
 * All persistence, the follow-up sweep, and owner email notifications
 * live server-side now, so leads survive refreshes and are shared
 * between the customer chat widget and the owner dashboard.
 */

const API_BASE = '/api';

async function req(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${options.method || 'GET'} ${path} failed: ${res.status} ${body}`);
  }
  return res.json();
}

function listLeads() {
  return req('/leads');
}

function getLead(id) {
  return req(`/leads/${id}`);
}

function createLead(partial) {
  return req('/leads', { method: 'POST', body: JSON.stringify(partial) });
}

function updateLead(id, patch) {
  return req(`/leads/${id}`, { method: 'PATCH', body: JSON.stringify(patch) });
}

function appendTranscript(id, entry) {
  return req(`/leads/${id}/transcript`, { method: 'POST', body: JSON.stringify(entry) });
}

function sendManualFollowUp(id) {
  return req(`/leads/${id}/followup`, { method: 'POST' });
}

function stats(leads) {
  const total = leads.length;
  const qualified = leads.filter((l) => ['qualified', 'booked', 'needs-follow-up'].includes(l.status)).length;
  const booked = leads.filter((l) => l.status === 'booked').length;
  const needsFollowUp = leads.filter((l) => l.status === 'needs-follow-up').length;
  const conversion = total ? Math.round((booked / total) * 100) : 0;
  return { total, qualified, booked, needsFollowUp, conversion };
}

window.ALM = {
  ...window.ALM_RULES,
  listLeads, getLead, createLead, updateLead, appendTranscript, sendManualFollowUp, stats,
};
