import { Fragment, useCallback, useEffect, useState, type ReactNode } from 'react'
import { ArrowLeft, Plus, Trash2 } from 'lucide-react'
import {
  learning,
  isUnavailable,
  type GuideCreate,
  type StudyGuide,
} from '../../lib/learningApi'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../ui'

/* Study guides: list, create, read, delete. Content is lightweight markdown
   (headings, bullets, numbered lists, bold/italic/code) rendered without a
   markdown dependency. */

const inputCls =
  'w-full rounded-md border border-line bg-transparent px-2.5 py-1.5 text-[13px] text-hi placeholder:text-low focus:border-ink/30 focus:outline-none'

function errMessage(e: unknown, fallback: string): string {
  if (isUnavailable(e)) return 'The study service is not reachable right now. Try again in a moment.'
  return e instanceof Error && e.message ? e.message : fallback
}

function Notice({ children, tone = 'fail' }: { children: ReactNode; tone?: 'fail' | 'low' }) {
  return (
    <p role="alert" className={`px-5 py-3 text-[12.5px] ${tone === 'fail' ? 'text-fail' : 'text-low'}`}>
      {children}
    </p>
  )
}

/* ------------------------- tiny markdown renderer ------------------------- */

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('**')) out.push(<strong key={i++} className="font-semibold text-hi">{tok.slice(2, -2)}</strong>)
    else if (tok.startsWith('`')) out.push(<code key={i++} className="rounded bg-raise2 px-1 font-mono text-[12px]">{tok.slice(1, -1)}</code>)
    else out.push(<em key={i++}>{tok.slice(1, -1)}</em>)
    last = m.index + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let para: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let code: string[] | null = null
  let k = 0

  const flushPara = () => {
    if (para.length) {
      blocks.push(<p key={k++} className="text-[13.5px] leading-relaxed text-mid">{inline(para.join(' '))}</p>)
      para = []
    }
  }
  const flushList = () => {
    if (!list) return
    const items = list.items.map((t, j) => <li key={j}>{inline(t)}</li>)
    blocks.push(
      list.ordered ? (
        <ol key={k++} className="list-decimal space-y-1 pl-5 text-[13.5px] leading-relaxed text-mid">{items}</ol>
      ) : (
        <ul key={k++} className="list-disc space-y-1 pl-5 text-[13.5px] leading-relaxed text-mid">{items}</ul>
      ),
    )
    list = null
  }

  for (const raw of lines) {
    if (code) {
      if (raw.trim().startsWith('```')) {
        blocks.push(
          <pre key={k++} className="overflow-x-auto rounded-[10px] bg-raise2 px-3 py-2 font-mono text-[12px] text-mid">
            {code.join('\n')}
          </pre>,
        )
        code = null
      } else code.push(raw)
      continue
    }
    const line = raw.trimEnd()
    if (line.trim().startsWith('```')) { flushPara(); flushList(); code = []; continue }
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) {
      flushPara(); flushList()
      const level = h[1].length
      const cls =
        level === 1 ? 'text-[18px] font-semibold text-hi'
        : level === 2 ? 'text-[15px] font-semibold text-hi'
        : 'text-[13.5px] font-semibold text-hi'
      blocks.push(<h3 key={k++} className={`${cls} pt-2`}>{inline(h[2])}</h3>)
      continue
    }
    const ul = /^\s*[-*+]\s+(.*)$/.exec(line)
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (ul || ol) {
      flushPara()
      const ordered = !!ol
      if (list && list.ordered !== ordered) flushList()
      if (!list) list = { ordered, items: [] }
      list.items.push((ul ?? ol)![1])
      continue
    }
    if (!line.trim()) { flushPara(); flushList(); continue }
    flushList()
    para.push(line.trim())
  }
  if (code) blocks.push(<pre key={k++} className="overflow-x-auto rounded-[10px] bg-raise2 px-3 py-2 font-mono text-[12px] text-mid">{code.join('\n')}</pre>)
  flushPara(); flushList()
  return <div className="space-y-3">{blocks.map((b, i) => <Fragment key={i}>{b}</Fragment>)}</div>
}

