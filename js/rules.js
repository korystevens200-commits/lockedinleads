/**
 * rules.js — pure business logic shared by the chat widget and dashboard.
 * No IO here; persistence lives in api.js / server.py.
 */

const BUSINESS = {
  name: 'Sparkle & Shine Cleaning Co.',
  serviceAreas: ['Miami', 'Miami Beach', 'Coral Gables', 'Doral', 'Hialeah'],
  ownerName: 'Maria',
};

const PRICE_BASE = { studio: 90, '1br': 100, '2br': 130, '3br': 160, '4br+': 200 };
const TYPE_MULTIPLIER = { standard: 1, deep: 1.4, 'move-in-out': 1.6 };
const FREQUENCY_DISCOUNT = { 'one-time': 0, weekly: 0.2, biweekly: 0.15, monthly: 0.1 };

function getBusiness() {
  return BUSINESS;
}

function estimateQuote({ homeSize, cleaningType, frequency }) {
  const base = PRICE_BASE[homeSize] ?? 130;
  const withType = base * (TYPE_MULTIPLIER[cleaningType] ?? 1);
  const discount = FREQUENCY_DISCOUNT[frequency] ?? 0;
  return Math.round(withType * (1 - discount));
}

function inServiceArea(address) {
  if (!address) return false;
  const a = address.toLowerCase();
  return BUSINESS.serviceAreas.some((city) => a.includes(city.toLowerCase()));
}

/** Rule-based stand-in for an AI qualification model. */
function qualifyLead(lead) {
  if (!inServiceArea(lead.address)) {
    return { qualified: false, score: 'out-of-area', reason: 'Outside current service area' };
  }
  const hasCoreInfo = lead.name && lead.phone && lead.homeSize && lead.cleaningType && lead.preferredDate;
  if (!hasCoreInfo) {
    return { qualified: false, score: 'incomplete', reason: 'Missing required details' };
  }
  let score = 'warm';
  if (lead.frequency && lead.frequency !== 'one-time') score = 'hot';
  if (lead.cleaningType === 'move-in-out' && lead.frequency === 'one-time') score = 'warm';
  return { qualified: true, score, reason: null };
}

window.ALM_RULES = { getBusiness, estimateQuote, inServiceArea, qualifyLead };
