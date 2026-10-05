// Apply form edits (plain JS values) to a YAML document without losing comments, key order,
// block scalars (|, >-) or flow style ({ agent: x, count: 1 }) of the parts that did not change.

import { Document, isMap, isScalar, isSeq, parseDocument, type Pair, type YAMLMap, type YAMLSeq } from 'yaml';
import { patchYaml } from './yamlPatch';

export const STRINGIFY = { lineWidth: 0, minContentWidth: 0, indentSeq: true } as const;

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function keyOf(pair: Pair): string {
  const k = pair.key as unknown;
  return isScalar(k) ? String(k.value) : String(k);
}

function setFlow(node: unknown, flow: boolean) {
  if (flow && (isMap(node) || isSeq(node))) (node as YAMLMap | YAMLSeq).flow = true;
}

function create(doc: Document, value: unknown, flow: boolean): unknown {
  const node = doc.createNode(value);
  setFlow(node, flow);
  return node;
}

function update(doc: Document, node: unknown, value: unknown, flowHint: boolean): unknown {
  if (isPlainObject(value)) {
    if (!isMap(node)) return create(doc, value, flowHint);
    const map = node as YAMLMap;
    const wanted = Object.entries(value).filter(([, v]) => v !== undefined);
    const keys = new Set(wanted.map(([k]) => k));
    map.items = (map.items as Pair[]).filter((p) => keys.has(keyOf(p)));
    for (const [k, v] of wanted) {
      const pair = (map.items as Pair[]).find((p) => keyOf(p) === k);
      if (pair) pair.value = update(doc, pair.value, v, !!map.flow) as any;
      else map.items.push(doc.createPair(k, create(doc, v, !!map.flow)) as any);
    }
    return map;
  }
  if (Array.isArray(value)) {
    if (!isSeq(node)) return create(doc, value, flowHint);
    const seq = node as YAMLSeq;
    const siblingFlow = seq.items.some((it) => (isMap(it) || isSeq(it)) && (it as YAMLMap).flow);
    value.forEach((v, i) => {
      if (i < seq.items.length) seq.items[i] = update(doc, seq.items[i], v, siblingFlow || !!seq.flow);
      else seq.items.push(create(doc, v, siblingFlow || !!seq.flow));
    });
    seq.items.length = value.length;
    return seq;
  }
  if (isScalar(node)) {
    if (node.value === value) return node;
    // Keep the scalar's style (block literal, quotes) when the type stays the same.
    if (typeof node.value === typeof value || node.value === null) {
      node.value = value;
      return node;
    }
  }
  return doc.createNode(value);
}

/** New YAML text: `text` with its data replaced by `value`, comments preserved.
 * Prefers a minimal text patch (untouched lines stay byte-identical); falls back to
 * re-serialising the document, which keeps comments but normalises whitespace. */
export function applyJson(text: string, value: unknown): string {
  const patched = patchYaml(text, value);
  if (patched !== null) return patched;
  const doc = parseDocument(text);
  if (doc.errors.length) throw new Error(doc.errors[0].message);
  if (doc.contents === null || doc.contents === undefined) {
    doc.contents = doc.createNode(value) as any;
  } else {
    doc.contents = update(doc, doc.contents, value, false) as any;
  }
  return doc.toString(STRINGIFY);
}

export interface Parsed {
  data: any;
  error: string | null;
  errorLine: number | null;
}

export function parseYaml(text: string): Parsed {
  const doc = parseDocument(text);
  if (doc.errors.length) {
    const e = doc.errors[0];
    return { data: null, error: e.message, errorLine: e.linePos?.[0]?.line ?? null };
  }
  try {
    return { data: doc.toJS() ?? {}, error: null, errorLine: null };
  } catch (e) {
    return { data: null, error: String(e), errorLine: null };
  }
}

export function toYaml(value: unknown): string {
  const doc = new Document(value);
  return doc.toString(STRINGIFY);
}

/** Immutable set at a path; `undefined` removes the key / element. */
export function setIn(obj: any, path: (string | number)[], value: unknown): any {
  if (path.length === 0) return value;
  const [head, ...rest] = path;
  if (typeof head === 'number') {
    const arr = Array.isArray(obj) ? [...obj] : [];
    if (rest.length === 0 && value === undefined) {
      arr.splice(head, 1);
      return arr;
    }
    arr[head] = setIn(arr[head], rest, value);
    return arr;
  }
  const out = isPlainObject(obj) ? { ...obj } : {};
  const next = setIn(out[head], rest, value);
  if (next === undefined) delete out[head];
  else out[head] = next;
  return out;
}

export function getIn(obj: any, path: (string | number)[]): any {
  let cur = obj;
  for (const p of path) {
    if (cur === null || cur === undefined) return undefined;
    cur = cur[p as any];
  }
  return cur;
}
