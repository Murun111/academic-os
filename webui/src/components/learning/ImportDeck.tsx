import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import {
  learning, isUnavailable, isLearningApiError,
  type ImportInput, type ImportPreview,
} from '../../lib/learningApi'
import { Btn, Mono } from '../ui'

const FIELD =
  'w-full rounded-md border border-line bg-transparent px-2.5 py-1.5 text-[13px] text-hi placeholder:text-low focus:border-ink/30 focus:outline-none'

type Source = 'anki' | 'quizlet' | 'other'

const SOURCES: { id: Source; label: string }[] = [
  { id: 'anki', label: 'Anki file' },
  { id: 'quizlet', label: 'Quizlet' },
  { id: 'other', label: 'Other text' },
]

const TERM_SEPS = [
  { label: 'Auto', value: 'auto' },
  { label: 'Tab', value: '\t' },
  { label: 'Comma', value: ',' },
  { label: 'Dash ( - )', value: ' - ' },
]
const ROW_SEPS = [
  { label: 'Auto', value: 'auto' },
  { label: 'New line', value: '\n' },
  { label: 'Semicolon', value: ';' },
]

function errMsg(e: unknown): string {
  if (isUnavailable(e)) return 'The study service is unavailable right now. Try again in a moment.'
  if (isLearningApiError(e) && e.detail) return e.detail
  return 'Something went wrong. Try again.'
}

function titleFromFile(name: string): string {
  return name.replace(/\.(apkg|colpkg|txt|csv)$/i, '').replace(/[_-]+/g, ' ').trim()
}

export function ImportDeck({ onImported }: { onImported: () => void }) {
  const [source, setSource] = useState<Source>('anki')
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [termSep, setTermSep] = useState('auto')
  const [rowSep, setRowSep] = useState('auto')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const inFlight = useRef(false)

  const usesText = source !== 'anki'
  const hasInput = usesText ? text.trim().length > 0 : file !== null

  const buildInput = (): ImportInput => {
    if (usesText) {
      return {
        text,
        format: source === 'quizlet' ? 'quizlet' : 'auto',
        term_sep: termSep,
        row_sep: rowSep,
      }
    }
    return { file: file ?? undefined, format: 'auto', term_sep: termSep, row_sep: rowSep }
  }

  const invalidate = () => {
    setPreview(null)
    setDone(null)
    setError(null)
  }

  // single-flight guard shared by preview and import
  const run = async (fn: () => Promise<void>) => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(errMsg(e))
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const doPreview = () =>
    run(async () => {
      setDone(null)
      const p = await learning.importPreview(buildInput())
      setPreview(p)
      if (!title.trim()) setTitle(file ? titleFromFile(file.name) : '')
    })

  const doImport = () => {
    const t = title.trim()
    if (!t || !preview) return
    return run(async () => {
      const r = await learning.importDeck({ ...buildInput(), deck_title: t })
      setDone(`Imported ${r.imported} card${r.imported === 1 ? '' : 's'} into "${r.deck.title}".`)
      setPreview(null)
      setFile(null)
      setText('')
      setTitle('')
      onImported()
    })
  }

  const sepSelect = (
    label: string, value: string, set: (v: string) => void, opts: { label: string; value: string }[],
  ) => (
    <label className="flex flex-col gap-1">
      <span className="label-mono">{label}</span>
      <select
        value={value}
        disabled={busy}
        onChange={(e) => { set(e.target.value); invalidate() }}
        className={FIELD}
      >
        {opts.map((o) => <option key={o.label} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  )

  return (
    <section aria-label="Import deck" className="mb-4 rounded-[10px] border border-line px-4 py-3">
      <div role="tablist" aria-label="Import source" className="mb-3 flex gap-1">
        {SOURCES.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={source === s.id}
            disabled={busy}
            onClick={() => { setSource(s.id); invalidate() }}
            className={`rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-40 ${
              source === s.id ? 'bg-ink/8 text-hi' : 'text-mid hover:bg-ink/5 hover:text-hi'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {source === 'anki' && (
        <label className="mb-3 flex flex-col gap-1">
          <span className="label-mono">file (.apkg, .colpkg, .txt, .csv)</span>
          <input
            type="file"
            accept=".apkg,.colpkg,.txt,.csv"
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null
              setFile(f)
              invalidate()
              setTitle(f ? titleFromFile(f.name) : '')
            }}
            className="text-[13px] text-mid file:mr-3 file:rounded-md file:border-0 file:bg-ink/8 file:px-3 file:py-1.5 file:text-[13px] file:text-hi"
          />
        </label>
      )}

      {usesText && (
        <div className="mb-3 flex flex-col gap-2">
          {source === 'quizlet' && (
            <p className="text-[12px] text-low">
              In Quizlet: open the set, then More (...) &gt; Export &gt; Copy text. Paste it below.
            </p>
          )}
          <label className="flex flex-col gap-1">
            <span className="label-mono">{source === 'quizlet' ? 'quizlet export' : 'text (one card per line)'}</span>
            <textarea
              value={text}
              disabled={busy}
              onChange={(e) => { setText(e.target.value); invalidate() }}
              rows={6}
              placeholder="term, definition"
              className={FIELD}
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            {sepSelect('between term and definition', termSep, setTermSep, TERM_SEPS)}
            {sepSelect('between cards', rowSep, setRowSep, ROW_SEPS)}
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mb-3 rounded-md border border-fail/30 px-3 py-2 text-[12px] text-fail">{error}</p>
      )}
      {done && (
        <p role="status" className="mb-3 rounded-md border border-line px-3 py-2 text-[12px] text-hi">{done}</p>
      )}

      {!preview && (
        <Btn kind="primary" onClick={() => void doPreview()} disabled={busy || !hasInput}>
          <span className="flex items-center gap-1.5"><Upload size={13} /> {busy ? 'Reading…' : 'Preview'}</span>
        </Btn>
      )}

      {preview && (
        <div className="flex flex-col gap-3">
          <Mono className="text-low">
            {preview.total} card{preview.total === 1 ? '' : 's'} found
            {preview.skipped > 0 ? `, ${preview.skipped} skipped` : ''}
            {preview.cards.length < preview.total ? ` (showing first ${preview.cards.length})` : ''}
          </Mono>
          {preview.warnings.length > 0 && (
            <ul className="text-[12px] text-low" aria-label="Import warnings">
              {preview.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
          <ul className="flex max-h-56 flex-col gap-px overflow-y-auto" aria-label="Preview cards">
            {preview.cards.map((c, i) => (
              <li key={i} className="rounded-[10px] px-3 py-2 hover:bg-ink/4">
                <p className="whitespace-pre-wrap break-words text-[13px] text-hi">{c.front}</p>
                <p className="whitespace-pre-wrap break-words text-[12px] text-low">{c.back}</p>
              </li>
            ))}
          </ul>
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => { e.preventDefault(); void doImport() }}
            aria-label="Import as deck"
          >
            <label className="flex flex-1 flex-col gap-1">
              <span className="label-mono">deck title</span>
              <input
                value={title}
                disabled={busy}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Deck title"
                className={FIELD}
              />
            </label>
            <button
              type="submit"
              disabled={busy || !title.trim()}
              className="shrink-0 rounded-lg bg-ink/8 px-3 py-1.5 text-[13px] font-medium text-hi transition-colors duration-150 hover:bg-ink/12 disabled:pointer-events-none disabled:opacity-40"
            >
              {busy ? 'Importing…' : `Import ${preview.total} cards`}
            </button>
          </form>
        </div>
      )}
    </section>
  )
}
