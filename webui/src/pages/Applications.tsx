import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, ArrowRight, Calendar, Check, Plus, Trash2, X } from 'lucide-react'
import {
  applicationsApi, APPLICATION_STATUSES, APPLICATION_TYPES, requirementsProgress,
  type Application, type ApplicationCosts, type ApplicationStatus, type ApplicationType,
} from '../lib/applicationsApi'
import { useOs } from '../lib/store'
import { stageConfig } from '../lib/stageConfig'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../components/ui'

const STATUS_LABEL: Record<ApplicationStatus, string> = {
  researching: 'Researching',
  preparing: 'Preparing',
  submitted: 'Submitted',
  interview: 'Interview',
  decision: 'Decision',
}

const DECISION_TONE: Record<string, string> = {
  accepted: 'running',
  rejected: 'failed',
  waitlisted: 'pending',
}

function daysUntil(deadline: string): number {
  return Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000)
}

function formatUsd(amount: number): string {
  return `$${Math.round(amount).toLocaleString()}`
}

function DeadlineLabel({ deadline }: { deadline: string | null }) {
  if (!deadline) return null
  const days = daysUntil(deadline)
  const urgent = days < 7
  return (
    <Mono className={urgent ? 'text-fail' : 'text-low'}>
      {deadline} · {days < 0 ? 'overdue' : `${days}d`}
    </Mono>
  )
}

