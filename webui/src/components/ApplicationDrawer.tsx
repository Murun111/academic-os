import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Archive, ArchiveRestore, Check, Plus, Trash2, X } from 'lucide-react'
import { documentsApi, type Document } from '../lib/documentsApi'
import {
  applicationsApi, APPLICATION_TYPES,
  type Application, type ApplicationStatus, type ApplicationType,
} from '../lib/applicationsApi'
import { Btn, Mono, Pill } from './ui'

export const STATUS_LABEL: Record<ApplicationStatus, string> = {
  researching: 'Researching',
  preparing: 'Preparing',
  submitted: 'Submitted',
  secondaries: 'Secondaries',
  interview: 'Interview',
  decision: 'Decision',
}

function daysUntil(deadline: string): number {
  return Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000)
}

export function DeadlineLabel({ deadline }: { deadline: string | null }) {
  if (!deadline) return null
  const days = daysUntil(deadline)
  const urgent = days < 7
  return (
    <Mono className={urgent ? 'text-fail' : 'text-low'}>
      {deadline} · {days < 0 ? 'overdue' : `${days}d`}
    </Mono>
  )
}

interface ApplicationDrawerProps {
  item: Application
  busy: boolean
  setBusy: (busy: boolean) => void
  // whether the stage config has a seed checklist for this item's type
  canSeedChecklist: boolean
  // stage+track-aware requirement template lookup
  templateFor: (type: ApplicationType) => string[] | undefined
  onClose: () => void
  // re-fetch the page's data after any mutation
  onChanged: () => Promise<void>
}

