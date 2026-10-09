import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { learning, isUnavailable, onLearningMutated, type LearningOverview } from '../lib/learningApi'
import { Btn, Panel } from '../components/ui'
import { ReviewSession } from '../components/learning/ReviewSession'
import { DecksPanel } from '../components/learning/DecksPanel'
import { QuizzesPanel } from '../components/learning/QuizzesPanel'
import { GuidesPanel } from '../components/learning/GuidesPanel'
import { MasteryPanel } from '../components/learning/MasteryPanel'
import { FocusPanel } from '../components/learning/FocusPanel'
import { TutorPanel } from '../components/learning/TutorPanel'
import { GeneratePanel } from '../components/learning/GeneratePanel'

// `keepAlive` tabs hold in-progress work (a running timer, a half-answered quiz,
// an unsaved generation, a conversation), so once visited they stay mounted and
// are only hidden. The rest list server data and remount fresh on every visit.
const TABS: { id: string; label: string; keepAlive?: boolean; render: (active: boolean) => ReactNode }[] = [
  { id: 'review', label: 'Review', render: (active) => <ReviewSession active={active} /> },
  { id: 'decks', label: 'Decks', render: () => <DecksPanel /> },
  { id: 'quizzes', label: 'Quizzes', keepAlive: true, render: () => <QuizzesPanel /> },
  { id: 'guides', label: 'Guides', render: () => <GuidesPanel /> },
  { id: 'mastery', label: 'Mastery', render: () => <MasteryPanel /> },
  { id: 'focus', label: 'Focus', keepAlive: true, render: () => <FocusPanel /> },
  { id: 'tutor', label: 'Tutor', keepAlive: true, render: () => <TutorPanel /> },
  { id: 'generate', label: 'Generate', keepAlive: true, render: () => <GeneratePanel /> },
]

function Stat({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return (
    <Panel className="px-4 py-3">
      <p className="label-mono mb-1">{label}</p>
      <p className="font-mono text-[20px] text-hi">{loading ? '…' : value}</p>
    </Panel>
  )
}

export function Learning() {
  const [params, setParams] = useSearchParams()
  const [overview, setOverview] = useState<LearningOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const active = TABS.find((t) => t.id === params.get('tab')) ?? TABS[0]
  const [visited, setVisited] = useState<string[]>([active.id])
  useEffect(() => {
    setVisited((v) => (v.includes(active.id) ? v : [...v, active.id]))
  }, [active.id])

  const load = useCallback(async () => {
    // No setLoading(true) here: initial state covers first load, and tab-switch
    // refetches should update in place instead of flashing skeletons.
    setError(null)
    try {
      setOverview(await learning.overview())
    } catch (e) {
      setError(
        isUnavailable(e)
          ? 'Learning service is unavailable right now. Stats will appear once it is reachable.'
          : 'Could not load learning stats.',
      )
    } finally {
      setLoading(false)
    }
  }, [])

  // Refetch on tab switch so the header reflects work done in the previous tab.
  useEffect(() => {
    void load()
  }, [load, active.id])

  // Any successful write inside a panel (a review, an import, a logged focus
  // session) refreshes the header stats without waiting for a tab switch.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const off = onLearningMutated(() => {
      clearTimeout(timer)
      timer = setTimeout(() => void load(), 300)
    })
    return () => {
      off()
      clearTimeout(timer)
    }
  }, [load])

  const o = overview
  const stats: { label: string; value: string }[] = [
    { label: 'due today', value: String(o?.cards_due_today ?? 0) },
    { label: (o?.total_decks ?? 0) === 1 ? 'cards · 1 deck' : `cards · ${o?.total_decks ?? 0} decks`, value: String(o?.total_cards ?? 0) },
    { label: 'quizzes', value: `${o?.total_quizzes ?? 0}` },
    { label: 'avg score', value: o && o.quiz_attempts_count > 0 ? `${Math.round(o.avg_quiz_score)}%` : '—' },
    { label: 'mastery', value: o && o.total_topics > 0 ? `${Math.round(o.overall_mastery)}%` : '—' },
    { label: 'focus', value: `${o?.total_focus_minutes ?? 0} min` },
  ]

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6">
        <p className="label-mono mb-1">review · quizzes · mastery · focus</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Learning</h1>
      </div>

      {error ? (
        <div role="alert" className="mb-5 flex items-center justify-between gap-3 rounded-[10px] border border-line px-4 py-3">
          <span className="text-[13px] text-mid">{error}</span>
          <Btn onClick={() => void load()}>Retry</Btn>
        </div>
      ) : (
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6" aria-busy={loading}>
          {stats.map((s) => (
            <Stat key={s.label} label={s.label} value={s.value} loading={loading} />
          ))}
        </div>
      )}

      <div role="tablist" aria-label="Learning sections" data-tour="learning-tabs" className="mb-5 flex flex-wrap gap-1 border-b border-line pb-2">
        {TABS.map((t) => {
          const on = t.id === active.id
          return (
            <button
              key={t.id}
              role="tab"
              id={`learning-tab-${t.id}`}
              aria-selected={on}
              aria-controls="learning-panel"
              onClick={() => setParams({ tab: t.id }, { replace: true })}
              className={`rounded-[10px] px-3 py-1.5 text-[13px] transition-colors duration-150 ${
                on ? 'bg-ink/6 text-hi' : 'text-mid hover:bg-ink/4 hover:text-hi'
              }`}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      <div id="learning-panel" role="tabpanel" aria-labelledby={`learning-tab-${active.id}`}>
        {TABS.map((t) => {
          const on = t.id === active.id
          if (!on && !(t.keepAlive && visited.includes(t.id))) return null
          return (
            <div key={t.id} hidden={!on}>
              {t.render(on)}
            </div>
          )
        })}
      </div>
    </div>
  )
}
