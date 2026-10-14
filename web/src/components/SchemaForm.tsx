// Generic form fields generated from the Pydantic JSON schemas the API serves, so the forms
// always match what the Python side validates. Unset fields show their default and are
// left out of the YAML; clearing a field removes the key again.

import {
  Autocomplete,
  Box,
  Button,
  Chip,
  FormControlLabel,
  Grid,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import { createContext, useContext, useEffect, useState } from 'react';
import { parse as parseYamlText } from 'yaml';
import { type Field, formatDefault } from '../lib/schema';
import { help, label } from '../lib/labels';
import { toYaml } from '../lib/yamlDoc';
import { t } from '../i18n';

export type Path = (string | number)[];
export const pathKey = (p: Path) => p.join('.');

/** Validation errors by dotted path, e.g. "stages.0.aggregation.method". */
export const ErrorsContext = createContext<Record<string, string>>({});

const UPPER_KEYS = new Set(['universe', 'symbols', 'whitelist', 'blacklist']);
const MULTILINE_KEYS = new Set(['persona', 'instructions', 'note']);

function useFieldError(path: Path): string | undefined {
  return useContext(ErrorsContext)[pathKey(path)];
}

function FieldLabel({ name }: { name: string | number }) {
  const text = label(name);
  return (
    <span>
      {text}
      {text !== String(name) && (
        <Box component="span" sx={{ ml: 0.75, fontFamily: 'monospace', fontSize: '0.85em', opacity: 0.6 }}>
          {name}
        </Box>
      )}
    </span>
  );
}

function helperText(name: string | number, field: Field, error?: string): React.ReactNode {
  if (error) return error;
  const parts = [help(name)];
  if (field.hasDefault && field.default !== undefined && typeof field.default !== 'object') parts.push(t('Default {value}', { value: formatDefault(field.default) }));
  if (field.default === null && field.nullable) parts.push(t('No limit by default'));
  return parts.filter(Boolean).join(' · ') || undefined;
}

// ------------------------------------------------------------------ scalars

function NumberInput({
  name,
  field,
  value,
  onChange,
  path,
  required,
}: {
  name: string | number;
  field: Field;
  value: any;
  onChange: (v: any) => void;
  path: Path;
  required?: boolean;
}) {
  const error = useFieldError(path);
  const show = (v: any) => (v === undefined ? '' : v === null ? 'null' : String(v));
  const [text, setText] = useState(show(value));
  useEffect(() => setText(show(value)), [value]);
  const commit = (t: string) => {
    const s = t.trim();
    if (s === '') return onChange(undefined);
    if (s === 'null') return onChange(null);
    const n = Number(s);
    onChange(Number.isFinite(n) && /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s) ? n : s); // ${ENV} stays a string
  };
  return (
    <TextField
      fullWidth
      size="small"
      label={<FieldLabel name={name} />}
      value={text}
      required={required}
      placeholder={field.hasDefault ? formatDefault(field.default) : undefined}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => commit(text)}
      onKeyDown={(e) => e.key === 'Enter' && commit(text)}
      error={!!error}
      helperText={helperText(name, field, error)}
      slotProps={{ inputLabel: { shrink: true }, htmlInput: { inputMode: 'decimal' } }}
    />
  );
}

function StringInput({
  name,
  field,
  value,
  onChange,
  path,
  required,
  options,
}: {
  name: string | number;
  field: Field;
  value: any;
  onChange: (v: any) => void;
  path: Path;
  required?: boolean;
  options?: string[];
}) {
  const error = useFieldError(path);
  const multiline = MULTILINE_KEYS.has(String(name)) || (typeof value === 'string' && (value.includes('\n') || value.length > 90));
  if (options) {
    return (
      <Autocomplete
        freeSolo
        options={options}
        value={value ?? ''}
        onChange={(_, v) => onChange(v ? String(v) : undefined)}
        onInputChange={(_, v, reason) => reason === 'input' && onChange(v || undefined)}
        renderInput={(params) => (
          <TextField
            {...params}
            size="small"
            required={required}
            label={<FieldLabel name={name} />}
            error={!!error}
            helperText={helperText(name, field, error)}
            placeholder={field.hasDefault ? formatDefault(field.default) : undefined}
            slotProps={{ ...params.slotProps, inputLabel: { shrink: true } }}
          />
        )}
      />
    );
  }
  return (
    <TextField
      fullWidth
      size="small"
      multiline={multiline}
      minRows={multiline ? 3 : undefined}
      required={required}
      label={<FieldLabel name={name} />}
      value={value ?? ''}
      placeholder={field.hasDefault ? formatDefault(field.default) : undefined}
      onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)}
      error={!!error}
      helperText={helperText(name, field, error)}
      slotProps={{ inputLabel: { shrink: true } }}
    />
  );
}