/* --------------------------------- views ---------------------------------- */

function splitLines(s: string): string[] {
  return s.split('\n').map((x) => x.trim()).filter(Boolean)
}

function CreateForm({ onCreated, onCancel }: { onCreated: (g: StudyGuide) => void; onCancel: () => void }) {
  const [title, setTitle] = useState('')
  const [topic, setTopic] = useState('')
  const [content, setContent] = useState('')
  const [takeaways, setTakeaways] = useState('')
  const [formulas, setFormulas] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid = title.trim() && topic.trim() && content.trim()

  const submit = async () => {
    if (!valid || saving) return
    setSaving(true)
    setError(null)
    const body: GuideCreate = {
      title: title.trim(),
      topic: topic.trim(),
      content: content.trim(),
      key_takeaways: splitLines(takeaways),
      formulas: splitLines(formulas),
    }
    try {
      onCreated(await learning.createGuide(body))
    } catch (e) {
      setError(errMessage(e, 'Could not save the guide.'))
      setSaving(false)
    }
  }

  return (
    <Panel>
      <PanelHead label="new guide" />
      <form
        className="space-y-3 px-5 pb-5"
        onSubmit={(e) => { e.preventDefault(); void submit() }}
      >
        <label className="block">
          <span className="label-mono mb-1 block">title</span>
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Photosynthesis: exam guide" />
        </label>
        <label className="block">
          <span className="label-mono mb-1 block">topic</span>
          <input className={inputCls} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Photosynthesis" />
        </label>
        <label className="block">
          <span className="label-mono mb-1 block">content (markdown)</span>
          <textarea className={`${inputCls} min-h-[160px] resize-y`} value={content} onChange={(e) => setContent(e.target.value)} placeholder={'## Light reactions\n- Occur in the thylakoid\n- Produce ATP and NADPH'} />
        </label>
        <label className="block">
          <span className="label-mono mb-1 block">key takeaways (one per line, optional)</span>
          <textarea className={`${inputCls} min-h-[64px] resize-y`} value={takeaways} onChange={(e) => setTakeaways(e.target.value)} />
        </label>
        <label className="block">
          <span className="label-mono mb-1 block">formulas (one per line, optional)</span>
          <textarea className={`${inputCls} min-h-[48px] resize-y font-mono`} value={formulas} onChange={(e) => setFormulas(e.target.value)} />
        </label>
        {error && <p role="alert" className="text-[12.5px] text-fail">{error}</p>}
        <div className="flex items-center gap-2">
          <Btn kind="primary" onClick={() => void submit()} disabled={!valid || saving}>
            {saving ? 'Saving…' : 'Save guide'}
          </Btn>
          <Btn onClick={onCancel} disabled={saving}>Cancel</Btn>
        </div>
      </form>
    </Panel>
  )
}

