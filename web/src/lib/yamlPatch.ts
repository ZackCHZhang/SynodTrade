// Minimal-diff YAML editing: turn a change of the parsed data into text edits of the original
// file, so untouched lines keep their exact formatting (aligned comments, `[a, b]` spacing,
// multi-line flow maps). Returns null when a change is not supported; the caller then falls
// back to re-serialising the document. Every result is re-parsed and compared with the wanted
// data, so a patch can never silently produce different data.

import { isMap, isScalar, isSeq, parse, parseDocument, stringify, type Node, type Pair, type Scalar, type YAMLMap, type YAMLSeq } from 'yaml';

interface Edit {
  start: number;
  end: number;
  text: string;
}

class Unsupported extends Error {}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a === 'number' && typeof b === 'number') return Number.isNaN(a) && Number.isNaN(b);
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => deepEqual(x, b[i]));
  if (isObj(a) && isObj(b)) {
    const ka = Object.keys(a).filter((k) => a[k] !== undefined);
    const kb = Object.keys(b).filter((k) => b[k] !== undefined);
    return ka.length === kb.length && ka.every((k) => k in b && deepEqual(a[k], b[k]));
  }
  return false;
}

// ------------------------------------------------------------------ text helpers

function lineStart(text: string, pos: number): number {
  return text.lastIndexOf('\n', pos - 1) + 1;
}

/** Position just after the line containing pos-1 (i.e. after the node ending at pos). */
function lineEndAfter(text: string, pos: number): number {
  if (pos > 0 && text[pos - 1] === '\n') return pos;
  const nl = text.indexOf('\n', pos);
  return nl < 0 ? text.length : nl + 1;
}

function column(text: string, pos: number): number {
  return pos - lineStart(text, pos);
}

function eol(text: string): string {
  return text.includes('\r\n') ? '\r\n' : '\n';
}

// ------------------------------------------------------------------ serialisation

