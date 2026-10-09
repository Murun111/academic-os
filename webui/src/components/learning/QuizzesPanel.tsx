import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Plus, Trash2, X } from 'lucide-react'
import {
  learning,
  isUnavailable,
  isLearningApiError,
  type Question,
  type QuestionCreate,
  type QuestionType,
  type Quiz,
  type QuizAttempt,
} from '../../lib/learningApi'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../ui'

type View =
  | { kind: 'list' }
  | { kind: 'create' }
  | { kind: 'take'; quiz: Quiz }
  | { kind: 'result'; quiz: Quiz; attempt: QuizAttempt }

const INPUT =
  'w-full rounded-md border border-line bg-transparent px-2.5 py-1.5 text-[13px] text-hi placeholder:text-low focus:outline-none focus-visible:border-ink/40'

function errMsg(e: unknown, fallback: string): string {
  if (isUnavailable(e)) return 'The learning service or local AI is not reachable right now. Try again in a moment.'
  if (isLearningApiError(e) && e.detail) return e.detail
  return fallback
}

function Notice({ children }: { children: string }) {
  return (
    <p role="alert" className="rounded-[10px] border border-line px-3 py-2 text-[12px] text-mid">
      {children}
    </p>
  )
}

function fmtAnswer(v: unknown): string {
  if (v === null || v === undefined || v === '') return '(no answer)'
  return typeof v === 'string' ? v : JSON.stringify(v)
}

/* ------------------------------- create form ------------------------------ */

interface DraftQ {
  prompt: string
  type: QuestionType
  options: string[]
  correct: string
  explanation: string
}

function blankQ(): DraftQ {
  return { prompt: '', type: 'multiple_choice', options: ['', '', '', ''], correct: '', explanation: '' }
}

function optionsFor(type: QuestionType, current: string[]): string[] {
  if (type === 'true_false') return ['True', 'False']
  if (type === 'short_answer') return []
  return current.length === 4 && !(current[0] === 'True' && current[1] === 'False') ? current : ['', '', '', '']
}

