// Syllabus import: upload or paste, read with the local model, edit the
// preview, then add the items to an existing or new course.
import { useRef, useState } from 'react'
import { AlertTriangle, Upload, X } from 'lucide-react'
import {
  applySyllabus, previewSyllabus,
  type CourseSummary, type SyllabusApplyResult, type SyllabusItem, type SyllabusPreview,
} from '../lib/coursesApi'
import { Btn, EmptyState, Mono, Panel, PanelHead } from './ui'

const NEW = '__new__'
const OFFLINE_MSG = 'The local AI is not available right now. Start your local model and try again.'
const FIELD = 'rounded-md border border-line bg-raise2 px-2 py-1 text-[12.5px] text-hi outline-none focus:border-ink/30 placeholder:text-low'

interface Row extends SyllabusItem { checked: boolean }

function errorText(status: number, error: string): string {
  if (status === 503) return OFFLINE_MSG
  if (status === 502) return 'The model returned something unreadable. Try again, or paste a cleaner copy of the syllabus.'
  return error
}

export function SyllabusImport({ courses, onClose, onDone }: {
  courses: CourseSummary[]
  onClose: () => void
  onDone: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [termStart, setTermStart] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<SyllabusPreview | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [target, setTarget] = useState<string>(NEW)
  const [newName, setNewName] = useState('')
  const [newTerm, setNewTerm] = useState('')
  const [result, setResult] = useState<SyllabusApplyResult | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const hasSource = !!file || text.trim() !== ''
  const selected = rows.filter((r) => r.checked)
  const invalid = selected.some((r) => !r.title.trim())
  const badWeight = (w: number | null) => w != null && (Number.isNaN(w) || w < 0 || w > 100)
  const weightsOk = !selected.some((r) => badWeight(r.weight))
  const targetOk = target === NEW ? newName.trim() !== '' && newTerm.trim() !== '' : true

  const read = async () => {
    if (!hasSource) return
    setBusy(true); setError('')
    const year = termStart ? Number(termStart.slice(0, 4)) : undefined
    const res = await previewSyllabus({
      file: file ?? undefined,
      text: file ? undefined : text,
      term_start: termStart || undefined,
      term_year: year && !Number.isNaN(year) ? year : undefined,
    })
    setBusy(false)
    if (!res.ok) { setError(errorText(res.status, res.error)); return }
    setPreview(res.data)
    setRows(res.data.items.map((i) => ({
      ...i,
      weight: i.weight != null && (i.weight < 0 || i.weight > 100) ? null : i.weight, // points, not a percent
      checked: !!i.due,
    })))
    setNewName(res.data.course_name ?? '')
    setTarget(NEW)
  }

  const patch = (idx: number, p: Partial<Row>) =>
    setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, ...p } : r)))

  const apply = async () => {
    if (selected.length === 0 || invalid || !targetOk || !weightsOk) return
    setBusy(true); setError('')
    const items = selected.map((r) => ({
      title: r.title.trim(), due: r.due || null, weight: r.weight, points: r.points ?? null, kind: r.kind,
    }))
    const res = await applySyllabus(
      target === NEW
        ? { new_course: { name: newName.trim(), term: newTerm.trim() }, items }
        : { course_id: target, items },
    )
    setBusy(false)
    if (!res.ok) { setError(errorText(res.status, res.error)); return }
    setResult(res.data)
    onDone()
  }

  const restart = () => {
    setPreview(null); setRows([]); setResult(null); setError('')
    setFile(null); setText(''); if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <Panel className="mb-6">
      <PanelHead
        label="import syllabus"
        right={
          <button onClick={onClose} aria-label="Close syllabus import" className="text-low transition-colors hover:text-hi">
            <X size={14} />
          </button>
        }
      />
      <div className="space-y-3 px-5 pb-5">
        {error && (
          <p role="alert" className="flex items-start gap-1.5 text-[12.5px] text-fail">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden /> {error}
          </p>
        )}

        {result ? (
          <div role="status" className="space-y-3">
            <p className="text-[13px] text-hi">
              Added {result.created} assignment{result.created === 1 ? '' : 's'} to {result.course.name}.
              {result.skipped > 0 && ` Skipped ${result.skipped} duplicate${result.skipped === 1 ? '' : 's'}.`}
            </p>
            {(result.warnings ?? []).map((w, i) => (
              <p key={i} className="flex items-start gap-1.5 text-[12.5px] text-pend">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden /> {w}
              </p>
            ))}
            <div className="flex gap-2">
              <Btn onClick={restart}>Import another</Btn>
              <Btn kind="primary" onClick={onClose}>Done</Btn>
            </div>
          </div>
        ) : busy && !preview ? (
          <div role="status"><EmptyState title="Reading the syllabus…" hint="A local model can take a minute. You can keep this tab open." /></div>
        ) : !preview ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium text-mid transition-colors hover:bg-ink/5 hover:text-hi focus-within:ring-2 focus-within:ring-ink/20">
                <Upload size={14} aria-hidden />
                {file ? file.name : 'Choose file (.pdf .docx .txt .md .html)'}
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.docx,.txt,.md,.html"
                  className="sr-only"
                  onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError('') }}
                />
              </label>
              {file && <Btn onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = '' }}>Remove file</Btn>}
            </div>
            <div>
              <label htmlFor="syl-text" className="mb-1 block text-[12px] text-low">Or paste the syllabus text</label>
              <textarea
                id="syl-text"
                value={text}
                disabled={!!file}
                onChange={(e) => { setText(e.target.value); setError('') }}
                rows={6}
                className={`w-full font-mono disabled:opacity-40 ${FIELD}`}
              />
            </div>
            <div>
              <label htmlFor="syl-start" className="mb-1 block text-[12px] text-low">Term start date (optional, helps resolve "Week 3" style dates)</label>
              <input id="syl-start" type="date" value={termStart} onChange={(e) => setTermStart(e.target.value)} className={FIELD} />
            </div>
            <Btn kind="primary" disabled={!hasSource} onClick={() => void read()}>Read syllabus</Btn>
          </>
        ) : (
          <>
            {preview.warnings.length > 0 && (
              <ul className="space-y-1" aria-label="Warnings">
                {preview.warnings.map((w, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-[12.5px] text-pend">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden /> {w}
                  </li>
                ))}
              </ul>
            )}

            {preview.grading.length > 0 && (
              <div>
                <p className="label-mono mb-1">grading breakdown</p>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {preview.grading.map((g, i) => (
                    <Mono key={i} className="text-mid">{g.category} {g.weight}%</Mono>
                  ))}
                </div>
              </div>
            )}

            {rows.length === 0 ? (
              <EmptyState title="No assignments found." hint="Try pasting the schedule section on its own." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left">
                  <thead>
                    <tr className="label-mono">
                      <th className="w-8 py-1 font-normal"><span className="sr-only">Include</span></th>
                      <th className="py-1 font-normal">title</th>
                      <th className="py-1 font-normal">kind</th>
                      <th className="py-1 font-normal">due</th>
                      <th className="py-1 font-normal">weight %</th>
                      <th className="py-1 pl-2 font-normal">points</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className={r.checked ? '' : 'opacity-60'}>
                        <td className="py-1 pr-2">
                          <input
                            type="checkbox"
                            checked={r.checked}
                            onChange={(e) => patch(i, { checked: e.target.checked })}
                            aria-label={`Include ${r.title || 'item'}`}
                          />
                        </td>
                        <td className="py-1 pr-2">
                          <input
                            value={r.title}
                            onChange={(e) => patch(i, { title: e.target.value })}
                            aria-label="Title"
                            aria-invalid={r.checked && !r.title.trim()}
                            className={`w-full ${FIELD}`}
                          />
                        </td>
                        <td className="py-1 pr-2">
                          <input
                            value={r.kind}
                            onChange={(e) => patch(i, { kind: e.target.value })}
                            aria-label="Kind"
                            className={`w-[100px] ${FIELD}`}
                          />
                        </td>
                        <td className="py-1 pr-2">
                          <input
                            type="date"
                            value={r.due ?? ''}
                            onChange={(e) => patch(i, { due: e.target.value || null })}
                            aria-label={`Due date for ${r.title || 'item'}`}
                            className={FIELD}
                          />
                          {!r.due && <Mono className="ml-2 text-pend">no date</Mono>}
                        </td>
                        <td className="py-1">
                          <input
                            type="number"
                            min={0}
                            max={100}
                            value={r.weight ?? ''}
                            onChange={(e) => patch(i, { weight: e.target.value === '' ? null : Number(e.target.value) })}
                            aria-label={`Weight for ${r.title || 'item'}`}
                            aria-invalid={r.checked && badWeight(r.weight)}
                            className={`w-[72px] text-right ${FIELD} ${r.checked && badWeight(r.weight) ? 'border-fail' : ''}`}
                          />
                        </td>
                        <td className="py-1 pl-2">
                          <Mono className="text-mid">{r.points ?? ''}</Mono>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {rows.length > 0 && (
              <div className="flex flex-wrap items-end gap-3 border-t border-hairline pt-3">
                <div>
                  <label htmlFor="syl-target" className="mb-1 block text-[12px] text-low">Add to</label>
                  <select id="syl-target" value={target} onChange={(e) => setTarget(e.target.value)} className={FIELD}>
                    <option value={NEW}>New course</option>
                    {courses.map((c) => <option key={c.id} value={c.id}>{c.name}{c.term ? ` (${c.term})` : ''}</option>)}
                  </select>
                </div>
                {target === NEW && (
                  <>
                    <div>
                      <label htmlFor="syl-name" className="mb-1 block text-[12px] text-low">Course name</label>
                      <input id="syl-name" value={newName} onChange={(e) => setNewName(e.target.value)} className={`w-[220px] ${FIELD}`} />
                    </div>
                    <div>
                      <label htmlFor="syl-term" className="mb-1 block text-[12px] text-low">Term (required)</label>
                      <input id="syl-term" required aria-required="true" value={newTerm} onChange={(e) => setNewTerm(e.target.value)} placeholder="Fall 2026" className={`w-[130px] ${FIELD}`} />
                    </div>
                  </>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              {rows.length > 0 && (
                <Btn kind="primary" disabled={busy || selected.length === 0 || invalid || !targetOk || !weightsOk} onClick={() => void apply()}>
                  {busy ? 'Adding…' : `Add ${selected.length} assignment${selected.length === 1 ? '' : 's'}`}
                </Btn>
              )}
              <Btn onClick={restart}>Start over</Btn>
              {invalid && <Mono className="text-pend">every checked item needs a title</Mono>}
              {!weightsOk && <Mono className="text-pend">weights must be between 0 and 100 (point values go in the points column)</Mono>}
              {rows.length > 0 && target === NEW && !targetOk && newName.trim() !== '' && <Mono className="text-pend">enter a term, e.g. Fall 2026</Mono>}
            </div>
          </>
        )}
      </div>
    </Panel>
  )
}
