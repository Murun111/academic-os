import { useCallback, useEffect, useState, type DragEvent, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, ArrowRight, Calendar, Landmark, Plus, Search } from 'lucide-react'
import {
  applicationsApi, APPLICATION_STATUSES, APPLICATION_TYPES, requirementsProgress,
  type Application, type ApplicationCosts, type ApplicationStatus, type ApplicationType,
} from '../lib/applicationsApi'
import { useOs } from '../lib/store'
import { stageConfig } from '../lib/stageConfig'
import { trackApplies, trackConfig } from '../lib/trackConfig'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../components/ui'
import { ApplicationDrawer, DeadlineLabel, STATUS_LABEL } from '../components/ApplicationDrawer'
import { createFafsa, FAFSA_STAGES, ScholarshipScout } from '../components/ScholarshipScout'

// human labels for the type filter tabs
const TYPE_LABEL: Record<ApplicationType, string> = {
  undergrad: 'Colleges',
  grad: 'Programs',
  scholarship: 'Scholarships',
  exchange: 'Exchange',
}

function formatUsd(amount: number): string {
  return `$${Math.round(amount).toLocaleString()}`
}

export function Applications() {
  const stage = useOs((s) => s.stage)
  const track = useOs((s) => s.track)
  const cfg = stageConfig(stage)
  // track tailoring layers on top of the stage config (pre-med → "Med Schools" etc.)
  const trackCfg = trackApplies(stage) ? trackConfig(track) : null
  const appsTitle = trackCfg?.appsTitle ?? cfg.appsTitle
  const appsSub = trackCfg?.appsSub ?? cfg.appsSub
  const templateFor = (type: ApplicationType) =>
    trackCfg?.requirementTemplates?.[type] ?? cfg.requirementTemplates[type]
  const [items, setItems] = useState<Application[]>([])
  const [deadlines, setDeadlines] = useState<Application[]>([])
  const [costs, setCosts] = useState<ApplicationCosts | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [formName, setFormName] = useState('')
  const [formType, setFormType] = useState<ApplicationType>(cfg.defaultType)
  const [formDeadline, setFormDeadline] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragId, setDragId] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState<ApplicationStatus | null>(null)
  const [showScout, setShowScout] = useState(false)

  // every applicationsApi call degrades to a safe fallback, so this never throws
  const load = useCallback(async () => {
    const [list, soon, costsRes] = await Promise.all([
      applicationsApi.list(), applicationsApi.deadlines(30), applicationsApi.costs(),
    ])
    setItems(list)
    setDeadlines(soon)
    setCosts(costsRes)
    setLoading(false)
  }, [])

  useEffect(() => { void load() }, [load])

  // deep link: other pages navigate to /applications?open=<id> — open that card once
  const [searchParams, setSearchParams] = useSearchParams()
  useEffect(() => {
    if (loading) return
    const open = searchParams.get('open')
    if (!open) return
    if (items.some((i) => i.id === open)) setSelected(open)
    const next = new URLSearchParams(searchParams)
    next.delete('open')
    setSearchParams(next, { replace: true })
  }, [loading, items, searchParams, setSearchParams])

  // keep the form's default type in sync when the stage loads or changes
  useEffect(() => { setFormType(cfg.defaultType) }, [cfg.defaultType])

  const selectedItem = items.find((i) => i.id === selected) ?? null

  // type filter tabs — split colleges from scholarships without two pages
  const [typeFilter, setTypeFilter] = useState<ApplicationType | 'all' | 'archived'>('all')
  const activeItems = items.filter((i) => !i.archived)
  const archivedItems = items.filter((i) => i.archived)
  const presentTypes = APPLICATION_TYPES.filter((t) => activeItems.some((i) => i.type === t))
  const visible =
    typeFilter === 'archived' ? archivedItems
    : typeFilter === 'all' ? activeItems
    : activeItems.filter((i) => i.type === typeFilter)
  const visibleDeadlines =
    typeFilter === 'archived' ? []
    : typeFilter === 'all' ? deadlines
    : deadlines.filter((d) => d.type === typeFilter)
  const columns = APPLICATION_STATUSES.map((status) => ({ status, items: visible.filter((i) => i.status === status) }))

  const setStatus = async (id: string, status: ApplicationStatus) => {
    // optimistic move so the card lands in the column instantly
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, status } : i)))
    await applicationsApi.update(id, { status })
    await load()
  }

  const dropOnColumn = (status: ApplicationStatus) => (e: DragEvent) => {
    e.preventDefault()
    const id = e.dataTransfer.getData('text/plain') || dragId
    setDragOver(null)
    setDragId(null)
    if (!id) return
    const item = items.find((i) => i.id === id)
    if (!item || item.status === status) return
    void setStatus(id, status)
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
    // stage+track-aware requirement template: seed the checklist for this type
    const template = templateFor(formType)
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

  // Enter anywhere in the add form does what the Add button does
  const submitFormOnEnter = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return
    if (busy || !formName.trim()) return
    e.preventDefault()
    void submitForm()
  }

  const fafsaApplies = FAFSA_STAGES.has(stage ?? '')
  const hasFafsa = items.some((i) => i.name.toLowerCase().includes('fafsa'))

  const addFafsa = async () => {
    setBusy(true)
    const created = await createFafsa()
    if (created) setSelected(created.id)
    setBusy(false)
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
          <p className="label-mono mb-1">{appsSub}</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">{appsTitle}</h1>
        </div>
        <div className="flex items-center gap-2">
          {fafsaApplies && !hasFafsa && !loading && (
            <Btn onClick={() => void addFafsa()} disabled={busy}>
              <span className="flex items-center gap-1.5"><Landmark size={13} /> Add FAFSA</span>
            </Btn>
          )}
          <span data-tour="apps-scout">
            <Btn onClick={() => setShowScout((s) => !s)}>
              <span className="flex items-center gap-1.5"><Search size={13} /> Find scholarships</span>
            </Btn>
          </span>
          <span data-tour="apps-add">
            <Btn kind="primary" onClick={() => setShowForm((s) => !s)}>
              <span className="flex items-center gap-1.5"><Plus size={13} /> Add application</span>
            </Btn>
          </span>
        </div>
      </div>

      <ScholarshipScout show={showScout} stage={stage} />

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
                    onKeyDown={submitFormOnEnter}
                    placeholder="Stanford MS CS"
                    className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-ink/25"
                  />
                </div>
                <div>
                  <p className="label-mono mb-1">type</p>
                  <select
                    value={formType}
                    onChange={(e) => setFormType(e.target.value as ApplicationType)}
                    className="rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-ink/25"
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
                    onKeyDown={submitFormOnEnter}
                    className="rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-ink/25"
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

      {(presentTypes.length > 1 || archivedItems.length > 0) && (
        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          {([
            'all',
            ...presentTypes,
            ...(archivedItems.length > 0 ? (['archived'] as const) : []),
          ] as const).map((t) => {
            const n =
              t === 'all' ? activeItems.length
              : t === 'archived' ? archivedItems.length
              : activeItems.filter((i) => i.type === t).length
            return (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={`rounded-full border px-3 py-1.5 text-[12.5px] transition-colors duration-150 ${
                  typeFilter === t
                    ? 'border-ink/25 bg-ink/6 text-hi'
                    : 'border-line text-mid hover:border-ink/15 hover:text-hi'
                }`}
              >
                {t === 'all' ? 'Everything' : t === 'archived' ? 'Archived' : TYPE_LABEL[t]}
                <span className="ml-1.5 font-mono text-[11px] text-low">{n}</span>
              </button>
            )
          })}
        </div>
      )}

      <Panel className="mb-6">
        <PanelHead label="next deadlines" right={<Mono className="text-low">{visibleDeadlines.length} upcoming</Mono>} />
        {costs && (costs.fees_due > 0 || costs.potential_awards > 0) && (
          <Mono className="-mt-1 block px-5 pb-3 text-low">
            fees due {formatUsd(costs.fees_due)} · potential awards {formatUsd(costs.potential_awards)}
          </Mono>
        )}
        <div className="flex flex-col gap-px px-2 pb-3">
          {visibleDeadlines.length === 0 && <EmptyState title="No deadlines in the next 30 days." />}
          {visibleDeadlines.slice(0, 3).map((d) => (
            <button
              key={d.id}
              onClick={() => setSelected(d.id)}
              className="flex items-center gap-3 rounded-[10px] px-3 py-2 text-left hover:bg-ink/4"
            >
              <Calendar size={13} className="shrink-0 text-low" />
              <span className="flex-1 truncate text-[12.5px] text-mid">{d.name}</span>
              <Pill>{d.type}</Pill>
              <DeadlineLabel deadline={d.deadline} />
            </button>
          ))}
        </div>
      </Panel>

      {visible.length === 0 ? (
        <EmptyState title="No applications yet." hint="Add your first application to start the pipeline." />
      ) : (
        <div data-tour="apps-board" className="overflow-x-auto pb-2">
          <div className="flex min-w-max gap-3">
            {columns.map(({ status, items: colItems }) => (
              <div
                key={status}
                className={`w-[200px] shrink-0 rounded-[12px] transition-colors duration-150 ${dragOver === status ? 'bg-ink/4 ring-1 ring-ink/10' : ''}`}
                onDragOver={(e) => {
                  e.preventDefault()
                  e.dataTransfer.dropEffect = 'move'
                  if (dragOver !== status) setDragOver(status)
                }}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(null)
                }}
                onDrop={dropOnColumn(status)}
              >
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
                        draggable
                        onDragStart={(e) => {
                          setDragId(item.id)
                          e.dataTransfer.effectAllowed = 'move'
                          e.dataTransfer.setData('text/plain', item.id)
                        }}
                        onDragEnd={() => { setDragId(null); setDragOver(null) }}
                        className={`panel cursor-grab px-3 py-2.5 transition-colors duration-150 hover:bg-raise2 active:cursor-grabbing ${selected === item.id ? 'border-ink/15' : ''} ${dragId === item.id ? 'opacity-40' : ''}`}
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
                          {item.notes && (
                            <p className="mt-1 line-clamp-2 text-[11.5px] leading-snug text-low">{item.notes}</p>
                          )}
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
          <ApplicationDrawer
            item={selectedItem}
            busy={busy}
            setBusy={setBusy}
            canSeedChecklist={Boolean(cfg.requirementTemplates[selectedItem.type])}
            templateFor={templateFor}
            onClose={() => setSelected(null)}
            onChanged={load}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
