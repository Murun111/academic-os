import { useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, ArrowRight, Calendar, Check, Landmark, Plus, Search, Trash2, X } from 'lucide-react'
import { scoutApi } from '../lib/scoutApi'
import {
  applicationsApi, APPLICATION_STATUSES, APPLICATION_TYPES, requirementsProgress,
  type Application, type ApplicationCosts, type ApplicationStatus, type ApplicationType,
} from '../lib/applicationsApi'
import { useOs } from '../lib/store'
import { stageConfig } from '../lib/stageConfig'
import { trackApplies, trackConfig } from '../lib/trackConfig'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../components/ui'

// human labels for the type filter tabs
const TYPE_LABEL: Record<ApplicationType, string> = {
  undergrad: 'Colleges',
  grad: 'Programs',
  scholarship: 'Scholarships',
  exchange: 'Exchange',
}

const STATUS_LABEL: Record<ApplicationStatus, string> = {
  researching: 'Researching',
  preparing: 'Preparing',
  submitted: 'Submitted',
  interview: 'Interview',
  decision: 'Decision',
}

function daysUntil(deadline: string): number {
  return Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000)
}

// ── Find-scholarships fill-in-the-blanks options ─────────────────────────────
const STAGE_PHRASE: Record<string, string> = {
  highschool: 'high school student',
  undergrad: 'undergraduate student',
  gapyear: 'college graduate on a gap year',
  grad: 'graduate student',
  beyond: 'graduate',
}

const MAJORS = [
  'Computer Science', 'Engineering', 'Business', 'Biology / Pre-med',
  'Nursing', 'Economics', 'Psychology', 'Arts & Design', 'Other…',
]

const IDENTITIES = [
  'First-generation', 'Immigrant', 'Low-income', 'Woman in STEM',
  'Underrepresented minority', 'International student', 'Veteran', 'Student with a disability',
]

const AMOUNTS = ['any amount', 'over $1,000', 'over $5,000', 'over $10,000']

// ── FAFSA one-click card ─────────────────────────────────────────────────────
const FAFSA_STAGES = new Set(['highschool', 'undergrad', 'gapyear'])

const FAFSA_CHECKLIST = [
  'Create your FSA ID at studentaid.gov',
  'Parent / contributor creates their FSA ID',
  'Gather tax returns and income info',
  'List the schools that should receive your FAFSA',
  'Submit the FAFSA',
  'Check your confirmation and compare aid offers',
]

const FAFSA_NOTES =
  'File as early as you can — some state and college aid is first-come, first-served. ' +
  'June 30 is the FEDERAL deadline; most state deadlines are much earlier — check yours at ' +
  'studentaid.gov. Filing is free. Anyone charging a fee to file it is a scam.'

