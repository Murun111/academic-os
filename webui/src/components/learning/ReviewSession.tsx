import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, RotateCw } from 'lucide-react'
import {
  learning,
  isUnavailable,
  type Card,
  type SrsRating,
} from '../../lib/learningApi'
import { Btn, EmptyState, Kbd, Mono, Panel, PanelHead } from '../ui'

const RATINGS: { key: string; rating: SrsRating; label: string; hint: string }[] = [
  { key: '1', rating: 'again', label: 'Again', hint: 'Forgot it' },
  { key: '2', rating: 'hard', label: 'Hard', hint: 'Barely recalled' },
  { key: '3', rating: 'good', label: 'Good', hint: 'Recalled' },
  { key: '4', rating: 'easy', label: 'Easy', hint: 'Effortless' },
]

function errorMessage(e: unknown, action: string): string {
  if (isUnavailable(e)) return `The learning service is not reachable right now. ${action} once it is back.`
  return `Something went wrong. ${action}.`
}

export function ReviewSession() {
  const [queue, setQueue] = useState<Card[]>([])
  const [total, setTotal] = useState(0)
  const [done, setDone] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [rateError, setRateError] = useState<string | null>(null)
  const [flipped, setFlipped] = useState(false)
  const [showHint, setShowHint] = useState(false)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const cards = await learning.dueCards()
      setQueue(cards)
      setTotal(cards.length)
      setDone(0)
      setFlipped(false)
      setShowHint(false)
    } catch (e) {
      setLoadError(errorMessage(e, 'Try again'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const current: Card | undefined = queue[0]

  const rate = useCallback(
    async (rating: SrsRating) => {
      if (!current || busyRef.current) return
      if (!current.deck_id) {
        setRateError('This card has no deck reference, so it cannot be rated.')
        return
      }
      busyRef.current = true
      setBusy(true)
      setRateError(null)
      try {
        await learning.reviewCard(current.deck_id, current.id, rating)
        setQueue((q) => q.slice(1))
        setDone((d) => d + 1)
        setFlipped(false)
        setShowHint(false)
      } catch (e) {
        setRateError(errorMessage(e, 'Your rating was not saved. Try again'))
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    },
    [current],
  )

  // keyboard: space/enter flips, 1-4 rates (only after flip)
  useEffect(() => {
    if (!current) return
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
      const onButton = t?.tagName === 'BUTTON'
      if ((e.key === ' ' || e.key === 'Enter') && !onButton) {
        e.preventDefault()
        setFlipped(true)
        return
      }
      if (flipped) {
        const hit = RATINGS.find((r) => r.key === e.key)
        if (hit) {
          e.preventDefault()
          void rate(hit.rating)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [current, flipped, rate])

  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  return (
    <Panel>
      <PanelHead
        label="review"
        right={
          total > 0 ? (
            <Mono className="text-low">
              {Math.min(done + 1, total)} / {total}
            </Mono>
          ) : undefined
        }
      />
      <div className="px-5 pb-5">
        {loading ? (
          <p className="py-14 text-center text-[13px] text-low" role="status">
            Loading due cards…
          </p>
        ) : loadError ? (
          <div className="flex flex-col items-center gap-3 py-12 text-center" role="alert">
            <p className="max-w-[420px] text-[13px] text-mid">{loadError}</p>
            <Btn onClick={() => void load()}>
              <span className="flex items-center gap-1.5">
                <RotateCw size={13} /> Retry
              </span>
            </Btn>
          </div>
        ) : !current ? (
          <div className="flex flex-col items-center gap-2">
            <CheckCircle2 size={22} className="mt-10 text-run" aria-hidden="true" />
            <EmptyState
              title="All caught up"
              hint={
                done > 0
                  ? `You reviewed ${done} card${done === 1 ? '' : 's'} this session.`
                  : 'No cards are due right now. Check back later.'
              }
            />
            <Btn onClick={() => void load()}>
              <span className="flex items-center gap-1.5">
                <RotateCw size={13} /> Check again
              </span>
            </Btn>
          </div>
        ) : (
          <div>
            <div
              className="mb-4 h-1 overflow-hidden rounded-full bg-ink/6"
              role="progressbar"
              aria-label="Review progress"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={done}
            >
              <div className="h-full bg-acc transition-all duration-200" style={{ width: `${pct}%` }} />
            </div>

            {(current.deck_title || current.course_name) && (
              <p className="label-mono mb-3">
                {[current.deck_title, current.course_name].filter(Boolean).join(' · ')}
              </p>
            )}

            <div className="rounded-[10px] border border-line bg-raise2 px-5 py-8 text-center">
              <p className="label-mono mb-2">question</p>
              <p className="whitespace-pre-wrap text-[18px] font-medium text-hi">{current.front}</p>

              {current.hint && !flipped && (
                <div className="mt-4">
                  {showHint ? (
                    <p className="text-[13px] text-low">Hint: {current.hint}</p>
                  ) : (
                    <Btn onClick={() => setShowHint(true)}>Show hint</Btn>
                  )}
                </div>
              )}

              {flipped && (
                <div className="mt-6 border-t border-line pt-6" aria-live="polite">
                  <p className="label-mono mb-2">answer</p>
                  <p className="whitespace-pre-wrap text-[16px] text-hi">{current.back}</p>
                  {current.explanation && (
                    <p className="mx-auto mt-3 max-w-[560px] whitespace-pre-wrap text-[13px] text-mid">
                      {current.explanation}
                    </p>
                  )}
                </div>
              )}
            </div>

            {rateError && (
              <p className="mt-3 text-center text-[12px] text-fail" role="alert">
                {rateError}
              </p>
            )}

            <div className="mt-4">
              {!flipped ? (
                <div className="flex items-center justify-center gap-2">
                  <Btn kind="primary" onClick={() => setFlipped(true)}>
                    Show answer
                  </Btn>
                  <Kbd>Space</Kbd>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="group" aria-label="Rate your recall">
                  {RATINGS.map((r) => (
                    <button
                      key={r.rating}
                      type="button"
                      disabled={busy}
                      onClick={() => void rate(r.rating)}
                      aria-label={`${r.label}: ${r.hint} (key ${r.key})`}
                      aria-keyshortcuts={r.key}
                      className="flex flex-col items-center gap-1 rounded-[10px] border border-line px-3 py-2.5 text-[13px] font-medium text-mid transition-colors duration-150 hover:bg-ink/5 hover:text-hi focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc disabled:pointer-events-none disabled:opacity-40"
                    >
                      <span>{r.label}</span>
                      <Kbd>{r.key}</Kbd>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}