function needsQuotes(s: string, inFlow: boolean): boolean {
  if (s === '' || s !== s.trim() || /[\n\r\t]/.test(s)) return true;
  if (/^[-?:,[\]{}#&*!|>'"%@`]/.test(s) || /: |\s#/.test(s) || s.endsWith(':')) return true;
  if (inFlow && /[,[\]{}]/.test(s)) return true;
  try {
    return parse(s) !== s; // e.g. "123", "true", "null" would change type
  } catch {
    return true;
  }
}

function scalarText(v: unknown, inFlow: boolean, original?: Scalar): string {
  if (v === null) return 'null';
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (typeof v !== 'string') throw new Unsupported('not a scalar');
  if (original?.type === 'QUOTE_SINGLE' && !/[\n\r]/.test(v)) return `'${v.replace(/'/g, "''")}'`;
  if (original?.type === 'QUOTE_DOUBLE' || needsQuotes(v, inFlow)) return JSON.stringify(v);
  return v;
}

/** One-line flow style matching the repo's configs: `[a, b]` and `{ k: v }`. */
function flowText(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(flowText).join(', ')}]`;
  if (isObj(v)) {
    const parts = Object.entries(v)
      .filter(([, x]) => x !== undefined)
      .map(([k, x]) => `${scalarText(k, true)}: ${flowText(x)}`);
    return parts.length ? `{ ${parts.join(', ')} }` : '{}';
  }
  return scalarText(v, true);
}

const isEmptyCollection = (v: unknown) => (Array.isArray(v) || isObj(v)) && Object.keys(v).length === 0;

const isScalarValue = (v: unknown) => v === null || ['string', 'number', 'boolean'].includes(typeof v);

/** Block YAML for new content, every line prefixed with `indent` spaces. */
function blockText(value: unknown, indent: number, nl: string): string {
  const pad = ' '.repeat(indent);
  return stringify(value, { lineWidth: 0, minContentWidth: 0, indentSeq: true })
    .replace(/\n$/, '')
    .split('\n')
    .map((l) => pad + l)
    .join(nl) + nl;
}

function pairText(key: string, value: unknown, indent: number, nl: string): string {
  const pad = ' '.repeat(indent);
  const k = scalarText(key, false);
  if (isScalarValue(value)) return `${pad}${k}: ${scalarText(value, false)}${nl}`;
  if (Array.isArray(value) && value.every(isScalarValue)) return `${pad}${k}: ${flowText(value)}${nl}`;
  if ((Array.isArray(value) || isObj(value)) && Object.keys(value).length === 0) return `${pad}${k}: ${flowText(value)}${nl}`;
  return `${pad}${k}:${nl}${blockText(value, indent + 2, nl)}`;
}

// ------------------------------------------------------------------ diff

class Patcher {
  edits: Edit[] = [];
  private text: string;
  private nl: string;
  constructor(text: string, nl: string) {
    this.text = text;
    this.nl = nl;
  }

  replace(node: Node, text: string) {
    const r = node.range;
    if (!r) throw new Unsupported('no range');
    this.edits.push({ start: r[0], end: r[1], text });
  }

  node(node: unknown, value: unknown, inFlow: boolean): void {
    if (isScalar(node)) return this.scalar(node, value, inFlow);
    if (isMap(node)) return this.map(node, value, inFlow);
    if (isSeq(node)) return this.seq(node, value, inFlow);
    throw new Unsupported('alias or empty node');
  }

  scalar(node: Scalar, value: unknown, inFlow: boolean) {
    if (deepEqual(node.value, value)) return;
    if (node.type === 'BLOCK_LITERAL' || node.type === 'BLOCK_FOLDED') return this.block(node, value);
    if (!isScalarValue(value)) {
      if (inFlow) return this.replace(node, flowText(value));
      throw new Unsupported('scalar -> collection');
    }
    this.replace(node, scalarText(value, inFlow, node));
  }

  /** Rewrite a `|` / `>` block scalar in place, keeping its indentation. */
  block(node: Scalar, value: unknown) {
    if (typeof value !== 'string' || value === '' || /^[ \t]/.test(value) || /\n\n$/.test(value) || value.includes('\r')) {
      throw new Unsupported('block scalar value');
    }
    const r = node.range!;
    const headerEnd = this.text.indexOf('\n', r[0]);
    if (headerEnd < 0) throw new Unsupported('block header');
    const body = this.text.slice(headerEnd + 1, r[1]);
    const indent = /^( +)\S/m.exec(body)?.[1].length;
    if (!indent) throw new Unsupported('block indent');
    const keep = value.endsWith('\n');
    const content = keep ? value.slice(0, -1) : value;
    // A single line can stay folded (`>-`); anything else becomes a literal block.
    const header = node.type === 'BLOCK_FOLDED' && !content.includes('\n') ? (keep ? '>' : '>-') : keep ? '|' : '|-';
    const pad = ' '.repeat(indent);
    let raw = content.split('\n');
    if (header.startsWith('>') && !content.includes('  ')) {
      // Folded: a line break between words reads as one space, so wrapping is lossless.
      const width = Math.max(60, 96 - indent);
      raw = [];
      let line = '';
      for (const word of content.split(' ')) {
        if (line && line.length + 1 + word.length > width) {
          raw.push(line);
          line = word;
        } else line = line ? `${line} ${word}` : word;
      }
      raw.push(line);
    }
    const lines = raw.map((l) => (l ? pad + l : ''));
    const end = lineEndAfter(this.text, r[1]);
    this.edits.push({ start: r[0], end, text: header + this.nl + lines.join(this.nl) + this.nl });
  }

  map(node: YAMLMap, value: unknown, inFlow: boolean) {
    if (!isObj(value)) throw new Unsupported('map -> non-map');
    if (deepEqual(node.toJSON(), value)) return;
    const pairs = node.items as Pair[];
    const keyOf = (p: Pair) => (isScalar(p.key) ? String(p.key.value) : String(p.key));
    const keys = new Set(pairs.map(keyOf));
    const wanted = Object.entries(value).filter(([, v]) => v !== undefined);
    if (node.flow || inFlow) {
      const sameKeys = wanted.length === pairs.length && wanted.every(([k]) => keys.has(k));
      if (sameKeys) {
        for (const p of pairs) this.node(p.value, value[keyOf(p)], true);
        return;
      }
      return this.replace(node, flowText(value));
    }
    if (!pairs.length) throw new Unsupported('empty block map');
    const indent = column(this.text, (pairs[0].key as Node).range![0]);
    for (const p of pairs) {
      const k = keyOf(p);
      if (!(k in value) || value[k] === undefined) {
        const keyNode = p.key as Node;
        const end = (p.value as Node | null)?.range?.[2] ?? keyNode.range![2];
        this.edits.push({ start: lineStart(this.text, keyNode.range![0]), end: lineEndAfter(this.text, end), text: '' });
      } else if (p.value === null || p.value === undefined) {
        throw new Unsupported('key without value');
      } else if (isEmptyCollection(value[k]) && (isMap(p.value) || isSeq(p.value)) && !(p.value as YAMLMap).flow && (p.value as YAMLMap).items.length) {
        // A block list/map emptied in the form: `key: []` / `key: {}` on the key's line.
        const keyEnd = (p.key as Node).range![1];
        this.edits.push({ start: keyEnd, end: lineEndAfter(this.text, (p.value as Node).range![2]), text: `: ${flowText(value[k])}${this.nl}` });
      } else {
        this.node(p.value, value[k], false);
      }
    }
    const added = wanted.filter(([k]) => !keys.has(k));
    if (added.length) {
      const last = pairs[pairs.length - 1];
      const end = (last.value as Node | null)?.range?.[2] ?? (last.key as Node).range![2];
      const at = lineEndAfter(this.text, end);
      const lead = at === this.text.length && !this.text.endsWith('\n') ? this.nl : '';
      this.edits.push({ start: at, end: at, text: lead + added.map(([k, v]) => pairText(k, v, indent, this.nl)).join('') });
    }
  }

  itemText(sibling: unknown, value: unknown, dash: number): string {
    const pad = ' '.repeat(dash);
    if (isScalarValue(value)) return `${pad}- ${scalarText(value, false)}${this.nl}`;
    if ((isMap(sibling) || isSeq(sibling)) && (sibling as YAMLMap).flow) return `${pad}- ${flowText(value)}${this.nl}`;
    const body = blockText(value, dash + 2, this.nl);
    return pad + '- ' + body.slice(dash + 2);
  }

  seq(node: YAMLSeq, value: unknown, inFlow: boolean) {
    if (!Array.isArray(value)) throw new Unsupported('seq -> non-seq');
    const items = node.items as Node[];
    const old = node.toJSON() as unknown[];
    if (deepEqual(old, value)) return;
    if (node.flow || inFlow || !items.length) return this.replace(node, flowText(value));
    const dash = (i: number) => {
      const start = lineStart(this.text, items[i].range![0]);
      return this.text.indexOf('-', start) - start;
    };
    // An item's lines, including the comment lines directly above it.
    const itemLines = (i: number) => {
      let start = lineStart(this.text, items[i].range![0]);
      while (start > 0) {
        const prev = lineStart(this.text, start - 1);
        if (!this.text.slice(prev, start).trim().startsWith('#')) break;
        start = prev;
      }
      return { start, end: lineEndAfter(this.text, items[i].range![2]) };
    };
    if (value.length === old.length - 1) {
      // one item removed?
      const j = old.findIndex((_, i) => deepEqual([...old.slice(0, i), ...old.slice(i + 1)], value));
      if (j >= 0) {
        const { start, end } = itemLines(j);
        this.edits.push({ start, end, text: '' });
        return;
      }
    }
    if (value.length === old.length + 1) {
      // one item inserted?
      const j = value.findIndex((_, i) => deepEqual([...value.slice(0, i), ...value.slice(i + 1)], old));
      if (j >= 0) {
        const ref = j < items.length ? j : items.length - 1;
        const at = j < items.length ? itemLines(j).start : itemLines(items.length - 1).end;
        this.edits.push({ start: at, end: at, text: this.itemText(items[ref], value[j], dash(ref)) });
        return;
      }
    }
    if (value.length !== old.length) throw new Unsupported('several items added/removed');
    // Reordered items (e.g. a stage moved up): move their text blocks, comments included.
    const used = new Set<number>();
    const order = value.map((v) => {
      const i = old.findIndex((o, k) => !used.has(k) && deepEqual(o, v));
      if (i >= 0) used.add(i);
      return i;
    });
    if (order.every((i) => i >= 0) && order.some((i, k) => i !== k)) {
      const starts = items.map((_, i) => itemLines(i).start);
      const end = itemLines(items.length - 1).end;
      const blocks = items.map((_, i) => {
        const block = this.text.slice(starts[i], i + 1 < items.length ? starts[i + 1] : end);
        return block.endsWith('\n') ? block : block + this.nl;
      });
      this.edits.push({ start: starts[0], end, text: order.map((i) => blocks[i]).join('') });
      return;
    }
    items.forEach((it, i) => this.node(it, value[i], false));
  }
}

export function patchYaml(text: string, value: unknown): string | null {
  const doc = parseDocument(text);
  if (doc.errors.length || !isMap(doc.contents)) return null;
  const patcher = new Patcher(text, eol(text));
  try {
    patcher.node(doc.contents, value, false);
  } catch (e) {
    if (e instanceof Unsupported) return null;
    throw e;
  }
  const edits = patcher.edits.sort((a, b) => a.start - b.start || a.end - b.end);
  let out = '';
  let pos = 0;
  for (const e of edits) {
    if (e.start < pos) return null; // overlapping edits
    out += text.slice(pos, e.start) + e.text;
    pos = e.end;
  }
  out += text.slice(pos);
  const check = parseDocument(out);
  if (check.errors.length || !deepEqual(check.toJS(), value)) return null;
  return out;
}
