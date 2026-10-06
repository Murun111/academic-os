import { useCallback, useEffect, useRef, useState } from 'react'
import { Pause, Play, RotateCcw, Square } from 'lucide-react'
import { learning, isUnavailable, type FocusSession } from '../../lib/learningApi'
import { Btn, EmptyState, Mono, Panel, PanelHead } from '../ui'

const PRESETS = [25, 50, 90] as const

const fieldCls =
  'w-full rounded-md border border-line bg-transparent px-2.5 py-1.5 text-[13px] text-hi placeholder:text-low focus:border-ink/30 focus:outline-none'

function fmt(totalSec: number): string {
  const s = Math.max(0, Math.ceil(totalSec))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

function whenLabel(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
    ' ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function errMsg(e: unknown, what: string): string {
  return isUnavailable(e)
    ? `The study service is not reachable right now. ${what} will work once it is back.`
    : `Could not ${what.toLowerCase()}. Try again in a moment.`
}

export function FocusPanel() {
  const [sessions, setSessions] = useState<FocusSession[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [minutes, setMinutes] = useState<number>(25)
  const [topic, setTopic] = useState('')
  const [goal, setGoal] = useState('')
  const [reflections, setReflections] = useState('')

  // Timer state: remaining time is derived from an end timestamp so it
  // survives throttled background tabs.
  const [running, setRunning] = useState(false)
  const [remaining, setRemaining] = useState(25 * 60)
  const [started, setStarted] = useState(false)
  const endRef = useRef(0)
  const elapsedRef = useRef(0) // seconds focused so far (excluding the running stretch)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const list = await learning.focusSessions()
      setSessions([...list].sort((a, b) => b.completed_at.localeCompare(a.completed_at)))
    } catch (e) {
      setLoadError(errMsg(e, 'Loading sessions'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => {
      const left = (endRef.current - Date.now()) / 1000
      if (left <= 0) {
        setRemaining(0)
        setRunning(false)
      } else {
        setRemaining(left)
      }
    }, 250)
    return () => window.clearInterval(id)
  }, [running])

  const finished = started && !running && remaining <= 0
  const totalSec = minutes * 60

  const pickPreset = (m: number) => {
    if (started) return
    setMinutes(m)
    setRemaining(m * 60)
  }

  const start = () => {
    endRef.current = Date.now() + remaining * 1000
    setStarted(true)
    setSaved(false)
    setRunning(true)
  }

  const pause = () => {
    elapsedRef.current = totalSec - Math.max(0, (endRef.current - Date.now()) / 1000)
    setRemaining(Math.max(0, (endRef.current - Date.now()) / 1000))
    setRunning(false)
  }

  const reset = () => {
    setRunning(false)
    setStarted(false)
    elapsedRef.current = 0
    setRemaining(minutes * 60)
  }

  const logSession = async () => {
    const t = topic.trim()
    if (!t) {
      setSaveError('Add a topic before logging this session.')
      return
    }
    const done = finished ? totalSec : running
      ? totalSec - Math.max(0, (endRef.current - Date.now()) / 1000)
      : totalSec - remaining
    const mins = Math.max(1, Math.round(done / 60))
    if (running) pause()
    setSaving(true)
    setSaveError(null)
    try {
      await learning.logFocus({
        duration_minutes: mins,
        topic: t,
        goal: goal.trim(),
        reflections: reflections.trim(),
      })
      setSaved(true)
      setTopic('')
      setGoal('')
      setReflections('')
      reset()
      void load()
    } catch (e) {
      setSaveError(errMsg(e, 'Logging the session'))
    } finally {
      setSaving(false)
    }
  }

  const progress = totalSec > 0 ? 1 - remaining / totalSec : 0
  const canLog = started && (finished || remaining < totalSec) && !saving

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel>
        <PanelHead label="focus timer" />
        <div className="flex flex-col gap-4 px-5 pb-5">
          <div role="group" aria-label="Session length" className="flex gap-2">
            {PRESETS.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => pickPreset(m)}
                disabled={started}
                aria-pressed={minutes === m}
                aria-label={`${m} minute session`}
                className={`rounded-lg px-3 py-1.5 font-mono text-[12px] transition-colors duration-150 disabled:pointer-events-none disabled:opacity-40 ${
                  minutes === m ? 'bg-ink/8 text-hi' : 'text-mid hover:bg-ink/5 hover:text-hi'
                }`}
              >
                {m}m
              </button>
            ))}
          </div>

          <div className="flex flex-col items-center gap-3 py-2">
            <div
              role="timer"
              aria-live="off"
              aria-label={`Time remaining ${fmt(remaining)}`}
              className="font-mono text-[48px] font-semibold tracking-[-0.02em] text-hi"
            >
              {fmt(remaining)}
            </div>
            <div
              role="progressbar"
              aria-label="Session progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress * 100)}
              className="h-1 w-full overflow-hidden rounded-full bg-ink/8"
            >
              <div className="h-full rounded-full bg-acc transition-[width] duration-300" style={{ width: `${progress * 100}%` }} />
            </div>
            {finished && <p className="text-[13px] text-run">Time is up. Log it below.</p>}
          </div>

          <div className="flex flex-wrap items-center justify-center gap-2">
            {running ? (
              <Btn kind="primary" onClick={pause}>
                <span className="inline-flex items-center gap-1.5"><Pause size={14} aria-hidden />Pause</span>
              </Btn>
            ) : (
              <Btn kind="primary" onClick={start} disabled={finished}>
                <span className="inline-flex items-center gap-1.5">
                  <Play size={14} aria-hidden />{started ? 'Resume' : 'Start'}
                </span>
              </Btn>
            )}
            <Btn onClick={reset} disabled={!started}>
              <span className="inline-flex items-center gap-1.5"><RotateCcw size={14} aria-hidden />Reset</span>
            </Btn>
          </div>

          <div className="flex flex-col gap-2 border-t border-line pt-4">
            <label className="flex flex-col gap-1">
              <span className="label-mono">topic</span>
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="What are you working on?"
                className={fieldCls}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="label-mono">goal (optional)</span>
              <input
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="What should be done by the end?"
                className={fieldCls}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="label-mono">reflections (optional)</span>
              <textarea
                value={reflections}
                onChange={(e) => setReflections(e.target.value)}
                rows={2}
                placeholder="What worked, what to review next"
                className={`${fieldCls} resize-none`}
              />
            </label>
            <div className="flex items-center gap-3">
              <Btn kind="primary" onClick={() => void logSession()} disabled={!canLog}>
                <span className="inline-flex items-center gap-1.5">
                  <Square size={13} aria-hidden />{saving ? 'Logging…' : finished ? 'Log session' : 'Stop and log'}
                </span>
              </Btn>
              {saved && <span role="status" className="text-[12px] text-run">Session logged.</span>}
            </div>
            {saveError && (
              <p role="alert" className="text-[12px] text-fail">{saveError}</p>
            )}
          </div>
        </div>
      </Panel>

      <Panel>
        <PanelHead label="recent sessions" />
        <div className="px-3 pb-3">
          {loading ? (
            <p role="status" className="px-2 py-10 text-center text-[13px] text-low">Loading sessions…</p>
          ) : loadError ? (
            <div role="alert" className="flex flex-col items-center gap-2 px-2 py-10 text-center">
              <p className="text-[13px] text-mid">{loadError}</p>
              <Btn onClick={() => { setLoading(true); void load() }}>Retry</Btn>
            </div>
          ) : sessions.length === 0 ? (
            <EmptyState title="No focus sessions yet" hint="Start the timer and log your first one." />
          ) : (
            <ul className="flex flex-col">
              {sessions.slice(0, 10).map((s) => (
                <li key={s.id} className="flex items-start gap-3 rounded-[10px] px-3 py-2 hover:bg-ink/4">
                  <Mono className="w-[48px] shrink-0 pt-0.5 text-hi">{s.duration_minutes}m</Mono>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] text-hi">{s.topic}</p>
                    {s.goal && <p className="truncate text-[12px] text-mid">{s.goal}</p>}
                    {s.reflections && <p className="line-clamp-2 text-[12px] text-low">{s.reflections}</p>}
                  </div>
                  <Mono className="shrink-0 pt-0.5 text-low">{s.course_name ? `${s.course_name} · ` : ''}{whenLabel(s.completed_at)}</Mono>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>
    </div>
  )
}