export function ApplicationDrawer({
  item, busy, setBusy, canSeedChecklist, templateFor, onClose, onChanged,
}: ApplicationDrawerProps) {
  const [newReqLabel, setNewReqLabel] = useState('')
  const [amountDraft, setAmountDraft] = useState('')
  const [feeDraft, setFeeDraft] = useState('')
  const [notesDraft, setNotesDraft] = useState('')
  const [nameDraft, setNameDraft] = useState('')
  const [orgDraft, setOrgDraft] = useState('')
  const [urlDraft, setUrlDraft] = useState('')
  // documents linked to the open card + everything available to link
  const [linkedDocs, setLinkedDocs] = useState<Document[]>([])
  const [allDocs, setAllDocs] = useState<Document[]>([])
  // two-click delete: first click arms, second deletes, auto-disarms after 3s
  const [confirmDelete, setConfirmDelete] = useState(false)
  const confirmTimer = useRef<number | null>(null)

  useEffect(() => () => { if (confirmTimer.current) window.clearTimeout(confirmTimer.current) }, [])

  // sync drafts whenever the drawer selection changes
  useEffect(() => {
    setAmountDraft(item.amount == null ? '' : String(item.amount))
    setFeeDraft(item.app_fee == null ? '' : String(item.app_fee))
    setNotesDraft(item.notes ?? '')
    setNameDraft(item.name ?? '')
    setOrgDraft(item.org ?? '')
    setUrlDraft(item.url ?? '')
    setConfirmDelete(false)
  }, [item.id])

  // linked documents for the open card, plus the pool of everything linkable
  const loadDocs = useCallback(async (appId: string) => {
    const [linked, all] = await Promise.all([
      documentsApi.list({ application_id: appId }), documentsApi.list(),
    ])
    setLinkedDocs(linked)
    setAllDocs(all)
  }, [])

  useEffect(() => { void loadDocs(item.id) }, [item.id, loadDocs])

  const linkDoc = async (docId: string) => {
    if (!docId) return
    await documentsApi.link(docId, item.id)
    await loadDocs(item.id)
  }

  const unlinkDoc = async (docId: string) => {
    await documentsApi.unlink(docId, item.id)
    await loadDocs(item.id)
  }

  const linkedDocIds = new Set(linkedDocs.map((d) => d.id))
  const unlinkedDocs = allDocs.filter((d) => !linkedDocIds.has(d.id))

  const patch = async (fields: Parameters<typeof applicationsApi.update>[1]) => {
    await applicationsApi.update(item.id, fields)
    await onChanged()
  }

  const commitName2 = async () => {
    if (!nameDraft.trim() || nameDraft.trim() === item.name) return
    await patch({ name: nameDraft.trim() })
  }

  const commitAmount = async () => {
    const trimmed = amountDraft.trim()
    const parsed = trimmed === '' ? null : Number(trimmed)
    const next = parsed === null || Number.isNaN(parsed) ? null : parsed
    if (next === item.amount) return
    await applicationsApi.update(item.id, { amount: next })
    await onChanged()
  }

  const commitFee = async () => {
    const trimmed = feeDraft.trim()
    const parsed = trimmed === '' ? null : Number(trimmed)
    const next = parsed === null || Number.isNaN(parsed) ? null : parsed
    if (next === item.app_fee) return
    await applicationsApi.update(item.id, { app_fee: next })
    await onChanged()
  }

  const toggleFeeWaived = async (feeWaived: boolean) => {
    await applicationsApi.update(item.id, { fee_waived: feeWaived })
    await onChanged()
  }

  const commitNotes = async () => {
    if (notesDraft === item.notes) return
    await applicationsApi.update(item.id, { notes: notesDraft })
    await onChanged()
  }

  const toggleRequirement = async (reqId: string, done: boolean) => {
    await applicationsApi.updateRequirement(item.id, reqId, { done: !done })
    await onChanged()
  }

  const seedChecklist = async () => {
    // for cards that arrived without one (agent-found, synced) — seed the
    // stage template for this type
    const template = templateFor(item.type)
    if (!template) return
    setBusy(true)
    for (const label of template) {
      await applicationsApi.addRequirement(item.id, label)
    }
    setBusy(false)
    await onChanged()
  }

  const addRequirement = async () => {
    if (!newReqLabel.trim()) return
    await applicationsApi.addRequirement(item.id, newReqLabel.trim())
    setNewReqLabel('')
    await onChanged()
  }

  const deleteRequirement = async (reqId: string) => {
    await applicationsApi.deleteRequirement(item.id, reqId)
    await onChanged()
  }

  const removeApplication = async () => {
    await applicationsApi.remove(item.id)
    onClose()
    await onChanged()
  }

  const clickDelete = () => {
    if (!confirmDelete) {
      setConfirmDelete(true)
      confirmTimer.current = window.setTimeout(() => {
        setConfirmDelete(false)
        confirmTimer.current = null
      }, 3000)
      return
    }
    if (confirmTimer.current) {
      window.clearTimeout(confirmTimer.current)
      confirmTimer.current = null
    }
    setConfirmDelete(false)
    void removeApplication()
  }

  return (
    <motion.aside
      className="glass-strong fixed top-4 right-4 bottom-4 z-30 flex w-[400px] max-w-[calc(100vw-2rem)] flex-col overflow-y-auto rounded-[18px] p-6"
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 16 }}
      transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <input
          value={nameDraft}
          onChange={(e) => setNameDraft(e.target.value)}
          onBlur={() => void commitName2()}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          className="-mx-1 w-full rounded-md px-1 text-[17px] font-semibold tracking-[-0.01em] text-hi outline-none hover:bg-ink/4 focus:bg-ink/4"
          aria-label="Application name"
        />
        <button onClick={onClose} className="text-low hover:text-mid"><X size={16} /></button>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <p className="label-mono mb-1">type</p>
          <select
            value={item.type}
            onChange={(e) => void patch({ type: e.target.value as ApplicationType })}
            className="rounded-lg border border-line bg-raise2 px-2 py-1.5 text-[12.5px] text-hi outline-none focus:border-ink/25"
          >
            {APPLICATION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <p className="label-mono mb-1">deadline</p>
          <input
            type="date"
            value={item.deadline ?? ''}
            onChange={(e) => void patch({ deadline: e.target.value || null })}
            className="rounded-lg border border-line bg-raise2 px-2 py-1.5 text-[12.5px] text-hi outline-none focus:border-ink/25"
          />
        </div>
        <div className="flex flex-col items-start gap-1 pb-0.5">
          <Pill>{STATUS_LABEL[item.status]}</Pill>
          {item.deadline && <DeadlineLabel deadline={item.deadline} />}
        </div>
      </div>

      {item.status === 'decision' && (
        <div className="mb-4">
          <p className="label-mono mb-1">result</p>
          <select
            value={item.decision_result}
            onChange={(e) => void patch({ decision_result: e.target.value as Application['decision_result'] })}
            className="rounded-lg border border-line bg-raise2 px-2 py-1.5 text-[12.5px] text-hi outline-none focus:border-ink/25"
          >
            <option value="">undecided</option>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
            <option value="waitlisted">waitlisted</option>
          </select>
        </div>
      )}

      <div className="mb-4 flex gap-3">
        <div className="flex-1">
          <p className="label-mono mb-1">school / funder</p>
          <input
            value={orgDraft}
            onChange={(e) => setOrgDraft(e.target.value)}
            onBlur={() => { if (orgDraft !== item.org) void patch({ org: orgDraft }) }}
            placeholder="e.g. Stanford"
            className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[12.5px] text-hi outline-none placeholder:text-low focus:border-ink/25"
          />
        </div>
        <div className="flex-1">
          <p className="label-mono mb-1">link</p>
          <input
            value={urlDraft}
            onChange={(e) => setUrlDraft(e.target.value)}
            onBlur={() => { if (urlDraft !== item.url) void patch({ url: urlDraft }) }}
            placeholder="https://…"
            className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[12.5px] text-hi outline-none placeholder:text-low focus:border-ink/25"
          />
        </div>
      </div>

      <div className="mb-4 flex items-end gap-3">
        <div className="flex-1">
          <p className="label-mono mb-1">amount</p>
          <input
            type="number"
            min={0}
            value={amountDraft}
            onChange={(e) => setAmountDraft(e.target.value)}
            onBlur={() => void commitAmount()}
            placeholder="0"
            className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-ink/25"
          />
        </div>
        <div className="flex-1">
          <p className="label-mono mb-1">app fee</p>
          <input
            type="number"
            min={0}
            value={feeDraft}
            onChange={(e) => setFeeDraft(e.target.value)}
            onBlur={() => void commitFee()}
            placeholder="0"
            className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-ink/25"
          />
        </div>
      </div>

      <label className="mb-4 flex items-center gap-2">
        <input
          type="checkbox"
          checked={item.fee_waived}
          onChange={(e) => void toggleFeeWaived(e.target.checked)}
          className="size-3.5 accent-ink/70"
        />
        <span className="text-[12.5px] text-mid">fee waived</span>
      </label>

      <div className="mb-4">
        <p className="label-mono mb-2">requirements</p>
        <div className="flex flex-col gap-1.5">
          {item.requirements.length === 0 && (
            canSeedChecklist ? (
              <Btn onClick={() => void seedChecklist()} disabled={busy}>
                {busy ? 'Adding…' : `Add ${item.type} checklist`}
              </Btn>
            ) : (
              <Mono className="text-low">none yet</Mono>
            )
          )}
          {item.requirements.map((r) => (
            <div key={r.id} className="flex items-center gap-2">
              <button
                onClick={() => void toggleRequirement(r.id, r.done)}
                className={`flex size-4 shrink-0 items-center justify-center rounded border border-line ${r.done ? 'bg-ink/12 text-hi' : 'text-transparent'}`}
              >
                <Check size={11} />
              </button>
              <span className={`flex-1 text-[12.5px] ${r.done ? 'text-low line-through' : 'text-mid'}`}>{r.label}</span>
              <button onClick={() => void deleteRequirement(r.id)} className="text-low hover:text-fail">
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          <input
            value={newReqLabel}
            onChange={(e) => setNewReqLabel(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void addRequirement() }}
            placeholder="Add requirement…"
            className="flex-1 rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[12.5px] text-hi outline-none focus:border-ink/25"
          />
          <Btn onClick={() => void addRequirement()} disabled={!newReqLabel.trim()}><Plus size={13} /></Btn>
        </div>
      </div>

      <div className="mb-4">
        <p className="label-mono mb-2">essays &amp; documents</p>
        <div className="flex flex-col gap-1.5">
          {linkedDocs.length === 0 && (
            <Mono className="text-low">nothing linked yet</Mono>
          )}
          {linkedDocs.map((d) => (
            <div key={d.id} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-[12.5px] text-mid">{d.title}</span>
              <Pill>{d.kind}</Pill>
              <button
                onClick={() => void unlinkDoc(d.id)}
                title="Unlink this document"
                className="shrink-0 text-low hover:text-fail"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
        {unlinkedDocs.length > 0 && (
          <select
            value=""
            onChange={(e) => void linkDoc(e.target.value)}
            className="mt-2 w-full rounded-lg border border-line bg-raise2 px-2 py-1.5 text-[12.5px] text-mid outline-none focus:border-ink/25"
          >
            <option value="">Link a document…</option>
            {unlinkedDocs.map((d) => (
              <option key={d.id} value={d.id}>{d.title} · {d.kind}</option>
            ))}
          </select>
        )}
        {allDocs.length === 0 && (
          <p className="mt-2 text-[12px] text-low">
            Add essays and files in <Link to="/documents" className="underline decoration-dotted">Documents</Link>, then link them here.
          </p>
        )}
      </div>

      <div className="mb-4">
        <p className="label-mono mb-1.5">description</p>
        <textarea
          value={notesDraft}
          onChange={(e) => setNotesDraft(e.target.value)}
          onBlur={() => void commitNotes()}
          placeholder="What is this? Award details, why it's a fit, who to ask for letters…"
          rows={4}
          className="w-full resize-y rounded-lg border border-line bg-raise2 px-3 py-2 text-[12.5px] leading-relaxed text-hi outline-none placeholder:text-low focus:border-ink/25"
        />
      </div>

      {item.url && (
        <a href={item.url} target="_blank" rel="noreferrer" className="mb-4 block font-mono text-[11px] text-low hover:text-mid">
          {item.url}
        </a>
      )}

      <div className="mt-auto flex items-center gap-2">
        <Btn
          onClick={() => {
            void patch({ archived: !item.archived })
            onClose()
          }}
        >
          <span className="flex items-center gap-1.5">
            {item.archived
              ? <><ArchiveRestore size={13} /> Restore</>
              : <><Archive size={13} /> Archive</>}
          </span>
        </Btn>
        <Btn kind="danger" onClick={clickDelete}>
          <span className="flex items-center gap-1.5">
            <Trash2 size={13} /> {confirmDelete ? 'Sure? Delete' : 'Delete'}
          </span>
        </Btn>
      </div>
    </motion.aside>
  )
}
