// Normalise Pydantic JSON schemas ($ref, anyOf-with-null, Decimal = number|string) into a
// small descriptor the form renderer understands.

import type { JsonSchema } from '../api/client';

export type FieldKind = 'object' | 'array' | 'map' | 'string' | 'number' | 'integer' | 'boolean' | 'enum' | 'any';

export interface Field {
  kind: FieldKind;
  nullable: boolean;
  default?: any;
  hasDefault: boolean;
  enumValues?: (string | number)[];
  properties?: Record<string, Field>;
  order?: string[];
  required?: string[];
  items?: Field;
  values?: Field; // map values
  min?: number;
  max?: number;
  exclusiveMin?: boolean;
  pattern?: string;
  title?: string;
  description?: string;
  minItems?: number;
}

function deref(schema: JsonSchema, defs: Record<string, JsonSchema>): JsonSchema {
  let s = schema;
  for (let i = 0; i < 10 && s && s.$ref; i++) {
    const name = String(s.$ref).split('/').pop() as string;
    const { $ref: _ignored, ...rest } = s;
    s = { ...defs[name], ...rest };
  }
  if (s && Array.isArray(s.allOf) && s.allOf.length === 1) {
    const { allOf, ...rest } = s;
    s = { ...deref(allOf[0], defs), ...rest };
  }
  return s ?? {};
}

export function normalize(schema: JsonSchema, rootDefs?: Record<string, JsonSchema>): Field {
  const defs = rootDefs ?? schema.$defs ?? {};
  let s = deref(schema, defs);
  let nullable = false;
  const outer = s;
  if (Array.isArray(s.anyOf)) {
    const options = s.anyOf.map((o: JsonSchema) => deref(o, defs));
    const nonNull = options.filter((o: JsonSchema) => o.type !== 'null');
    nullable = nonNull.length < options.length;
    const numeric = nonNull.find((o: JsonSchema) => o.type === 'number' || o.type === 'integer');
    if (nonNull.length === 1) s = { ...nonNull[0], default: outer.default, title: outer.title, description: outer.description };
    else if (numeric) s = { ...numeric, default: outer.default, title: outer.title }; // Decimal
    else s = { default: outer.default, title: outer.title };
  }
  const base = {
    nullable,
    default: s.default,
    hasDefault: 'default' in s || 'default' in outer,
    title: s.title,
    description: s.description ?? outer.description,
  };
  if (Array.isArray(s.enum)) return { ...base, kind: 'enum', enumValues: s.enum };
  if (s.const !== undefined) return { ...base, kind: 'enum', enumValues: [s.const] };
  switch (s.type) {
    case 'object': {
      if (s.properties) {
        const properties: Record<string, Field> = {};
        for (const [k, v] of Object.entries<JsonSchema>(s.properties)) properties[k] = normalize(v, defs);
        return { ...base, kind: 'object', properties, order: Object.keys(s.properties), required: s.required ?? [] };
      }
      const values = s.additionalProperties && s.additionalProperties !== true ? normalize(s.additionalProperties, defs) : ({ kind: 'any', nullable: true, hasDefault: false } as Field);
      return { ...base, kind: 'map', values };
    }
    case 'array':
      return { ...base, kind: 'array', items: s.items ? normalize(s.items, defs) : ({ kind: 'any', nullable: true, hasDefault: false } as Field), minItems: s.minItems };
    case 'string':
      return { ...base, kind: 'string', pattern: s.pattern };
    case 'integer':
    case 'number':
      return {
        ...base,
        kind: s.type,
        min: s.minimum ?? s.exclusiveMinimum,
        max: s.maximum ?? s.exclusiveMaximum,
        exclusiveMin: s.exclusiveMinimum !== undefined,
      };
    case 'boolean':
      return { ...base, kind: 'boolean' };
    default:
      return { ...base, kind: 'any' };
  }
}

/** Properties of an object schema, optionally without some keys. */
export function objectFields(schema: JsonSchema, omit: string[] = []): Field {
  const f = normalize(schema);
  if (f.kind !== 'object' || !f.properties) return f;
  const properties = Object.fromEntries(Object.entries(f.properties).filter(([k]) => !omit.includes(k)));
  return { ...f, properties, order: (f.order ?? []).filter((k) => !omit.includes(k)) };
}

export function formatDefault(v: any): string {
  if (v === undefined) return '';
  if (v === null) return 'null';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}
