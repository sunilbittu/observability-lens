'use strict';

// Input cleaning shared by every public call. Nothing here throws.

const MAX_ATTRIBUTES = 32;
const MAX_STRING = 1024;
const NAME = /^[A-Za-z][A-Za-z0-9_.\-/]{0,199}$/;

// Attribute keys that hold identifiers or codes even when the value is a number.
// A numeric attribute whose key matches is recorded on the event but never summed.
const ID_LIKE = /(^|[._-])(id|ids|uuid|guid|key|code|number|num|no|zip|postcode|phone|port|pid|version|year|status|index|seq|timestamp|time|ts)$/i;

function validName(name) {
  return typeof name === 'string' && NAME.test(name);
}

function attributes(input) {
  const out = {};
  if (input === null || typeof input !== 'object' || Array.isArray(input)) return out;
  let kept = 0;
  for (const key of Object.keys(input)) {
    if (kept >= MAX_ATTRIBUTES) break;
    const value = input[key];
    if (typeof value === 'string') out[key] = value.length > MAX_STRING ? value.slice(0, MAX_STRING) : value;
    else if (typeof value === 'number' && Number.isFinite(value)) out[key] = value;
    else if (typeof value === 'boolean') out[key] = value;
    else continue;                      // objects, arrays, functions, NaN and undefined are dropped
    kept += 1;
  }
  return out;
}

// Which attributes of an event are measurements that can be added up.
function summable(attrs) {
  const out = [];
  for (const [key, value] of Object.entries(attrs)) {
    if (typeof value === 'number' && value >= 0 && !ID_LIKE.test(key)) out.push([key, value]);
  }
  return out;
}

module.exports = { validName, attributes, summable, ID_LIKE };
