// Scholarship CSV import: upload or paste, dry-run preview, then import.
import { useRef, useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { applicationsApi, type ScholarshipImportResult } from '../lib/applicationsApi'
import { Btn, EmptyState, Panel, PanelHead } from './ui'

const TEMPLATE_HEADER = 'name,organization,amount,deadline,url,notes,eligibility,renewable'

export function ScholarshipImport({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [preview, setPreview] = useState<ScholarshipImportResult | null>(null)
  const [result, setResult] = useState<ScholarshipImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [running, setRunning] = useState<'preview' | 'import' | null>(null)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const source = (): File | string | null => (file ? file : text.trim() ? text : null)

  const reset = () => { setPreview(null); setResult(null); setError('') }

  const downloadTemplate = () => {
    const blob = new Blob([TEMPLATE_HEADER + '\n'], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'scholarships-template.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const run = async (dryRun: boolean) => {
    const src = source()
    if (!src) return
    setBusy(true); setRunning(dryRun ? 'preview' : 'import'); setError('')
    const res = await applicationsApi.importScholarshipsCsv(src, dryRun)
    setBusy(false); setRunning(null)
    if ('error' in res && 'ok' in res) { setError(String(res.error)); return }
    const okRes = res as ScholarshipImportResult
    if (dryRun) { setPreview(okRes); setResult(null) }
    else { setResult(okRes); setPreview(null); setFile(null); setText(''); if (fileRef.current) fileRef.current.value = ''; onDone() }
  }

  return (
    <Panel>
      <PanelHead label="Import scholarships from CSV" />
      <div className="space-y-3 p-4">
        <p className="text-[12px] text-low">
          Columns: name, organization, amount, deadline, url, notes, eligibility, renewable.
          Deadlines accept 2026-03-01, M/D/YYYY (US order: 3/4/2026 is March 4), or "March 1, 2026" in quotes. Quote any value that contains a comma, such as "$1,500".
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium text-mid transition-colors hover:bg-ink/5 hover:text-hi focus-within:ring-2 focus-within:ring-ink/20">
            <Upload size={14} aria-hidden />
            {file ? file.name : 'Choose .csv file'}
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={e => { setFile(e.target.files?.[0] ?? null); reset() }}
            />
          </label>
          <Btn onClick={downloadTemplate}>
            <span className="inline-flex items-center gap-1.5"><Download size={14} aria-hidden />Download a blank template</span>
          </Btn>
        </div>

        <div>
          <label htmlFor="sch-import-text" className="mb-1 block text-[12px] text-low">Or paste rows</label>
          <textarea
            id="sch-import-text"
            value={text}
            disabled={!!file}
            onChange={e => { setText(e.target.value); reset() }}
            rows={5}
            placeholder={`${TEMPLATE_HEADER}\nExample Award,Example Foundation,2500,2026-03-01,,,,false`}
            className="w-full rounded-lg border border-line bg-raise2 p-2 font-mono text-[12px] text-hi outline-none focus:border-ink/30 disabled:opacity-40"
          />
          {file && (
            <button
              type="button"
              className="text-[12px] text-low underline hover:text-hi"
              onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ''; reset() }}
            >
              Remove file to paste instead
            </button>
          )}
        </div>

        <div className="flex gap-2">
          <Btn onClick={() => void run(true)} disabled={busy || !source()}>{running === 'preview' ? 'Checking…' : 'Preview'}</Btn>
          <Btn kind="primary" onClick={() => void run(false)} disabled={busy || !preview || preview.rows?.length === 0}>
            {running === 'import' ? 'Importing…' : 'Import'}
          </Btn>
        </div>

        <div role="status" aria-live="polite">
          {error && <p className="text-[13px] text-fail">{error}</p>}
        </div>

        {preview && (
          <div className="space-y-2">
            <p className="text-[13px] text-mid">
              {preview.rows?.length ?? preview.created} ready to import, {preview.skipped_duplicates} duplicates skipped, {preview.errors.length} with errors.
            </p>
            {preview.rows && preview.rows.length > 0 ? (
              <div className="overflow-x-auto rounded-lg border border-line">
                <table className="w-full text-left text-[12px]">
                  <caption className="sr-only">Preview of scholarships to import</caption>
                  <thead className="text-low">
                    <tr>
                      <th scope="col" className="px-2 py-1">Row</th>
                      <th scope="col" className="px-2 py-1">Name</th>
                      <th scope="col" className="px-2 py-1">Organization</th>
                      <th scope="col" className="px-2 py-1">Amount</th>
                      <th scope="col" className="px-2 py-1">Deadline</th>
                    </tr>
                  </thead>
                  <tbody className="text-hi">
                    {preview.rows.map(r => (
                      <tr key={r.row} className="border-t border-line">
                        <td className="px-2 py-1 font-mono text-low">{r.row}</td>
                        <td className="px-2 py-1">{r.name}</td>
                        <td className="px-2 py-1">{r.org || '-'}</td>
                        <td className="px-2 py-1">{r.amount != null ? `$${r.amount.toLocaleString()}` : '-'}</td>
                        <td className="px-2 py-1">{r.deadline ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="No new rows to import" hint="Everything was a duplicate or had errors." />
            )}
            {preview.errors.length > 0 && (
              <ul className="space-y-0.5 text-[12px] text-fail">
                {preview.errors.map((e, i) => <li key={i}>Row {e.row}: {e.message}</li>)}
              </ul>
            )}
          </div>
        )}

        {result && (
          <div className="space-y-1" role="status">
            <p className="text-[13px] text-hi">
              Imported {result.created}. Skipped {result.skipped_duplicates} duplicates. {result.errors.length} errors.
            </p>
            {result.errors.length > 0 && (
              <ul className="space-y-0.5 text-[12px] text-fail">
                {result.errors.map((e, i) => <li key={i}>Row {e.row}: {e.message}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>
    </Panel>
  )
}
