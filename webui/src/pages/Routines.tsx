import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Panel, PanelHead, Pill, Btn, EmptyState } from '../components/ui'
import { LocalAiPanel } from '../components/LocalAiPanel'
import {
  routinesApi,
  type DeadlineDigest,
  type DeadlineDigestBriefing,
  type EssayFeedback,
  type RoutineCatalogEntry,
  RoutinesApiError,
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

      <LocalAiPanel />

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
            Assistants
          </Link>{' '}
          page. This page only runs routines on demand.
        </p>
      </div>
    </div>
  )
}

function OfflineNote() {
  return (
    <p className="text-[12.5px] text-fail">
      The local AI isn't set up yet — download it in Settings → Local AI.
    </p>
  )
}

function FailedNote({ message }: { message: string }) {
  return <p role="alert" className="text-[12.5px] text-fail">{message}</p>
}

// Split an LLM-call failure into "AI not available" vs "something else went wrong".
function llmFailure(e: unknown): { offline: boolean; message: string } {
  if (e instanceof RoutinesApiError) return { offline: e.offline, message: e.message }
  return { offline: false, message: 'Something went wrong. Try again.' }
}

function DeadlineWatcherCard() {
  const [digest, setDigest] = useState<DeadlineDigest | null>(null)
  const [briefing, setBriefing] = useState<DeadlineDigestBriefing | null>(null)
  const [loadingDigest, setLoadingDigest] = useState(false)
  const [loadingBrief, setLoadingBrief] = useState(false)
  const [briefOffline, setBriefOffline] = useState(false)
  const [briefError, setBriefError] = useState('')
  const [digestError, setDigestError] = useState(false)

  const runNow = async () => {
    setLoadingDigest(true)
    setBriefing(null)
    setBriefOffline(false)
    setBriefError('')
    setDigestError(false)
    try {
      const d = await routinesApi.deadlineDigest(14)
      setDigest(d)
    } catch {
      setDigest(null)
      setDigestError(true)
    } finally {
      setLoadingDigest(false)
    }
  }

  const runBriefing = async () => {
    setLoadingBrief(true)
    setBriefOffline(false)
    setBriefError('')
    try {
      const b = await routinesApi.deadlineDigestBrief(14)
      setBriefing(b)
      setDigest(b)
      setDigestError(false)
    } catch (e) {
      const f = llmFailure(e)
      if (f.offline) setBriefOffline(true)
      else setBriefError(f.message)
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
        {briefError && <div className="mb-3"><FailedNote message={briefError} /></div>}
        {digestError && (
          <div className="mb-3"><FailedNote message="Couldn't load your deadlines. Check the app backend is running, then try again." /></div>
        )}

        {digest === null && !loadingDigest && !digestError && (
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
            <p className="whitespace-pre-line text-[13px] leading-relaxed text-hi">{briefing.briefing}</p>
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
  const [failure, setFailure] = useState('')

  const getFeedback = async () => {
    if (!text.trim()) return
    setLoading(true)
    setOffline(false)
    setFailure('')
    setFeedback(null)
    try {
      const f = await routinesApi.essayFeedback(text, promptHint)
      setFeedback(f)
    } catch (e) {
      const r = llmFailure(e)
      if (r.offline) setOffline(true)
      else setFailure(r.message)
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
        {failure && <div className="mt-3"><FailedNote message={failure} /></div>}

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