function CreateQuiz({ onCancel, onCreated }: { onCancel: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState('')
  const [topic, setTopic] = useState('')
  const [mins, setMins] = useState('15')
  const [qs, setQs] = useState<DraftQ[]>([blankQ()])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const patch = (i: number, p: Partial<DraftQ>) =>
    setQs((prev) => prev.map((q, j) => (j === i ? { ...q, ...p } : q)))

  const setType = (i: number, type: QuestionType) =>
    setQs((prev) =>
      prev.map((q, j) =>
        j === i ? { ...q, type, options: optionsFor(type, q.options), correct: '' } : q,
      ),
    )

  const valid =
    title.trim() &&
    topic.trim() &&
    qs.length > 0 &&
    qs.every((q) => {
      if (!q.prompt.trim() || !q.correct.trim() || !q.explanation.trim()) return false
      if (q.type === 'multiple_choice') return q.options.every((o) => o.trim()) && q.options.includes(q.correct)
      return true
    })

  const save = async () => {
    if (!valid || saving) return
    setSaving(true)
    setError('')
    const questions: QuestionCreate[] = qs.map((q) => ({
      prompt: q.prompt.trim(),
      type: q.type,
      options: q.type === 'multiple_choice' ? q.options.map((o) => o.trim()) : q.options,
      correct_answer: q.correct.trim(),
      explanation: q.explanation.trim(),
    }))
    const m = parseInt(mins, 10)
    try {
      await learning.createQuiz({
        title: title.trim(),
        topic: topic.trim(),
        time_limit_mins: Number.isFinite(m) && m > 0 ? m : 15,
        questions,
      })
      onCreated()
    } catch (e) {
      setError(errMsg(e, "Couldn't save the quiz."))
      setSaving(false)
    }
  }

  return (
    <Panel>
      <PanelHead label="new quiz" right={<Btn onClick={onCancel}>Cancel</Btn>} />
      <div className="flex flex-col gap-4 px-5 pb-5">
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_90px]">
          <label className="flex flex-col gap-1">
            <span className="label-mono">title</span>
            <input className={INPUT} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Midterm review" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label-mono">topic</span>
            <input className={INPUT} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Cell biology" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label-mono">minutes</span>
            <input className={INPUT} type="number" min={1} value={mins} onChange={(e) => setMins(e.target.value)} />
          </label>
        </div>

        {qs.map((q, i) => (
          <fieldset key={i} className="flex flex-col gap-2 rounded-[10px] border border-line p-3">
            <legend className="px-1">
              <Mono className="text-low">question {i + 1}</Mono>
            </legend>
            <div className="flex items-center gap-2">
              <input
                className={INPUT}
                value={q.prompt}
                onChange={(e) => patch(i, { prompt: e.target.value })}
                placeholder="Question text"
                aria-label={`Question ${i + 1} text`}
              />
              <select
                value={q.type}
                onChange={(e) => setType(i, e.target.value as QuestionType)}
                aria-label={`Question ${i + 1} type`}
                className="rounded-md border border-line bg-transparent px-2 py-1.5 text-[12px] text-mid focus:outline-none"
              >
                <option value="multiple_choice">multiple choice</option>
                <option value="true_false">true / false</option>
                <option value="short_answer">short answer</option>
              </select>
              {qs.length > 1 && (
                <button
                  type="button"
                  aria-label={`Remove question ${i + 1}`}
                  onClick={() => setQs((prev) => prev.filter((_, j) => j !== i))}
                  className="rounded-md p-1.5 text-low hover:bg-ink/5 hover:text-hi"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {q.type === 'multiple_choice' &&
              q.options.map((o, k) => (
                <div key={k} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={`correct-${i}`}
                    checked={o !== '' && q.correct === o}
                    disabled={!o.trim()}
                    onChange={() => patch(i, { correct: o })}
                    className="size-3.5 accent-ink/70"
                    aria-label={`Mark option ${k + 1} correct`}
                  />
                  <input
                    className={INPUT}
                    value={o}
                    onChange={(e) => {
                      const next = [...q.options]
                      next[k] = e.target.value
                      patch(i, { options: next, correct: q.correct === o ? '' : q.correct })
                    }}
                    placeholder={`Option ${k + 1}`}
                    aria-label={`Question ${i + 1} option ${k + 1}`}
                  />
                </div>
              ))}

            {q.type === 'true_false' && (
              <div className="flex items-center gap-4" role="radiogroup" aria-label="Correct answer">
                {['True', 'False'].map((o) => (
                  <label key={o} className="flex items-center gap-1.5 text-[13px] text-mid">
                    <input
                      type="radio"
                      name={`correct-${i}`}
                      checked={q.correct === o}
                      onChange={() => patch(i, { correct: o })}
                      className="size-3.5 accent-ink/70"
                    />
                    {o}
                  </label>
                ))}
              </div>
            )}

            {q.type === 'short_answer' && (
              <input
                className={INPUT}
                value={q.correct}
                onChange={(e) => patch(i, { correct: e.target.value })}
                placeholder="Correct answer"
                aria-label={`Question ${i + 1} correct answer`}
              />
            )}

            <input
              className={INPUT}
              value={q.explanation}
              onChange={(e) => patch(i, { explanation: e.target.value })}
              placeholder="Explanation shown after submitting"
              aria-label={`Question ${i + 1} explanation`}
            />
          </fieldset>
        ))}

        <div className="flex items-center justify-between gap-3">
          <Btn onClick={() => setQs((p) => [...p, blankQ()])}>
            <span className="flex items-center gap-1.5">
              <Plus size={13} /> Add question
            </span>
          </Btn>
          <Btn kind="primary" onClick={() => void save()} disabled={!valid || saving}>
            {saving ? 'Saving…' : 'Save quiz'}
          </Btn>
        </div>
        {error && <Notice>{error}</Notice>}
      </div>
    </Panel>
  )
}

/* -------------------------------- take quiz ------------------------------- */

function TakeQuiz({
  quiz,
  onExit,
  onSubmitted,
}: {
  quiz: Quiz
  onExit: () => void
  onSubmitted: (a: QuizAttempt) => void
}) {
  const [idx, setIdx] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const startedAt = useRef(Date.now())
  const limitSecs = quiz.time_limit_mins > 0 ? quiz.time_limit_mins * 60 : 0
  const [remaining, setRemaining] = useState(limitSecs)
  const submitRef = useRef<() => void>(() => {})
  const autoSubmitted = useRef(false)

  const total = quiz.questions.length
  const q: Question | undefined = quiz.questions[idx]
  const answered = quiz.questions.filter((x) => (answers[x.id] ?? '').trim()).length
  const isLast = idx === total - 1

  const submit = async () => {
    setSubmitting(true)
    setError('')
    try {
      const attempt = await learning.submitQuiz(quiz.id, {
        answers,
        time_spent_secs: Math.round((Date.now() - startedAt.current) / 1000),
      })
      onSubmitted(attempt)
    } catch (e) {
      setError(errMsg(e, "Couldn't submit. Your answers are still here, try again."))
      setSubmitting(false)
    }
  }

  submitRef.current = () => { if (!submitting) void submit() }

  // Countdown for timed quizzes. At zero the answers given so far are submitted.
  useEffect(() => {
    if (!limitSecs) return
    const tick = () => {
      const left = Math.max(0, limitSecs - Math.round((Date.now() - startedAt.current) / 1000))
      setRemaining(left)
      if (left === 0 && !autoSubmitted.current) {
        autoSubmitted.current = true
        submitRef.current()
      }
    }
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [limitSecs])

  if (!q) {
    return (
      <Panel>
        <EmptyState title="This quiz has no questions." />
        <div className="px-5 pb-4"><Btn onClick={onExit}>Back</Btn></div>
      </Panel>
    )
  }

  const opts = q.type === 'true_false' && q.options.length === 0 ? ['True', 'False'] : q.options

  return (
    <Panel>
      <PanelHead
        label={`${quiz.title} · ${idx + 1} of ${total}`}
        right={
          <span className="flex items-center gap-3">
            {limitSecs > 0 && (
              <Mono className={remaining <= 60 ? 'text-fail' : 'text-low'}>
                {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, '0')} left
              </Mono>
            )}
            <Btn onClick={onExit}>Exit</Btn>
          </span>
        }
      />
      <div className="flex flex-col gap-4 px-5 pb-5">
        <div className="h-1 overflow-hidden rounded-full bg-ink/8" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={answered} aria-label="Answered questions">
          <div className="h-full bg-ink/40" style={{ width: `${(answered / total) * 100}%` }} />
        </div>

        <p className="text-[15px] font-medium text-hi">{q.prompt}</p>

        {q.type === 'short_answer' ? (
          <input
            className={INPUT}
            value={answers[q.id] ?? ''}
            onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
            placeholder="Your answer"
            aria-label="Your answer"
          />
        ) : (
          <div role="radiogroup" aria-label="Answer choices" className="flex flex-col gap-1.5">
            {opts.map((o) => (
              <label
                key={o}
                className={`flex cursor-pointer items-center gap-2.5 rounded-[10px] border px-3 py-2 text-[13px] text-mid hover:bg-ink/4 ${
                  answers[q.id] === o ? 'border-ink/40 bg-ink/4 text-hi' : 'border-line'
                }`}
              >
                <input
                  type="radio"
                  name={`ans-${q.id}`}
                  checked={answers[q.id] === o}
                  onChange={() => setAnswers((a) => ({ ...a, [q.id]: o }))}
                  className="size-3.5 accent-ink/70"
                />
                {o}
              </label>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between gap-3">
          <Btn onClick={() => setIdx((i) => Math.max(0, i - 1))} disabled={idx === 0 || submitting}>
            <span className="flex items-center gap-1.5"><ArrowLeft size={13} /> Back</span>
          </Btn>
          {isLast ? (
            <Btn kind="primary" onClick={() => void submit()} disabled={submitting || answered === 0}>
              {submitting ? 'Submitting…' : `Submit (${answered}/${total} answered)`}
            </Btn>
          ) : (
            <Btn kind="primary" onClick={() => setIdx((i) => Math.min(total - 1, i + 1))}>
              <span className="flex items-center gap-1.5">Next <ArrowRight size={13} /></span>
            </Btn>
          )}
        </div>
        {error && <Notice>{error}</Notice>}
      </div>
    </Panel>
  )
}

/* --------------------------------- results -------------------------------- */

function Results({ quiz, attempt, onDone, onRetake }: {
  quiz: Quiz
  attempt: QuizAttempt
  onDone: () => void
  onRetake: () => void
}) {
  return (
    <Panel>
      <PanelHead label={`${quiz.title} · results`} />
      <div className="flex flex-col gap-4 px-5 pb-5">
        <div className="flex items-baseline gap-3">
          <span className="text-[32px] font-semibold tracking-[-0.01em] text-hi">{attempt.score}%</span>
          <Mono className="text-low">
            {attempt.correct_count} of {attempt.total_questions} correct
          </Mono>
        </div>
        <ol className="flex flex-col gap-2">
          {attempt.breakdown.map((r, i) => (
            <li key={r.question_id} className="rounded-[10px] border border-line px-3 py-2.5">
              <div className="flex items-start justify-between gap-3">
                <p className="text-[13px] text-hi">{i + 1}. {r.prompt}</p>
                <Pill tone={r.is_correct ? 'ok' : 'failed'}>{r.is_correct ? 'correct' : 'incorrect'}</Pill>
              </div>
              <p className="mt-1.5 text-[12px] text-mid">Your answer: {fmtAnswer(r.user_answer)}</p>
              {!r.is_correct && <p className="text-[12px] text-mid">Correct answer: {r.correct_answer}</p>}
              {r.explanation && <p className="mt-1 text-[12px] text-low">{r.explanation}</p>}
            </li>
          ))}
        </ol>
        <div className="flex items-center justify-between gap-3">
          <Btn onClick={onDone}>Back to quizzes</Btn>
          <Btn kind="primary" onClick={onRetake}>Retake</Btn>
        </div>
      </div>
    </Panel>
  )
}

/* ---------------------------------- panel --------------------------------- */

export function QuizzesPanel() {
  const [view, setView] = useState<View>({ kind: 'list' })
  const [quizzes, setQuizzes] = useState<Quiz[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [confirmId, setConfirmId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError('')
    try {
      setQuizzes(await learning.quizzes())
    } catch (e) {
      setError(errMsg(e, "Couldn't load quizzes."))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const remove = async (id: string) => {
    setActionError('')
    try {
      await learning.deleteQuiz(id)
      setConfirmId(null)
      void load()
    } catch (e) {
      setActionError(errMsg(e, "Couldn't delete the quiz."))
    }
  }

  const backToList = () => {
    setView({ kind: 'list' })
    void load()
  }

  if (view.kind === 'create') {
    return <CreateQuiz onCancel={() => setView({ kind: 'list' })} onCreated={backToList} />
  }
  if (view.kind === 'take') {
    return (
      <TakeQuiz
        quiz={view.quiz}
        onExit={backToList}
        onSubmitted={(attempt) => setView({ kind: 'result', quiz: view.quiz, attempt })}
      />
    )
  }
  if (view.kind === 'result') {
    return (
      <Results
        quiz={view.quiz}
        attempt={view.attempt}
        onDone={backToList}
        onRetake={() => setView({ kind: 'take', quiz: view.quiz })}
      />
    )
  }

  return (
    <Panel>
      <PanelHead
        label="quizzes"
        right={
          <Btn kind="primary" onClick={() => setView({ kind: 'create' })}>
            <span className="flex items-center gap-1.5"><Plus size={13} /> New quiz</span>
          </Btn>
        }
      />
      <div className="flex flex-col gap-px px-2 pb-3">
        {loading && <p className="px-3 py-6 text-center text-[13px] text-low">Loading quizzes…</p>}
        {!loading && error && (
          <div className="flex flex-col items-center gap-2 px-3 py-6">
            <Notice>{error}</Notice>
            <Btn onClick={() => { setLoading(true); void load() }}>Retry</Btn>
          </div>
        )}
        {!loading && !error && quizzes.length === 0 && (
          <EmptyState title="No quizzes yet." hint="Create one to start practicing." />
        )}
        {actionError && <div className="px-3 pb-2"><Notice>{actionError}</Notice></div>}
        {!error &&
          quizzes.map((qz) => (
            <div key={qz.id} className="flex items-center gap-3 rounded-[10px] px-3 py-2 hover:bg-ink/4">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] text-hi">{qz.title}</p>
                <Mono className="text-low">
                  {qz.topic} · {qz.questions.length} questions · {qz.time_limit_mins} min
                </Mono>
              </div>
              {qz.best_score !== null && <Pill>best {qz.best_score}%</Pill>}
              {confirmId === qz.id ? (
                <>
                  <Btn kind="danger" onClick={() => void remove(qz.id)}>Confirm delete</Btn>
                  <Btn onClick={() => setConfirmId(null)}>Cancel</Btn>
                </>
              ) : (
                <>
                  <Btn kind="primary" onClick={() => setView({ kind: 'take', quiz: qz })} disabled={qz.questions.length === 0}>
                    Take
                  </Btn>
                  <button
                    type="button"
                    aria-label={`Delete quiz ${qz.title}`}
                    onClick={() => setConfirmId(qz.id)}
                    className="rounded-md p-1.5 text-low hover:bg-fail/10 hover:text-fail"
                  >
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </div>
          ))}
      </div>
    </Panel>
  )
}
