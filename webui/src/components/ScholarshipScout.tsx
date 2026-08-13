import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { scoutApi } from '../lib/scoutApi'
import { applicationsApi } from '../lib/applicationsApi'
import type { Stage } from '../lib/stageConfig'
import { Btn, Panel } from './ui'

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
export const FAFSA_STAGES = new Set(['highschool', 'undergrad', 'gapyear'])

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

// create the FAFSA card with its checklist seeded; returns the created application
export async function createFafsa() {
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
  }
  return created
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

export function ScholarshipScout({ show, stage }: { show: boolean; stage: Stage | null }) {
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

  return (
    <AnimatePresence>
      {show && (
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
  )
}
