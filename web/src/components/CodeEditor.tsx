import CodeMirror from '@uiw/react-codemirror';
import { yaml } from '@codemirror/lang-yaml';
import { StreamLanguage } from '@codemirror/language';
import { jinja2 } from '@codemirror/legacy-modes/mode/jinja2';
import { json } from '@codemirror/legacy-modes/mode/javascript';
import { EditorView } from '@codemirror/view';
import { useTheme } from '@mui/material';
import { useMemo } from 'react';

export type Lang = 'yaml' | 'jinja' | 'json' | 'text';

export function CodeEditor({
  value,
  onChange,
  lang = 'yaml',
  readOnly = false,
  height = '60vh',
}: {
  value: string;
  onChange?: (v: string) => void;
  lang?: Lang;
  readOnly?: boolean;
  height?: string;
}) {
  const theme = useTheme();
  const extensions = useMemo(() => {
    const ext: any[] = [EditorView.lineWrapping];
    if (lang === 'yaml') ext.push(yaml());
    if (lang === 'jinja') ext.push(StreamLanguage.define(jinja2));
    if (lang === 'json') ext.push(StreamLanguage.define(json));
    return ext;
  }, [lang]);
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      editable={!readOnly}
      readOnly={readOnly}
      height={height}
      theme={theme.palette.mode === 'dark' ? 'dark' : 'light'}
      extensions={extensions}
      basicSetup={{ foldGutter: true, highlightActiveLine: !readOnly }}
      style={{ fontSize: 13, border: `1px solid ${theme.palette.divider}`, borderRadius: 4, overflow: 'hidden' }}
    />
  );
}
