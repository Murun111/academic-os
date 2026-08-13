import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowUp, Brain, Plus } from 'lucide-react'
import { api } from '../lib/api'
import type { ChatMessage, ChatThread } from '../lib/types'
import { EmptyState, Mono, timeAgo } from '../components/ui'

// shown when no Ollama models are installed — the backend falls back to the
// bundled local AI regardless of the requested model name
const FALLBACK_MODELS = ['local ai']

// A rail refetch carries summaries only (api.threads sends no messages), so keep
// whatever content is already loaded, and keep threads that exist only in this
// tab — a brand-new one the student hasn't sent into yet is not on disk.
function mergeThreads(incoming: ChatThread[], prev: ChatThread[]): ChatThread[] {
  const old = new Map(prev.map((t) => [t.id, t]))
  const merged = incoming.map((t) => {
    const o = old.get(t.id)
    return o && o.messages.length > 0 ? { ...t, messages: o.messages } : t
  })
  const seen = new Set(incoming.map((t) => t.id))
  return [...prev.filter((t) => !seen.has(t.id)), ...merged]
}

export function Chat() {
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [models, setModels] = useState<string[]>(FALLBACK_MODELS)
  const [model, setModel] = useState(FALLBACK_MODELS[0])
  // Until this resolves the picker still reads 'local ai'. Sending that while
  // Ollama is running makes Ollama 404 the model, so gate send on it rather
  // than let the turn resolve against the wrong model.
  const [modelsReady, setModelsReady] = useState(false)

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
      .finally(() => setModelsReady(true))
  }, [])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  // a thread's messages arrive only when it is opened, so the pane says so
  const [loadingThread, setLoadingThread] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  // threads whose content we already have (fetched, or created in this tab)
  const loadedRef = useRef<Set<string>>(new Set())
  const loadingIdRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    void api.threads().then((t) => {
      setThreads(t)
      setActiveId(t[0]?.id ?? null)
    })
  }, [])

  const active = threads.find((t) => t.id === activeId) ?? null

  // pull the open thread's server-side state back in: a reply that finished
  // while the tab was in the background (or after a cancel) is not lost.
  const syncThread = async (id: string) => {
    const full = await api.thread(id)
    if (!full || full.messages.length === 0) return
    setThreads((ts) =>
      ts.map((t) =>
        // shorter than what's on screen means the turn is still in flight — keep ours
        t.id === id && full.messages.length >= t.messages.length ? { ...t, ...full } : t,
      ),
    )
  }

  const refresh = async (id: string | null) => {
    const t = await api.threads()
    setThreads((prev) => mergeThreads(t, prev))
    if (id) await syncThread(id)
  }

  // open a thread → fetch its messages once
  useEffect(() => {
    const id = activeId
    if (!id || loadedRef.current.has(id)) { loadingIdRef.current = null; setLoadingThread(false); return }
    loadedRef.current.add(id)
    loadingIdRef.current = id
    setLoadingThread(true)
    void api.thread(id)
      .then((full) => {
        if (full) setThreads((ts) => ts.map((t) => (t.id === id ? { ...t, ...full } : t)))
      })
      // a slower fetch for a thread the student already switched away from
      // must not clear the spinner on the one they are looking at now
      .finally(() => { if (loadingIdRef.current === id) setLoadingThread(false) })
  }, [activeId])

  // coming back to the tab: the rail and the open thread catch up
  useEffect(() => {
    const onFocus = () => { if (!busy) void refresh(activeId) }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [activeId, busy])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [active?.messages.length, busy])

  const newThread = () => {
    const t: ChatThread = {
      id: `local_${Date.now()}`, title: 'new thread', model,
      updated: new Date().toISOString(), messages: [],
    }
    loadedRef.current.add(t.id) // nothing on disk yet; don't try to fetch it
    setThreads((ts) => [t, ...ts])
    setActiveId(t.id)
  }

  const send = async () => {
    const text = draft.trim()
    if (!text || busy || !modelsReady) return
    setDraft('')
    setBusy(true)
    const mine: ChatMessage = { role: 'user', content: text, t: new Date().toISOString() }
    // No thread yet (fresh install, or everything deleted): create one on the
    // fly — otherwise the message has nowhere to land and silently vanishes.
    let id = activeId
    if (!id || !threads.some((t) => t.id === id)) {
      id = `local_${Date.now()}`
      loadedRef.current.add(id) // nothing on disk yet; don't try to fetch it
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
    const ctl = new AbortController()
    abortRef.current = ctl
    try {
      const replies = await api.chat(id, text, model, ctl.signal)
      setThreads((ts) => ts.map((t) => (t.id === id ? { ...t, messages: [...t.messages, ...replies] } : t)))
    } finally {
      abortRef.current = null
      setBusy(false)
      // the turn is persisted server-side; pick up the saved version (and any
      // reply that landed after a cancel) rather than trusting only local state
      void refresh(id)
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
              {/* summaries can arrive without a stamp — don't print "NaNd" */}
              <p className="mt-0.5 font-mono text-[11px] text-low">
                {t.model}{t.updated ? ` · ${timeAgo(t.updated)}` : ''}
              </p>
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
          {active && active.messages.length === 0 && loadingThread ? (
            <p className="px-1 font-mono text-[12px] text-low">loading thread…</p>
          ) : !active || active.messages.length === 0 ? (
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
                <div className="panel flex items-center gap-3 self-start rounded-2xl px-4 py-2.5">
                  <span className="font-mono text-[12px] text-low">thinking…</span>
                  <button
                    onClick={() => abortRef.current?.abort()}
                    className="font-mono text-[11px] text-low underline-offset-2 transition-colors hover:text-hi hover:underline"
                  >
                    cancel
                  </button>
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
            disabled={!draft.trim() || busy || !modelsReady}
            className="grid size-8 place-items-center rounded-lg bg-ink/8 text-hi transition-colors hover:bg-ink/13 disabled:opacity-30"
          >
            <ArrowUp size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}