function EnumInput({ name, field, value, onChange, path, required }: { name: string | number; field: Field; value: any; onChange: (v: any) => void; path: Path; required?: boolean }) {
  const error = useFieldError(path);
  const values = field.enumValues ?? [];
  const unset = '__unset__';
  return (
    <TextField
      select
      fullWidth
      size="small"
      required={required}
      label={<FieldLabel name={name} />}
      value={value === undefined ? unset : value === null ? '__null__' : String(value)}
      onChange={(e) => {
        const v = e.target.value;
        if (v === unset) onChange(undefined);
        else if (v === '__null__') onChange(null);
        else onChange(values.find((x) => String(x) === v) ?? v);
      }}
      error={!!error}
      helperText={error ?? help(name)}
      slotProps={{ inputLabel: { shrink: true } }}
    >
      {!required && (
        <MenuItem value={unset}>
          <em>{field.hasDefault ? t('Default ({value})', { value: formatDefault(field.default) }) : t('Not set')}</em>
        </MenuItem>
      )}
      {field.nullable && <MenuItem value="__null__">null</MenuItem>}
      {values.map((v) => (
        <MenuItem key={String(v)} value={String(v)}>
          {String(v)}
        </MenuItem>
      ))}
    </TextField>
  );
}

function BooleanInput({ name, field, value, onChange, path }: { name: string | number; field: Field; value: any; onChange: (v: any) => void; path: Path }) {
  const error = useFieldError(path);
  const effective = value ?? field.default ?? false;
  return (
    <Box>
      <Stack direction="row" sx={{ alignItems: 'center' }}>
        <FormControlLabel
          control={<Switch size="small" checked={!!effective} onChange={(e) => onChange(e.target.checked)} />}
          label={
            <Typography variant="body2" component="span">
              <FieldLabel name={name} />
              {value === undefined && (
                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                  {t('(default)')}
                </Typography>
              )}
            </Typography>
          }
        />
        {value !== undefined && field.hasDefault && (
          <Tooltip title={t('Reset to default (remove from YAML)')}>
            <IconButton size="small" onClick={() => onChange(undefined)}>
              <RestartAltIcon fontSize="inherit" />
            </IconButton>
          </Tooltip>
        )}
      </Stack>
      {(error || help(name)) && (
        <Typography variant="caption" color={error ? 'error' : 'text.secondary'} sx={{ display: 'block', mt: -0.5, ml: 0.5 }}>
          {error ?? help(name)}
        </Typography>
      )}
    </Box>
  );
}

