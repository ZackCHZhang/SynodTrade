// Lists English UI strings that have no entry in src/i18n/zh.ts, and zh.ts keys no code uses.
// Covers literal t('...') / withKey('...') calls plus the lookup tables whose values are translated via t(variable).
// Usage: npm run i18n:check   (exit code 1 when a translation is missing)

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = new URL('../src/', import.meta.url).pathname;

// Tables translated indirectly. 'all' = every string value, 'props' = only label/desc/section values,
// 'second' = the second element of each [key, text] tuple.
const TABLES = [
  ['lib/labels.ts', 'L', 'all'],
  ['lib/labels.ts', 'STAGE_INFO', 'props'],
  ['lib/labels.ts', 'ROLE_LABEL', 'all'],
  ['App.tsx', 'NAV', 'props'],
  ['components/StatusChip.tsx', 'STATUS', 'props'],
  ['pages/AccountSyncPage.tsx', 'SYNC_STATUS', 'props'],
  ['pages/AccountSyncPage.tsx', 'TRIGGER', 'all'],
  ['pages/ConfigsPage.tsx', 'DESCRIPTIONS', 'all'],
  ['pages/DataPage.tsx', 'TABLE_LABEL', 'all'],
  ['pages/DataPage.tsx', 'OPS', 'second'],
];
// Config kind labels come from the backend (packages/webapi/src/quant_webapi/catalog.py).
const BACKEND = ['Pipelines', 'Agent', 'Prompt templates', 'Accounts', 'Risk rules', 'LLM providers', 'Schedules', 'Account sync'];

const STR = /'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"/g;
const unescape = (s) => s.replace(/\\(.)/g, '$1');

function files(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.tsx?$/.test(f) ? [p] : [];
  });
}

/** The source of `const NAME = {...}` or `[...]`, from the declaration to its closing line. */
function block(text, name) {
  const m = text.match(new RegExp(`const ${name}\\b[^=]*=\\s*([\\[{])`));
  if (!m) throw new Error(`table ${name} not found`);
  const close = m[1] === '{' ? '}' : ']';
  let depth = 0;
  for (let i = m.index + m[0].length - 1; i < text.length; i++) {
    if (text[i] === m[1]) depth++;
    else if (text[i] === close && --depth === 0) return text.slice(m.index + m[0].length, i);
  }
  throw new Error(`table ${name} is not closed`);
}

/** String literals in the first argument of the call whose `(` is at `i`, skipping operands of comparisons. */
function tArgs(text, i) {
  let depth = 0;
  let end = i;
  for (; end < text.length; end++) {
    const c = text[end];
    if (c === "'" || c === '"' || c === '`') {
      end = text.indexOf(c, end + 1); // literals in t() args never contain their own quote unescaped
      while (text[end - 1] === '\\') end = text.indexOf(c, end + 1);
    } else if (c === '(') depth++;
    else if (c === ')' && --depth === 0) break;
    else if (c === ',' && depth === 1) break;
  }
  const arg = text.slice(i, end);
  const out = [];
  for (const m of arg.matchAll(STR)) {
    if (/[!=]==?\s*$/.test(arg.slice(0, m.index))) continue;
    out.push(unescape(m[1] ?? m[2]));
  }
  return out;
}

const used = new Map(); // text -> first location
const add = (s, where) => {
  if (/[a-z]/i.test(s) && !used.has(s)) used.set(s, where);
};

for (const file of files(SRC)) {
  if (file.endsWith('i18n/zh.ts')) continue;
  const text = readFileSync(file, 'utf8');
  const rel = relative(SRC, file);
  for (const m of text.matchAll(/(?<![\w.])(?:t|withKey)\(/g)) tArgs(text, m.index + m[0].length - 1).forEach((s) => add(s, rel));
}
for (const [rel, name, mode] of TABLES) {
  const body = block(readFileSync(join(SRC, rel), 'utf8'), name);
  if (mode === 'second') {
    for (const m of body.matchAll(/\[\s*'[^']*',\s*'((?:[^'\\]|\\.)*)'\s*\]/g)) add(unescape(m[1]), `${rel} ${name}`);
  } else if (mode === 'all') {
    for (const line of body.split('\n')) {
      const value = line.replace(/^\s*(\w+|'[^']*'):\s*/, ''); // drop the key
      for (const m of value.matchAll(STR)) add(unescape(m[1] ?? m[2]), `${rel} ${name}`);
    }
  } else {
    for (const m of body.matchAll(/\b(?:label|desc|section):\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")/g)) add(unescape(m[1] ?? m[2]), `${rel} ${name}`);
  }
}
BACKEND.forEach((s) => add(s, 'backend config kinds'));

const zhText = readFileSync(join(SRC, 'i18n/zh.ts'), 'utf8');
const zh = new Set();
for (const line of zhText.split('\n')) {
  const m = line.match(/^\s*('((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"):/);
  if (m) zh.add(unescape(m[2] ?? m[3]));
}

const missing = [...used].filter(([s]) => !zh.has(s));
const unused = [...zh].filter((s) => !used.has(s));
for (const [s, where] of missing) console.log(`missing  ${JSON.stringify(s)}  (${where})`);
for (const s of unused) console.log(`unused   ${JSON.stringify(s)}`);
console.log(`${used.size} strings, ${missing.length} missing, ${unused.length} unused`);
process.exit(missing.length ? 1 : 0);
