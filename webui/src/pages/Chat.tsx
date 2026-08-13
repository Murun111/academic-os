import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowUp, Brain, Plus } from 'lucide-react'
import { api } from '../lib/api'
import type { ChatMessage, ChatThread } from '../lib/types'
import { EmptyState, Mono, timeAgo } from '../components/ui'

// shown when no Ollama models are installed — the backend falls back to the
// bundled local AI regardless of the requested model name
const FALLBACK_MODELS = ['local ai']

export function Chat() {
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [models, setModels] = useState<string[]>(FALLBACK_MODELS)
  const [model, setModel] = useState(FALLBACK_MODELS[0])

  // the picker lists what is actually installed, not a hardcoded wishlist
  useEffect(() => {
    void fetch('/api/llms/models?backend=ollama')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        const ids = (d?.models ?? []).map((m: { id: string }) => m.id)
        if (ids.length > 0) {
          setModels(ids)
          setModel(ids[0])
        }
      })
      .catch(() => {})
  }, [])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void api.threads().then((t) => {
      setThreads(t)
      setActiveId(t[0]?.id ?? null)
    })
  }, [])

  const active = threads.find((t) => t.id === activeId) ?? null

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [active?.messages.length, busy])

  const newThread = () => {
    const t: ChatThread = {
      id: `local_${Date.now()}`, title: 'new thread', model,
      updated: new Date().toISOString(), messages: [],
    }
    setThreads((ts) => [t, ...ts])
    setActiveId(t.id)
  }

  const send = async () => {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    setBusy(true)
    const mine: ChatMessage = { role: 'user', content: text, t: new Date().toISOString() }
    // No thread yet (fresh install, or everything deleted): create one on the
    // fly — otherwise the message has nowhere to land and silently vanishes.
    let id = activeId
    if (!id || !threads.some((t) => t.id === id)) {
      id = `local_${Date.now()}`
      setThreads((ts) => [
        { id: id as string, title: 'new thread', model, updated: mine.t, messages: [] },
        ...ts,
      ])
      setActiveId(id)
    }
    setThreads((ts) =>
      ts.map((t) =>
        t.id === id
          ? {
              ...t,
              // first message names the thread
              title: t.messages.length === 0 ? text.slice(0, 42) : t.title,
              updated: mine.t,
              messages: [...t.messages, mine],
            }
          : t,
      ),
    )
    try {
      const replies = await api.chat(id, text, model)
      setThreads((ts) => ts.map((t) => (t.id === id ? { ...t, messages: [...t.messages, ...replies] } : t)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-[1100px] gap-5">
      {/* thread rail */}
      <div className="hidden w-[220px] shrink-0 pt-1 md:block">
        <div className="mb-3 flex items-center justify-between px-1">
          <p className="label-mono">threads</p>
          <button
            onClick={newThread}
            title="New thread"
            className="grid size-6 place-items-center rounded-md text-low transition-colors hover:bg-ink/5 hover:text-hi"
          >
            <Plus size={13} />
          </button>
        </div>
        <div className="flex flex-col gap-0.5">
          {threads.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveId(t.id)}
              className={`rounded-[10px] px-2.5 py-2 text-left transition-colors duration-150 ${
                t.id === activeId ? 'bg-ink/6' : 'hover:bg-ink/4'
              }`}
            >
              <p className={`truncate text-[13px] ${t.id === activeId ? 'text-hi' : 'text-mid'}`}>{t.title}</p>
              <p className="mt-0.5 font-mono text-[11px] text-low">{t.model} · {timeAgo(t.updated)}</p>
            </button>
          ))}
        </div>
      </div>

      {/* conversation */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* stable gutter on BOTH edges: with macOS "always show scrollbars" the
            scrollbar otherwise eats ~15px off the right only, leaving the message
            column narrower than — and off-centre from — the composer below it. */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto pt-1 pb-4 [scrollbar-gutter:stable_both-edges]"
        >
          {!active || active.messages.length === 0 ? (
            <EmptyState title="Say something." hint="Ask about your deadlines, essays, or courses." />
          ) : (
            <div className="flex flex-col gap-4">
              {active.messages.map((m, i) =>
                m.role === 'memory' ? (
                  <div key={i} className="flex items-center gap-2 self-start rounded-full border border-hairline px-3 py-1">
                    <Brain size={12} className="text-low" />
                    <span className="font-mono text-[11px] text-low">{m.content}</span>
                  </div>
                ) : (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                    className={m.role === 'user' ? 'self-end' : 'self-start'}
                  >
                    <div
                      className={`max-w-[62ch] rounded-2xl px-4 py-2.5 text-[14px] leading-relaxed ${
                        m.role === 'user' ? 'bg-ink/8 text-hi' : 'panel text-mid'
                      }`}
                    >
                      {m.content}
                    </div>
                    {m.role === 'assistant' && m.tokens && (
                      <Mono className="mt-1 block px-1 text-low">
                        {m.tokens} tok · {((m.elapsedMs ?? 0) / 1000).toFixed(1)}s
                      </Mono>
                    )}
                  </motion.div>
                ),
              )}
              {busy && (
                <div className="panel self-start rounded-2xl px-4 py-2.5">
                  <span className="font-mono text-[12px] text-low">thinking…</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* composer */}
        <div className="panel mb-1 flex items-end gap-2 p-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() }
            }}
            rows={Math.min(5, Math.max(1, draft.split('\n').length))}
            placeholder="Message the OS…"
            className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-[14px] text-hi outline-none placeholder:text-low"
          />
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="rounded-lg bg-transparent px-1 py-1.5 font-mono text-[11.5px] text-low outline-none hover:text-mid"
          >
            {models.map((m) => <option key={m} value={m} className="bg-raise">{m}</option>)}
          </select>
          <button
            onClick={() => void send()}
            disabled={!draft.trim() || busy}
            className="grid size-8 place-items-center rounded-lg bg-ink/8 text-hi transition-colors hover:bg-ink/13 disabled:opacity-30"
          >
            <ArrowUp size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}
