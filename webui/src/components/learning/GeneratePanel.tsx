import { useCallback, useEffect, useState } from 'react'
import { Sparkles } from 'lucide-react'
import {
  learning, isUnavailable,
  type Deck, type Difficulty, type GeneratedCard, type GeneratedQuestion, type GuideData,
} from '../../lib/learningApi'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../ui'

type Kind = 'flashcards' | 'quiz' | 'guide'
const KINDS: { id: Kind; label: string }[] = [
  { id: 'flashcards', label: 'Flashcards' },
  { id: 'quiz', label: 'Quiz' },
  { id: 'guide', label: 'Study guide' },
]
const DIFFICULTIES: Difficulty[] = ['easy', 'medium', 'hard']
const NEW_DECK = '__new__'

type Result =
  | { kind: 'flashcards'; topic: string; cards: GeneratedCard[] }
  | { kind: 'quiz'; topic: string; questions: GeneratedQuestion[] }
  | { kind: 'guide'; topic: string; guide: GuideData }

const field =
  'w-full rounded-md border border-line bg-transparent px-2.5 py-1.5 text-[13px] text-hi placeholder:text-low focus:outline-none focus:border-ink/30'

function errorMessage(e: unknown): string {
  if (isUnavailable(e)) {
    return 'The local AI model is not reachable right now. Start Ollama and try again.'
  }
  return e instanceof Error && e.message ? e.message : 'Something went wrong. Try again.'
}

