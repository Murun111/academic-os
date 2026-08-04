import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Panel, PanelHead, Pill, Btn, EmptyState } from '../components/ui'
import {
  routinesApi,
  type DeadlineDigest,
  type DeadlineDigestBriefing,
  type EssayFeedback,
  type RoutineCatalogEntry,
} from '../lib/routinesApi'

export function Routines() {
  const [catalog, setCatalog] = useState<RoutineCatalogEntry[]>([])
  const [catalogLoaded, setCatalogLoaded] = useState(false)

  useEffect(() => {
    void routinesApi.catalog().then((c) => {
      setCatalog(c.routines)
      setCatalogLoaded(true)
    })
  }, [])

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6">
        <p className="label-mono mb-1">agent routines · on-demand</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Routines</h1>
      </div>

      {catalogLoaded && catalog.length === 0 && (
        <EmptyState title="No routines available" hint="Backend may be unreachable." />
      )}

      {catalog.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {catalog.map((r) => (
            <Pill key={r.id}>{r.name}</Pill>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DeadlineWatcherCard />
        <EssayFeedbackCard />
      </div>

      <div className="mt-6 flex items-center justify-between border-t border-hairline pt-4">
        <p className="text-[12.5px] text-low">
          Scheduled and background agents live on the{' '}
          <Link to="/agents" className="text-mid underline decoration-dotted hover:text-hi">
            Agents
          </Link>{' '}
          page. This page only runs routines on demand.
        </p>
      </div>
    </div>
  )
}

function OfflineNote() {
  return <p className="text-[12.5px] text-fail">Local model offline — start Ollama</p>
}

function DeadlineWatcherCard() {
  const [digest, setDigest] = useState<DeadlineDigest | null>(null)
  const [briefing, setBriefing] = useState<DeadlineDigestBriefing | null>(null)
  const [loadingDigest, setLoadingDigest] = useState(false)
  const [loadingBrief, setLoadingBrief] = useState(false)
  const [briefOffline, setBriefOffline] = useState(false)

  const runNow = async () => {
    setLoadingDigest(true)
    setBriefing(null)
    setBriefOffline(false)
    try {
      const d = await routinesApi.deadlineDigest(14)
      setDigest(d)
    } finally {
      setLoadingDigest(false)
    }
  }

  const runBriefing = async () => {
    setLoadingBrief(true)
    setBriefOffline(false)
    try {
      const b = await routinesApi.deadlineDigestBrief(14)
      if (b) {
        setBriefing(b)
        setDigest(b)
      } else {
        setBriefOffline(true)
      }
    } finally {
      setLoadingBrief(false)
    }
  }

  return (
    <Panel>
      <PanelHead
        label="deadline watcher"
        right={
          <div className="flex items-center gap-2">
            <Btn kind="quiet" onClick={() => void runNow()} disabled={loadingDigest}>
              {loadingDigest ? 'Running…' : 'Run now'}
            </Btn>
            <Btn kind="primary" onClick={() => void runBriefing()} disabled={loadingBrief}>
              {loadingBrief ? 'Thinking…' : 'AI briefing'}
            </Btn>
          </div>
        }
      />
      <div className="px-5 pb-5">
        <p className="mb-3 text-[12.5px] text-low">
          Merges upcoming application deadlines and assignment due dates into one digest.
        </p>

        {briefOffline && <div className="mb-3"><OfflineNote /></div>}

        {digest === null && !loadingDigest && (
          <EmptyState title="No digest yet" hint="Click Run now." />
        )}

        {digest && digest.items.length === 0 && (
          <EmptyState title="Nothing due soon" hint="No deadlines in the next 14 days." />
        )}

        {digest && digest.items.length > 0 && (
          <ul className="mb-3 flex flex-col gap-1.5">
            {digest.items.map((it) => (
              <li key={`${it.kind}-${it.id}`} className="flex items-center justify-between gap-2 text-[13px]">
                <span className="truncate text-mid">{it.title}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <Pill>{it.kind}</Pill>
                  <span className="font-mono text-[11px] text-low">{it.due ?? '—'}</span>
                </span>
              </li>
            ))}
          </ul>
        )}

        {digest && (
          <p className="whitespace-pre-line text-[12.5px] leading-relaxed text-mid">{digest.summary}</p>
        )}

        {briefing && (
          <div className="mt-3 border-t border-hairline pt-3">
            <p className="label-mono mb-1.5">ai briefing</p>
            <p className="text-[13px] leading-relaxed text-hi">{briefing.briefing}</p>
          </div>
        )}
      </div>
    </Panel>
  )
}

function EssayFeedbackCard() {
  const [text, setText] = useState('')
  const [promptHint, setPromptHint] = useState('')
  const [feedback, setFeedback] = useState<EssayFeedback | null>(null)
  const [loading, setLoading] = useState(false)
  const [offline, setOffline] = useState(false)

  const getFeedback = async () => {
    if (!text.trim()) return
    setLoading(true)
    setOffline(false)
    setFeedback(null)
    try {
      const f = await routinesApi.essayFeedback(text, promptHint)
      if (f) {
        setFeedback(f)
      } else {
        setOffline(true)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <Panel>
      <PanelHead label="essay feedback" />
      <div className="px-5 pb-5">
        <p className="mb-3 text-[12.5px] text-low">
          Admissions-essay coach — structure, specificity, voice, cliché detection.
        </p>

        <input
          value={promptHint}
          onChange={(e) => setPromptHint(e.target.value)}
          placeholder="Essay prompt (optional)"
          className="mb-2 w-full rounded-lg border border-line bg-raise px-3 py-2 text-[13px] text-hi outline-none placeholder:text-low"
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste your draft here…"
          rows={8}
          className="mb-3 w-full resize-y rounded-lg border border-line bg-raise px-3 py-2 text-[13px] text-hi outline-none placeholder:text-low"
        />

        <Btn kind="primary" onClick={() => void getFeedback()} disabled={loading || !text.trim()}>
          {loading ? 'Reading…' : 'Get feedback'}
        </Btn>

        {offline && <div className="mt-3"><OfflineNote /></div>}

        {feedback && (
          <div className="mt-4 border-t border-hairline pt-3">
            <p className="label-mono mb-1.5">feedback · {feedback.model}</p>
            <div className="flex flex-col gap-2">
              {feedback.feedback.split('\n').filter((line) => line.trim().length > 0).map((line, i) => (
                <p key={i} className="text-[13px] leading-relaxed text-mid">{line}</p>
              ))}
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}