function ScalarList({ name, field, value, onChange, path, required }: { name: string | number; field: Field; value: any; onChange: (v: any) => void; path: Path; required?: boolean }) {
  const error = useFieldError(path);
  const items: string[] = Array.isArray(value) ? value.map(String) : [];
  const enumOptions = field.items?.enumValues?.map(String);
  const upper = UPPER_KEYS.has(String(name));
  const numeric = field.items?.kind === 'number' || field.items?.kind === 'integer';
  return (
    <Autocomplete
      multiple
      freeSolo={!enumOptions}
      options={enumOptions ?? []}
      value={items}
      onChange={(_, v) => {
        const next = (v as string[])
          .flatMap((s) => String(s).split(/[,\s]+/))
          .map((s) => (upper ? s.trim().toUpperCase() : s.trim()))
          .filter(Boolean)
          .map((s) => (numeric && !Number.isNaN(Number(s)) ? Number(s) : s));
        const unique = [...new Set(next)];
        onChange(unique.length || required ? unique : value === undefined ? undefined : []);
      }}
      renderValue={(vals, getItemProps) =>
        vals.map((option, index) => {
          const { key, ...rest } = getItemProps({ index });
          return <Chip key={key} size="small" label={String(option)} {...rest} />;
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          size="small"
          label={<FieldLabel name={name} />}
          placeholder={items.length ? '' : enumOptions ? t('Choose…') : t('Type and press Enter')}
          error={!!error}
          helperText={error ?? help(name) ?? (field.hasDefault && field.default ? t('Default {value}', { value: formatDefault(field.default) }) : undefined)}
          slotProps={{ ...params.slotProps, inputLabel: { shrink: true } }}
        />
      )}
    />
  );
}

function AnyInput({ name, value, onChange, path }: { name: string | number; value: any; onChange: (v: any) => void; path: Path }) {
  const error = useFieldError(path);
  const show = (v: any) => (v === undefined ? '' : toYaml(v).trimEnd());
  const [text, setText] = useState(show(value));
  const [bad, setBad] = useState<string | null>(null);
  useEffect(() => setText(show(value)), [value]);
  return (
    <TextField
      fullWidth
      size="small"
      multiline
      minRows={2}
      label={<FieldLabel name={name} />}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (!text.trim()) return onChange(undefined);
        try {
          onChange(parseYamlText(text));
          setBad(null);
        } catch (e) {
          setBad(String(e));
        }
      }}
      error={!!(error || bad)}
      helperText={bad ?? error ?? t('YAML snippet')}
      slotProps={{ inputLabel: { shrink: true }, htmlInput: { style: { fontFamily: 'monospace', fontSize: 13 } } }}
    />
  );
}

// ------------------------------------------------------------------ collections

function MapInput({ name, field, value, onChange, path }: { name: string | number; field: Field; value: any; onChange: (v: any) => void; path: Path }) {
  const entries = Object.entries<any>(value && typeof value === 'object' ? value : {});
  const [newKey, setNewKey] = useState('');
  const values = field.values ?? ({ kind: 'any', nullable: true, hasDefault: false } as Field);
  const set = (next: [string, any][]) => onChange(next.length ? Object.fromEntries(next) : undefined);
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
        <FieldLabel name={name} />
      </Typography>
      {help(name) && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          {help(name)}
        </Typography>
      )}
      <Stack spacing={1.5}>
        {entries.map(([k, v], i) => (
          <Stack key={k} direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <FieldEditor
                name={k}
                field={values}
                value={v}
                path={[...path, k]}
                onChange={(nv) => set(nv === undefined ? entries.filter((_, j) => j !== i) : entries.map((e, j) => (j === i ? [k, nv] : e)))}
              />
            </Box>
            <IconButton size="small" onClick={() => set(entries.filter((_, j) => j !== i))}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Stack>
        ))}
        <Stack direction="row" spacing={1}>
          <TextField size="small" placeholder={t('New key')} value={newKey} onChange={(e) => setNewKey(e.target.value)} />
          <Button
            size="small"
            startIcon={<AddIcon />}
            disabled={!newKey.trim() || entries.some(([k]) => k === newKey.trim())}
            onClick={() => {
              const initial = values.kind === 'array' ? [] : values.kind === 'object' || values.kind === 'map' ? {} : '';
              set([...entries, [newKey.trim(), initial]]);
              setNewKey('');
            }}
          >
            {t('Add')}
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

function ObjectList({ name, field, value, onChange, path }: { name: string | number; field: Field; value: any; onChange: (v: any) => void; path: Path }) {
  const items: any[] = Array.isArray(value) ? value : [];
  const item = field.items as Field;
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
        <FieldLabel name={name} />
      </Typography>
      <Stack spacing={1.5}>
        {items.map((it, i) => (
          <Paper key={i} variant="outlined" sx={{ p: 1.5, position: 'relative' }}>
            <IconButton size="small" sx={{ position: 'absolute', top: 4, right: 4 }} onClick={() => onChange(items.filter((_, j) => j !== i))}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
            <SchemaFields field={item} value={it} path={[...path, i]} onChange={(v) => onChange(items.map((x, j) => (j === i ? (v ?? {}) : x)))} />
          </Paper>
        ))}
        <Box>
          <Button size="small" startIcon={<AddIcon />} onClick={() => onChange([...items, {}])}>
            {t('Add')}
          </Button>
        </Box>
      </Stack>
    </Paper>
  );
}