export function Applications() {
  const stage = useOs((s) => s.stage)
  const cfg = stageConfig(stage)
  const [items, setItems] = useState<Application[]>([])
  const [deadlines, setDeadlines] = useState<Application[]>([])
  const [costs, setCosts] = useState<ApplicationCosts | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [formName, setFormName] = useState('')
  const [formType, setFormType] = useState<ApplicationType>(cfg.defaultType)
  const [formDeadline, setFormDeadline] = useState('')
  const [newReqLabel, setNewReqLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [amountDraft, setAmountDraft] = useState('')
  const [feeDraft, setFeeDraft] = useState('')

  const load = useCallback(async () => {
    try {
      const [list, soon, costsRes] = await Promise.all([
        applicationsApi.list(), applicationsApi.deadlines(30), applicationsApi.costs(),
      ])
      setItems(list)
      setDeadlines(soon)
      setCosts(costsRes)
      setError(false)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  // keep the form's default type in sync when the stage loads or changes
  useEffect(() => { setFormType(cfg.defaultType) }, [cfg.defaultType])

  const selectedItem = items.find((i) => i.id === selected) ?? null
  const columns = APPLICATION_STATUSES.map((status) => ({ status, items: items.filter((i) => i.status === status) }))

  // sync money drafts whenever the drawer selection changes
  useEffect(() => {
    setAmountDraft(selectedItem?.amount == null ? '' : String(selectedItem.amount))
    setFeeDraft(selectedItem?.app_fee == null ? '' : String(selectedItem.app_fee))
  }, [selectedItem?.id])

  const commitAmount = async () => {
    if (!selectedItem) return
    const trimmed = amountDraft.trim()
    const parsed = trimmed === '' ? null : Number(trimmed)
    const next = parsed === null || Number.isNaN(parsed) ? null : parsed
    if (next === selectedItem.amount) return
    await applicationsApi.update(selectedItem.id, { amount: next })
    await load()
  }

  const commitFee = async () => {
    if (!selectedItem) return
    const trimmed = feeDraft.trim()
    const parsed = trimmed === '' ? null : Number(trimmed)
    const next = parsed === null || Number.isNaN(parsed) ? null : parsed
    if (next === selectedItem.app_fee) return
    await applicationsApi.update(selectedItem.id, { app_fee: next })
    await load()
  }

  const toggleFeeWaived = async (feeWaived: boolean) => {
    if (!selectedItem) return
    await applicationsApi.update(selectedItem.id, { fee_waived: feeWaived })
    await load()
  }

  const moveStatus = async (item: Application, dir: 1 | -1) => {
    const idx = APPLICATION_STATUSES.indexOf(item.status)
    const next = APPLICATION_STATUSES[idx + dir]
    if (!next) return
    await applicationsApi.update(item.id, { status: next })
    await load()
  }

  const submitForm = async () => {
    if (!formName.trim()) return
    setBusy(true)
    const created = await applicationsApi.create({ name: formName.trim(), type: formType, deadline: formDeadline || null })
    // stage-aware requirement template: seed the checklist for this type
    const template = cfg.requirementTemplates[formType]
    if (created && template) {
      for (const label of template) {
        await applicationsApi.addRequirement(created.id, label)
      }
    }
    setFormName('')
    setFormDeadline('')
    setShowForm(false)
    setBusy(false)
    await load()
  }

  const toggleRequirement = async (item: Application, reqId: string, done: boolean) => {
    await applicationsApi.updateRequirement(item.id, reqId, { done: !done })
    await load()
  }

  const addRequirement = async () => {
    if (!selectedItem || !newReqLabel.trim()) return
    await applicationsApi.addRequirement(selectedItem.id, newReqLabel.trim())
    setNewReqLabel('')
    await load()
  }

  const deleteRequirement = async (reqId: string) => {
    if (!selectedItem) return
    await applicationsApi.deleteRequirement(selectedItem.id, reqId)
    await load()
  }

  const removeApplication = async () => {
    if (!selectedItem) return
    await applicationsApi.remove(selectedItem.id)
    setSelected(null)
    await load()
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-[1200px]">
        <p className="label-mono">loading applications…</p>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <p className="label-mono mb-1">{cfg.appsSub}</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">{cfg.appsTitle}</h1>
        </div>
        <Btn kind="primary" onClick={() => setShowForm((s) => !s)}>
          <span className="flex items-center gap-1.5"><Plus size={13} /> Add application</span>
        </Btn>
      </div>

      {error && (
        <div className="mb-4 rounded-[10px] border border-hairline px-3 py-2.5">
          <Mono className="text-low">Couldn't reach the applications service — showing what's cached.</Mono>
        </div>
      )}

      <AnimatePresence>
        {showForm && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-6 overflow-hidden"
          >
            <Panel className="p-4">
              <div className="flex flex-wrap items-end gap-3">
                <div className="min-w-[200px] flex-1">
                  <p className="label-mono mb-1">name</p>
                  <input
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="Stanford MS CS"
                    className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-black/25"
                  />
                </div>
                <div>
                  <p className="label-mono mb-1">type</p>
                  <select
                    value={formType}
                    onChange={(e) => setFormType(e.target.value as ApplicationType)}
                    className="rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-black/25"
                  >
                    {APPLICATION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <p className="label-mono mb-1">deadline</p>
                  <input
                    type="date"
                    value={formDeadline}
                    onChange={(e) => setFormDeadline(e.target.value)}
                    className="rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-black/25"
                  />
                </div>
                <Btn kind="primary" onClick={() => void submitForm()} disabled={busy || !formName.trim()}>
                  {busy ? 'Adding…' : 'Add'}
                </Btn>
                <Btn onClick={() => setShowForm(false)}>Cancel</Btn>
              </div>
            </Panel>
          </motion.div>
        )}
      </AnimatePresence>

      <Panel className="mb-6">
        <PanelHead label="next deadlines" right={<Mono className="text-low">{deadlines.length} upcoming</Mono>} />
        {costs && (costs.fees_due > 0 || costs.potential_awards > 0) && (
          <Mono className="-mt-1 block px-5 pb-3 text-low">
            fees due {formatUsd(costs.fees_due)} · potential awards {formatUsd(costs.potential_awards)}
          </Mono>
        )}
        <div className="flex flex-col gap-px px-2 pb-3">
          {deadlines.length === 0 && <EmptyState title="No deadlines in the next 30 days." />}
          {deadlines.slice(0, 3).map((d) => (
            <button
              key={d.id}
              onClick={() => setSelected(d.id)}
              className="flex items-center gap-3 rounded-[10px] px-3 py-2 text-left hover:bg-black/4"
            >
              <Calendar size={13} className="shrink-0 text-low" />
              <span className="flex-1 truncate text-[12.5px] text-mid">{d.name}</span>
              <Pill>{d.type}</Pill>
              <DeadlineLabel deadline={d.deadline} />
            </button>
          ))}
        </div>
      </Panel>

      {items.length === 0 ? (
        <EmptyState title="No applications yet." hint="Add your first application to start the pipeline." />
      ) : (
        <div className="overflow-x-auto pb-2">
          <div className="flex min-w-max gap-3">
            {columns.map(({ status, items: colItems }) => (
              <div key={status} className="w-[220px] shrink-0">
                <div className="mb-2 flex items-center justify-between px-1">
                  <span className="label-mono">{STATUS_LABEL[status]}</span>
                  <Mono className="text-low">{colItems.length}</Mono>
                </div>
                <div className="flex flex-col gap-2">
                  {colItems.map((item) => {
                    const idx = APPLICATION_STATUSES.indexOf(item.status)
                    return (
                      <div
                        key={item.id}
                        className={`panel px-3 py-2.5 transition-colors duration-150 hover:bg-raise2 ${selected === item.id ? 'border-black/15' : ''}`}
                      >
                        <button onClick={() => setSelected(item.id === selected ? null : item.id)} className="mb-1.5 block w-full text-left">
                          <span className="mb-1 block truncate text-[13px] text-hi">{item.name}</span>
                          <div className="flex items-center gap-2">
                            <Pill>{item.type}</Pill>
                            {item.amount != null && <Pill>{formatUsd(item.amount)}</Pill>}
                            {item.requirements.length > 0 && (
                              <Mono className="text-low">{requirementsProgress(item.requirements)}</Mono>
                            )}
                          </div>
                          {item.deadline && <div className="mt-1"><DeadlineLabel deadline={item.deadline} /></div>}
                        </button>
                        <div className="flex items-center gap-1">
                          <Btn onClick={() => void moveStatus(item, -1)} disabled={idx === 0}>
                            <ArrowLeft size={12} />
                          </Btn>
                          <Btn onClick={() => void moveStatus(item, 1)} disabled={idx === APPLICATION_STATUSES.length - 1}>
                            <ArrowRight size={12} />
                          </Btn>
                        </div>
                      </div>
                    )
                  })}
                  {colItems.length === 0 && (
                    <div className="rounded-[10px] border border-dashed border-hairline py-4 text-center">
                      <Mono className="text-low">empty</Mono>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <AnimatePresence>
        {selectedItem && (
          <motion.aside
            className="glass-strong fixed top-4 right-4 bottom-4 z-30 flex w-[400px] max-w-[calc(100vw-2rem)] flex-col overflow-y-auto rounded-[18px] p-6"
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 16 }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="mb-1 flex items-start justify-between gap-3">
              <h2 className="text-[17px] font-semibold tracking-[-0.01em]">{selectedItem.name}</h2>
              <button onClick={() => setSelected(null)} className="text-low hover:text-mid"><X size={16} /></button>
            </div>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <Pill>{selectedItem.type}</Pill>
              <Pill>{STATUS_LABEL[selectedItem.status]}</Pill>
              {selectedItem.decision_result && (
                <Pill tone={DECISION_TONE[selectedItem.decision_result]}>{selectedItem.decision_result}</Pill>
              )}
              {selectedItem.org && <Mono className="text-low">{selectedItem.org}</Mono>}
            </div>

            {selectedItem.deadline && (
              <div className="mb-4">
                <p className="label-mono mb-1">deadline</p>
                <DeadlineLabel deadline={selectedItem.deadline} />
              </div>
            )}

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
                  className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-black/25"
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
                  className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-black/25"
                />
              </div>
            </div>

            <label className="mb-4 flex items-center gap-2">
              <input
                type="checkbox"
                checked={selectedItem.fee_waived}
                onChange={(e) => void toggleFeeWaived(e.target.checked)}
                className="size-3.5 accent-black/70"
              />
              <span className="text-[12.5px] text-mid">fee waived</span>
            </label>

            <div className="mb-4">
              <p className="label-mono mb-2">requirements</p>
              <div className="flex flex-col gap-1.5">
                {selectedItem.requirements.length === 0 && <Mono className="text-low">none yet</Mono>}
                {selectedItem.requirements.map((r) => (
                  <div key={r.id} className="flex items-center gap-2">
                    <button
                      onClick={() => void toggleRequirement(selectedItem, r.id, r.done)}
                      className={`flex size-4 shrink-0 items-center justify-center rounded border border-line ${r.done ? 'bg-black/12 text-hi' : 'text-transparent'}`}
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
                  className="flex-1 rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[12.5px] text-hi outline-none focus:border-black/25"
                />
                <Btn onClick={() => void addRequirement()} disabled={!newReqLabel.trim()}><Plus size={13} /></Btn>
              </div>
            </div>

            {selectedItem.notes && (
              <div className="mb-4">
                <p className="label-mono mb-1.5">notes</p>
                <p className="text-[12.5px] leading-relaxed text-mid">{selectedItem.notes}</p>
              </div>
            )}

            {selectedItem.url && (
              <a href={selectedItem.url} target="_blank" rel="noreferrer" className="mb-4 block font-mono text-[11px] text-low hover:text-mid">
                {selectedItem.url}
              </a>
            )}

            <Btn kind="danger" className="mt-auto" onClick={() => void removeApplication()}>
              <span className="flex items-center gap-1.5"><Trash2 size={13} /> Delete</span>
            </Btn>
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  )
}