function GuideView({
  guide, onBack, onDelete,
}: { guide: StudyGuide; onBack: () => void; onDelete: (id: string) => Promise<string | null> }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const doDelete = async () => {
    setBusy(true)
    const err = await onDelete(guide.id)
    if (err) { setError(err); setBusy(false); setConfirming(false) }
  }

  return (
    <Panel>
      <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-2">
        <Btn onClick={onBack}>
          <span className="flex items-center gap-1.5"><ArrowLeft size={13} aria-hidden /> All guides</span>
        </Btn>
        {confirming ? (
          <div className="flex items-center gap-1">
            <span className="text-[12.5px] text-mid">Delete this guide?</span>
            <Btn kind="danger" onClick={() => void doDelete()} disabled={busy}>{busy ? 'Deleting…' : 'Yes, delete'}</Btn>
            <Btn onClick={() => setConfirming(false)} disabled={busy}>Cancel</Btn>
          </div>
        ) : (
          <Btn kind="danger" onClick={() => setConfirming(true)}>
            <span className="flex items-center gap-1.5"><Trash2 size={13} aria-hidden /> Delete</span>
          </Btn>
        )}
      </div>
      {error && <Notice>{error}</Notice>}
      <article className="space-y-5 px-5 pt-2 pb-6">
        <header>
          <h2 className="text-[20px] font-semibold tracking-[-0.01em]">{guide.title}</h2>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Pill>{guide.topic}</Pill>
            {guide.course_name && <Pill>{guide.course_name}</Pill>}
            {guide.tags.map((t) => <Pill key={t}>{t}</Pill>)}
          </div>
        </header>
        {guide.key_takeaways.length > 0 && (
          <section aria-label="Key takeaways">
            <p className="label-mono mb-2">key takeaways</p>
            <ul className="list-disc space-y-1 pl-5 text-[13.5px] leading-relaxed text-mid">
              {guide.key_takeaways.map((t, i) => <li key={i}>{inline(t)}</li>)}
            </ul>
          </section>
        )}
        <Markdown source={guide.content} />
        {guide.formulas.length > 0 && (
          <section aria-label="Formulas">
            <p className="label-mono mb-2">formulas</p>
            <ul className="space-y-1.5">
              {guide.formulas.map((f, i) => (
                <li key={i} className="rounded-[10px] bg-raise2 px-3 py-1.5 font-mono text-[12.5px] text-hi">{f}</li>
              ))}
            </ul>
          </section>
        )}
      </article>
    </Panel>
  )
}

export function GuidesPanel() {
  const [guides, setGuides] = useState<StudyGuide[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setGuides(await learning.guides())
    } catch (e) {
      setError(errMessage(e, 'Could not load study guides.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const open = guides.find((g) => g.id === openId) ?? null

  const handleDelete = async (id: string): Promise<string | null> => {
    try {
      await learning.deleteGuide(id)
      setGuides((gs) => gs.filter((g) => g.id !== id))
      setOpenId(null)
      return null
    } catch (e) {
      if (e instanceof Error && 'status' in e && (e as { status: number }).status === 404) {
        setGuides((gs) => gs.filter((g) => g.id !== id))
        setOpenId(null)
        return null
      }
      return errMessage(e, 'Could not delete the guide.')
    }
  }

  if (creating) {
    return (
      <CreateForm
        onCancel={() => setCreating(false)}
        onCreated={(g) => { setGuides((gs) => [g, ...gs]); setCreating(false); setOpenId(g.id) }}
      />
    )
  }

  if (open) {
    return <GuideView guide={open} onBack={() => setOpenId(null)} onDelete={handleDelete} />
  }

  return (
    <Panel>
      <PanelHead
        label="study guides"
        right={
          <div className="flex items-center gap-2">
            <Mono className="text-low">{guides.length}</Mono>
            <Btn kind="primary" onClick={() => setCreating(true)}>
              <span className="flex items-center gap-1.5"><Plus size={13} aria-hidden /> New guide</span>
            </Btn>
          </div>
        }
      />
      {loading ? (
        <p role="status" className="px-5 pb-6 text-[12.5px] text-low">Loading guides…</p>
      ) : error ? (
        <div className="pb-4">
          <Notice>{error}</Notice>
          <div className="px-5"><Btn onClick={() => { setLoading(true); void load() }}>Retry</Btn></div>
        </div>
      ) : guides.length === 0 ? (
        <EmptyState title="No study guides yet" hint="Create one to keep your notes, takeaways and formulas in one place." />
      ) : (
        <ul className="px-2 pb-3">
          {guides.map((g) => (
            <li key={g.id}>
              <button
                type="button"
                onClick={() => setOpenId(g.id)}
                className="flex w-full items-center gap-3 rounded-[10px] px-3 py-2 text-left hover:bg-ink/4 focus-visible:outline focus-visible:outline-1 focus-visible:outline-ink/30"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] text-hi">{g.title}</span>
                  <span className="block truncate text-[12px] text-low">
                    {g.topic}{g.course_name ? ` · ${g.course_name}` : ''}
                  </span>
                </span>
                <Mono className="shrink-0 text-low">{(g.updated_at || g.created_at).slice(0, 10)}</Mono>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