// ------------------------------------------------------------------ dispatch

export function FieldEditor({
  name,
  field,
  value,
  onChange,
  path,
  required,
  options,
}: {
  name: string | number;
  field: Field | undefined;
  value: any;
  onChange: (v: any) => void;
  path: Path;
  required?: boolean;
  options?: string[];
}) {
  if (!field) {
    return (
      <Typography variant="body2" color="warning.main" sx={{ py: 1 }}>
        {t("{name}: the server's config schema has no such field. The web page is newer than the backend; restart quant-web serve.", { name: String(name) })}
      </Typography>
    );
  }
  const common = { name, field, value, onChange, path, required };
  // A value of an unexpected type (e.g. "${ENV}" in a number field) is edited as such.
  if (typeof value === 'string' && (field.kind === 'number' || field.kind === 'integer')) return <NumberInput {...common} />;
  switch (field.kind) {
    case 'boolean':
      return <BooleanInput {...common} />;
    case 'number':
    case 'integer':
      return <NumberInput {...common} />;
    case 'enum':
      return <EnumInput {...common} />;
    case 'string':
      return <StringInput {...common} options={options} />;
    case 'array':
      if (field.items && ['object'].includes(field.items.kind)) return <ObjectList {...common} />;
      if (field.items && ['string', 'number', 'integer', 'enum'].includes(field.items.kind)) return <ScalarList {...common} />;
      return <AnyInput {...common} />;
    case 'map':
      return <MapInput {...common} />;
    case 'object':
      return (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="body2" sx={{ fontWeight: 600, mb: 1.5 }}>
            <FieldLabel name={name} />
          </Typography>
          <SchemaFields field={field} value={value} path={path} onChange={(v) => onChange(v === undefined && required ? {} : v)} />
        </Paper>
      );
    default:
      return <AnyInput {...common} />;
  }
}

const WIDE = new Set<string>(['object', 'map', 'array', 'any']);

function isWide(name: string, f: Field, value: any) {
  if (WIDE.has(f.kind) && !(f.kind === 'array' && f.items && f.items.kind !== 'object')) return true;
  if (MULTILINE_KEYS.has(name)) return true;
  return typeof value === 'string' && value.length > 60;
}

/** All properties of an object schema as a responsive grid. */
export function SchemaFields({
  field,
  value,
  onChange,
  path,
  omit = [],
  only,
  options = {},
  columns = 3,
}: {
  field: Field | undefined;
  value: any;
  onChange: (v: any) => void;
  path: Path;
  omit?: string[];
  only?: string[];
  options?: Record<string, string[]>;
  columns?: 2 | 3 | 4;
}) {
  if (!field) return null; // unknown to an older server: nothing to edit
  const obj = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const keys = (only ?? field.order ?? Object.keys(field.properties ?? {})).filter((k) => !omit.includes(k) && field.properties?.[k]);
  const set = (k: string, v: any) => {
    const next = { ...obj };
    if (v === undefined) delete next[k];
    else next[k] = v;
    onChange(Object.keys(next).length ? next : undefined);
  };
  const narrow = 12 / columns;
  return (
    <Grid container spacing={2}>
      {keys.map((k) => {
        const f = field.properties![k];
        const wide = isWide(k, f, obj[k]);
        return (
          <Grid key={k} size={{ xs: 12, sm: wide ? 12 : 6, md: wide ? 12 : narrow }}>
            <FieldEditor name={k} field={f} value={obj[k]} path={[...path, k]} required={field.required?.includes(k)} options={options[k]} onChange={(v) => set(k, v)} />
          </Grid>
        );
      })}
    </Grid>
  );
}
