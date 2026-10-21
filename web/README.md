# web — SynodTrade console frontend

**English** | [简体中文](README.zh-CN.md)

React 19 + TypeScript + MUI 9 + Vite. The backend is `packages/webapi` (`synodtrade-web`). The UI is available in English (default) and Simplified Chinese; switch with the language button in the top bar (the choice is remembered in the browser).

## Usage

```bash
# repository root
python tasks.py web            # npm install + build into web/dist (needs Node.js >= 20)
poetry run synodtrade-web serve     # open http://127.0.0.1:8765
```

## Development

```bash
poetry run synodtrade-web serve     # API on port 8765
cd web
npm install
npm run dev                    # http://localhost:5173, /api proxied to 8765 (change with SYNODTRADE_WEB_API)
npm run typecheck              # tsc -b
npm run i18n:check             # every UI string has a Chinese translation
npm run build                  # tsc -b && vite build, output in web/dist
```

## Pages

- **Overview**: kill switch, scheduler status, running jobs, recent runs, each pipeline's NAV.
- **Runs / run detail**: stage progress bar, live log (SSE), selection / sentiment / decisions / risk / orders / agent instances / LLM calls / config snapshot.
- **Scheduler**: start / stop the built-in scheduler, next run times, the plan for the next N days, health checks, run now.
- **Configs**: pipelines (visual flow plus each stage's agent instances, models and options), agents, prompt templates, risk rules, accounts, LLM providers, schedules.
  Every editor has a visual tab and a YAML tab kept in sync, with live server-side validation.
- **Data**: positions and account, market (bars + moving averages), database (every table).

## How forms write back to YAML

Forms edit the parsed data; `src/lib/yamlPatch.ts` turns the data change into a minimal edit of the original text,
leaving untouched lines byte-for-byte identical (aligned comments, `[a, b]` style, multi-line flow maps and CRLF line endings are kept).
The result is parsed again and compared with the target data; on a mismatch or an unsupported change it falls back to serialising the whole document with the `yaml` library
(`src/lib/yamlDoc.ts`, which keeps comments but normalises whitespace).

Form fields are generated from the Pydantic JSON Schemas served by the backend (`src/components/SchemaForm.tsx`),
so new config options appear in the forms automatically; labels and help texts live in `src/lib/labels.ts`.

## Translations

`src/i18n/` is a small, dependency-free i18n layer. UI strings are written in English and wrapped in `t()`;
the English text is the key, and `src/i18n/zh.ts` maps it to Chinese. Placeholders use `{name}`:

```tsx
import { t } from '../i18n';

<Button>{t('Save')}</Button>
<Typography>{t('{n} errors', { n: errorCount })}</Typography>
```

A string without a translation falls back to English. After adding or changing UI text, run `npm run i18n:check`
(also run in CI): it lists strings missing from `zh.ts` and entries no code uses. Dates and numbers follow the
selected language. To add a language, add a dictionary next to `zh.ts` and register it in `src/i18n/index.tsx`.