function nextJune30Iso(): string {
  const now = new Date()
  const thisYear = new Date(now.getFullYear(), 5, 30)
  const d = now <= thisYear ? thisYear : new Date(now.getFullYear() + 1, 5, 30)
  return `${d.getFullYear()}-06-30`
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-2.5 py-1 text-[12px] transition-colors duration-150 ${
        active
          ? 'border-ink/25 bg-ink/6 text-hi'
          : 'border-line text-mid hover:border-ink/15 hover:text-hi'
      }`}
    >
      {children}
    </button>
  )
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
  const [notesDraft, setNotesDraft] = useState('')
  const [nameDraft, setNameDraft] = useState('')
  const [orgDraft, setOrgDraft] = useState('')
  const [urlDraft, setUrlDraft] = useState('')
  const [dragId, setDragId] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState<ApplicationStatus | null>(null)
  const [showScout, setShowScout] = useState(false)
  const [major, setMajor] = useState('')
  const [customMajor, setCustomMajor] = useState('')
  const [identities, setIdentities] = useState<string[]>([])
  const [amount, setAmount] = useState('')
  const [extra, setExtra] = useState('')
  const [scoutState, setScoutState] = useState<'idle' | 'running' | 'done' | 'failed'>('idle')
  const [scoutSummary, setScoutSummary] = useState('')
  const scoutPoll = useRef<number | null>(null)

  useEffect(() => () => { if (scoutPoll.current) window.clearInterval(scoutPoll.current) }, [])

  // compose the fill-in-the-blanks selections into one plain sentence
  const chosenMajor = major === 'Other…' ? customMajor.trim() : major
  const criteria = [
    STAGE_PHRASE[stage ?? 'undergrad'],
    chosenMajor && `studying ${chosenMajor}`,
    identities.length > 0 && identities.join(', ').toLowerCase(),
    amount && (amount === 'any amount' ? 'open to scholarships of any amount' : `looking for scholarships ${amount}`),
    extra.trim(),
  ].filter(Boolean).join(', ')

  const toggleIdentity = (id: string) =>
    setIdentities((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const startScout = async () => {
    const c = criteria.trim()
    if (!c || scoutState === 'running') return
    setScoutState('running')
    setScoutSummary('')
    const id = await scoutApi.search(c)
    if (!id) {
      setScoutState('failed')
      setScoutSummary("Couldn't start the search — is the backend running?")
      return
    }
    const startedAt = Date.now()
    scoutPoll.current = window.setInterval(async () => {
      const run = await scoutApi.run(id)
      const timedOut = Date.now() - startedAt > 4 * 60_000
      if (run && run.status !== 'running' && run.status !== 'pending') {
        window.clearInterval(scoutPoll.current!)
        scoutPoll.current = null
        setScoutState(run.status === 'success' ? 'done' : 'failed')
        setScoutSummary(run.result || run.error || 'The search finished without a summary.')
      } else if (timedOut) {
        window.clearInterval(scoutPoll.current!)
        scoutPoll.current = null
        setScoutState('failed')
        setScoutSummary('The search is taking too long — check the Assistants page for the run.')
      }
    }, 3000)
  }

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

  // type filter tabs — split colleges from scholarships without two pages
  const [typeFilter, setTypeFilter] = useState<ApplicationType | 'all'>('all')
  const presentTypes = APPLICATION_TYPES.filter((t) => items.some((i) => i.type === t))
  const visible = typeFilter === 'all' ? items : items.filter((i) => i.type === typeFilter)
  const visibleDeadlines = typeFilter === 'all' ? deadlines : deadlines.filter((d) => d.type === typeFilter)
  const columns = APPLICATION_STATUSES.map((status) => ({ status, items: visible.filter((i) => i.status === status) }))

  // sync drafts whenever the drawer selection changes
  useEffect(() => {
    setAmountDraft(selectedItem?.amount == null ? '' : String(selectedItem.amount))
    setFeeDraft(selectedItem?.app_fee == null ? '' : String(selectedItem.app_fee))
    setNotesDraft(selectedItem?.notes ?? '')
    setNameDraft(selectedItem?.name ?? '')
    setOrgDraft(selectedItem?.org ?? '')
    setUrlDraft(selectedItem?.url ?? '')
  }, [selectedItem?.id])

  const patch = async (fields: Parameters<typeof applicationsApi.update>[1]) => {
    if (!selectedItem) return
    await applicationsApi.update(selectedItem.id, fields)
    await load()
  }

  const commitName2 = async () => {
    if (!selectedItem || !nameDraft.trim() || nameDraft.trim() === selectedItem.name) return
    await patch({ name: nameDraft.trim() })
  }

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

  const commitNotes = async () => {
    if (!selectedItem) return
    if (notesDraft === selectedItem.notes) return
    await applicationsApi.update(selectedItem.id, { notes: notesDraft })
    await load()
  }

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

  const toggleRequirement = async (item: Application, reqId: string, done: boolean) => {
    await applicationsApi.updateRequirement(item.id, reqId, { done: !done })
    await load()
  }

  const fafsaApplies = FAFSA_STAGES.has(stage ?? '')
  const hasFafsa = items.some((i) => i.name.toLowerCase().includes('fafsa'))

  const addFafsa = async () => {
    setBusy(true)
    const created = await applicationsApi.create({
      name: 'FAFSA (federal student aid)',
      type: 'scholarship',
      org: 'Federal Student Aid',
      url: 'https://studentaid.gov/h/apply-for-aid/fafsa',
      deadline: nextJune30Iso(),
      notes: FAFSA_NOTES,
    })
    if (created) {
      for (const label of FAFSA_CHECKLIST) {
        await applicationsApi.addRequirement(created.id, label)
      }
      setSelected(created.id)
    }
    setBusy(false)
    await load()
  }

  const seedChecklist = async () => {
    // for cards that arrived without one (agent-found, synced) — seed the
    // stage template for this type
    const item = selectedItem
    const template = item && templateFor(item.type)
    if (!item || !template) return
    setBusy(true)
    for (const label of template) {
      await applicationsApi.addRequirement(item.id, label)
    }
    setBusy(false)
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

      <AnimatePresence>
        {showScout && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-6 overflow-hidden"
          >
            <Panel className="p-4">
              <p className="mb-3 text-[12.5px] text-mid">
                Pick what fits — the scout searches the web and proposes matches. Nothing enters
                your pipeline until you approve it.
              </p>

              <p className="label-mono mb-1.5">studying</p>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {MAJORS.map((m) => (
                  <Chip key={m} active={major === m} onClick={() => setMajor(major === m ? '' : m)}>{m}</Chip>
                ))}
                {major === 'Other…' && (
                  <input
                    value={customMajor}
                    onChange={(e) => setCustomMajor(e.target.value)}
                    placeholder="your major"
                    autoFocus
                    className="rounded-full border border-line bg-raise2 px-3 py-1 text-[12px] text-hi outline-none placeholder:text-low focus:border-ink/25"
                  />
                )}
              </div>

              <p className="label-mono mb-1.5">about you <span className="normal-case">(pick any)</span></p>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {IDENTITIES.map((id) => (
                  <Chip key={id} active={identities.includes(id)} onClick={() => toggleIdentity(id)}>{id}</Chip>
                ))}
              </div>

              <p className="label-mono mb-1.5">award size</p>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {AMOUNTS.map((a) => (
                  <Chip key={a} active={amount === a} onClick={() => setAmount(amount === a ? '' : a)}>{a}</Chip>
                ))}
              </div>

              <div className="flex gap-2">
                <input
                  value={extra}
                  onChange={(e) => setExtra(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') void startScout() }}
                  placeholder="Anything else — state, sport, club, situation… (optional)"
                  className="flex-1 rounded-lg border border-line bg-raise2 px-3 py-2 text-[13px] text-hi outline-none placeholder:text-low focus:border-ink/25"
                />
                <Btn kind="primary" onClick={() => void startScout()} disabled={scoutState === 'running' || !criteria.trim()}>
                  {scoutState === 'running' ? 'Searching…' : 'Search'}
                </Btn>
              </div>
              {criteria && scoutState !== 'running' && (
                <p className="mt-2 text-[12px] text-low">Will search for: <span className="text-mid">{criteria}</span></p>
              )}
              {scoutState === 'running' && (
                <p className="mt-2 text-[12.5px] text-mid">
                  Searching the web — this takes a minute or two. You can leave this page; results
                  land in <Link to="/approvals" className="underline decoration-dotted">Approvals</Link>.
                </p>
              )}
              {scoutState === 'done' && (
                <div className="mt-2">
                  <p className="whitespace-pre-line text-[12.5px] leading-relaxed text-mid">{scoutSummary}</p>
                  <Link to="/approvals" className="mt-1 inline-block text-[12.5px] text-hi underline decoration-dotted">
                    Review proposals in Approvals →
                  </Link>
                </div>
              )}
              {scoutState === 'failed' && (
                <p className="mt-2 text-[12.5px] text-fail">{scoutSummary}</p>
              )}
            </Panel>
          </motion.div>
        )}
      </AnimatePresence>

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

      {presentTypes.length > 1 && (
        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          {(['all', ...presentTypes] as const).map((t) => {
            const n = t === 'all' ? items.length : items.filter((i) => i.type === t).length
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
                {t === 'all' ? 'Everything' : TYPE_LABEL[t]}
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
                className={`w-[220px] shrink-0 rounded-[12px] transition-colors duration-150 ${dragOver === status ? 'bg-ink/4 ring-1 ring-ink/10' : ''}`}
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
              <button onClick={() => setSelected(null)} className="text-low hover:text-mid"><X size={16} /></button>
            </div>

            <div className="mb-4 flex flex-wrap items-end gap-3">
              <div>
                <p className="label-mono mb-1">type</p>
                <select
                  value={selectedItem.type}
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
                  value={selectedItem.deadline ?? ''}
                  onChange={(e) => void patch({ deadline: e.target.value || null })}
                  className="rounded-lg border border-line bg-raise2 px-2 py-1.5 text-[12.5px] text-hi outline-none focus:border-ink/25"
                />
              </div>
              <div className="flex flex-col items-start gap-1 pb-0.5">
                <Pill>{STATUS_LABEL[selectedItem.status]}</Pill>
                {selectedItem.deadline && <DeadlineLabel deadline={selectedItem.deadline} />}
              </div>
            </div>

            {selectedItem.status === 'decision' && (
              <div className="mb-4">
                <p className="label-mono mb-1">result</p>
                <select
                  value={selectedItem.decision_result}
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
                  onBlur={() => { if (orgDraft !== selectedItem.org) void patch({ org: orgDraft }) }}
                  placeholder="e.g. Stanford"
                  className="w-full rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[12.5px] text-hi outline-none placeholder:text-low focus:border-ink/25"
                />
              </div>
              <div className="flex-1">
                <p className="label-mono mb-1">link</p>
                <input
                  value={urlDraft}
                  onChange={(e) => setUrlDraft(e.target.value)}
                  onBlur={() => { if (urlDraft !== selectedItem.url) void patch({ url: urlDraft }) }}
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
                checked={selectedItem.fee_waived}
                onChange={(e) => void toggleFeeWaived(e.target.checked)}
                className="size-3.5 accent-ink/70"
              />
              <span className="text-[12.5px] text-mid">fee waived</span>
            </label>

            <div className="mb-4">
              <p className="label-mono mb-2">requirements</p>
              <div className="flex flex-col gap-1.5">
                {selectedItem.requirements.length === 0 && (
                  cfg.requirementTemplates[selectedItem.type] ? (
                    <Btn onClick={() => void seedChecklist()} disabled={busy}>
                      {busy ? 'Adding…' : `Add ${selectedItem.type} checklist`}
                    </Btn>
                  ) : (
                    <Mono className="text-low">none yet</Mono>
                  )
                )}
                {selectedItem.requirements.map((r) => (
                  <div key={r.id} className="flex items-center gap-2">
                    <button
                      onClick={() => void toggleRequirement(selectedItem, r.id, r.done)}
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