export function GeneratePanel() {
  const [kind, setKind] = useState<Kind>('flashcards')
  const [topic, setTopic] = useState('')
  const [notes, setNotes] = useState('')
  const [count, setCount] = useState(8)
  const [difficulty, setDifficulty] = useState<Difficulty>('medium')

  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Result | null>(null)

  const [decks, setDecks] = useState<Deck[]>([])
  const [decksLoading, setDecksLoading] = useState(true)
  const [decksError, setDecksError] = useState(false)
  const [target, setTarget] = useState(NEW_DECK)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  const loadDecks = useCallback(async () => {
    setDecksError(false)
    try {
      setDecks(await learning.decks())
    } catch {
      setDecksError(true)
    } finally {
      setDecksLoading(false)
    }
  }, [])

  useEffect(() => { void loadDecks() }, [loadDecks])

  const canGenerate = !generating && (topic.trim() !== '' || notes.trim() !== '')

  async function generate() {
    const t = topic.trim() || notes.trim().slice(0, 60)
    const context_text = notes.trim() || undefined
    setGenerating(true)
    setError(null)
    setResult(null)
    setSaveMsg(null)
    setSaveErr(null)
    try {
      if (kind === 'flashcards') {
        const r = await learning.generateFlashcards({ topic: t, context_text, count, difficulty })
        setResult({ kind, topic: t, cards: r.cards })
      } else if (kind === 'quiz') {
        const r = await learning.generateQuiz({ topic: t, context_text, num_questions: count, difficulty })
        setResult({ kind, topic: t, questions: r.questions })
      } else {
        const r = await learning.generateGuide({ topic: t, context_text })
        setResult({ kind, topic: t, guide: r.guide_data })
      }
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setGenerating(false)
    }
  }

  async function save() {
    if (!result) return
    setSaving(true)
    setSaveMsg(null)
    setSaveErr(null)
    try {
      if (result.kind === 'flashcards') {
        if (target === NEW_DECK) {
          await learning.createDeck({ title: result.topic, cards: result.cards })
          setSaveMsg('Saved as a new deck.')
        } else {
          for (const c of result.cards) await learning.addCard(target, c)
          setSaveMsg('Cards added to the deck.')
        }
        void loadDecks()
      } else if (result.kind === 'quiz') {
        await learning.createQuiz({
          title: result.topic, topic: result.topic,
          questions: result.questions.map((q) => ({
            prompt: q.prompt, type: q.type, options: q.options,
            correct_answer: q.correct_answer, explanation: q.explanation, concept: q.concept,
          })),
        })
        setSaveMsg('Saved as a quiz.')
      } else {
        const g = result.guide
        await learning.createGuide({
          title: g.title || result.topic, topic: result.topic, content: g.summary_markdown,
          key_takeaways: g.key_takeaways, formulas: g.formulas, tags: g.tags,
        })
        setSaveMsg('Saved as a study guide.')
      }
    } catch (e) {
      setSaveErr(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  const hasCount = kind !== 'guide'

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHead label="Generate with AI" />
        <div className="space-y-3 px-5 pb-5">
          <div role="radiogroup" aria-label="What to generate" className="flex flex-wrap gap-1.5">
            {KINDS.map((k) => (
              <button
                key={k.id}
                role="radio"
                aria-checked={kind === k.id}
                onClick={() => { setKind(k.id); setResult(null); setError(null) }}
                className={`rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors duration-150 ${
                  kind === k.id ? 'bg-ink/8 text-hi' : 'text-mid hover:bg-ink/5 hover:text-hi'
                }`}
              >
                {k.label}
              </button>
            ))}
          </div>

          <label className="block">
            <span className="label-mono mb-1 block">Topic</span>
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. Krebs cycle"
              className={field}
            />
          </label>

          <label className="block">
            <span className="label-mono mb-1 block">Notes (optional)</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={6}
              placeholder="Paste lecture notes or a passage to generate from"
              className={`${field} resize-y`}
            />
          </label>

          <div className="flex flex-wrap items-end gap-3">
            {hasCount && (
              <>
                <label className="block">
                  <span className="label-mono mb-1 block">{kind === 'quiz' ? 'Questions' : 'Cards'}</span>
                  <input
                    type="number" min={1} max={30} value={count}
                    onChange={(e) => setCount(Math.min(30, Math.max(1, Number(e.target.value) || 1)))}
                    className={`${field} w-20 font-mono`}
                  />
                </label>
                <label className="block">
                  <span className="label-mono mb-1 block">Difficulty</span>
                  <select
                    value={difficulty}
                    onChange={(e) => setDifficulty(e.target.value as Difficulty)}
                    className={`${field} w-28`}
                  >
                    {DIFFICULTIES.map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </label>
              </>
            )}
            <Btn kind="primary" onClick={() => void generate()} disabled={!canGenerate}>
              <span className="flex items-center gap-1.5">
                <Sparkles size={13} aria-hidden="true" />
                {generating ? 'Generating…' : 'Generate'}
              </span>
            </Btn>
          </div>
        </div>
      </Panel>

      {error && (
        <p role="alert" className="rounded-[10px] border border-line bg-ink/4 px-4 py-3 text-[13px] text-mid">
          {error}
        </p>
      )}

      {generating && (
        <Panel><div role="status"><EmptyState title="Generating…" hint="A local model can take a minute." /></div></Panel>
      )}

      {!generating && !error && !result && (
        <Panel><EmptyState title="Nothing generated yet" hint="Add a topic or paste notes, then press Generate." /></Panel>
      )}

      {result && !generating && (
        <Panel>
          <PanelHead label={`Result: ${result.topic}`} right={<Pill>{kind}</Pill>} />
          <div className="space-y-2 px-5 pb-4">
            {result.kind === 'flashcards' && (
              result.cards.length === 0 ? <EmptyState title="The model returned no cards" /> :
              result.cards.map((c, i) => (
                <div key={i} className="rounded-[10px] border border-hairline px-3 py-2">
                  <p className="text-[13px] text-hi">{c.front}</p>
                  <p className="mt-1 text-[13px] text-mid">{c.back}</p>
                </div>
              ))
            )}
            {result.kind === 'quiz' && (
              result.questions.length === 0 ? <EmptyState title="The model returned no questions" /> :
              result.questions.map((q, i) => (
                <div key={i} className="rounded-[10px] border border-hairline px-3 py-2">
                  <p className="text-[13px] text-hi">{i + 1}. {q.prompt}</p>
                  {q.options.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {q.options.map((o, j) => <li key={j} className="text-[13px] text-mid">{o}</li>)}
                    </ul>
                  )}
                  <Mono className="mt-1 block text-low">answer: {q.correct_answer}</Mono>
                </div>
              ))
            )}
            {result.kind === 'guide' && (
              <div className="space-y-3">
                <h3 className="text-[15px] font-semibold text-hi">{result.guide.title}</h3>
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-mid">
                  {result.guide.summary_markdown}
                </p>
                {result.guide.key_takeaways.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-mid">
                    {result.guide.key_takeaways.map((t, i) => <li key={i}>{t}</li>)}
                  </ul>
                )}
                {result.guide.formulas.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {result.guide.formulas.map((f, i) => <Pill key={i}>{f}</Pill>)}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-hairline px-5 py-3">
            {result.kind === 'flashcards' && (
              <label className="flex items-center gap-2">
                <span className="label-mono">Deck</span>
                <select
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  disabled={decksLoading}
                  aria-label="Save into deck"
                  className={`${field} w-56`}
                >
                  <option value={NEW_DECK}>New deck: {result.topic.slice(0, 30)}</option>
                  {decks.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
                </select>
              </label>
            )}
            <Btn kind="primary" onClick={() => void save()} disabled={saving || !!saveMsg}>
              {saving ? 'Saving…' : 'Save'}
            </Btn>
            {result.kind === 'flashcards' && decksError && (
              <Mono className="text-low">Could not load decks; saving makes a new one.</Mono>
            )}
            {saveMsg && <Mono className="text-run" >{saveMsg}</Mono>}
            {saveErr && <span role="alert" className="text-[12px] text-fail">{saveErr}</span>}
          </div>
        </Panel>
      )}
    </div>
  )
}
