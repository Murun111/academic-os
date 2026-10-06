import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ArrowLeft, Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { learning, isUnavailable, isLearningApiError, type Deck } from '../../lib/learningApi'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../ui'

const FIELD =
  'w-full rounded-md border border-line bg-transparent px-2.5 py-1.5 text-[13px] text-hi placeholder:text-low focus:border-ink/30 focus:outline-none'

function errMsg(e: unknown): string {
  if (isUnavailable(e)) return 'The study service is unavailable right now. Try again in a moment.'
  if (isLearningApiError(e) && e.detail) return e.detail
  return 'Something went wrong. Try again.'
}

function IconBtn({
  label, onClick, danger, children,
}: { label: string; onClick: () => void; danger?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={`rounded-md p-1.5 transition-colors duration-150 ${
        danger ? 'text-low hover:bg-fail/10 hover:text-fail' : 'text-low hover:bg-ink/5 hover:text-hi'
      }`}
    >
      {children}
    </button>
  )
}

function ConfirmDelete({
  what, busy, onConfirm, onCancel,
}: { what: string; busy: boolean; onConfirm: () => void; onCancel: () => void }) {
  return (
    <span className="flex items-center gap-1" role="alertdialog" aria-label={`Confirm delete ${what}`}>
      <Mono className="text-fail">delete?</Mono>
      <Btn kind="danger" onClick={onConfirm} disabled={busy}>Yes, delete</Btn>
      <Btn onClick={onCancel} disabled={busy}>Cancel</Btn>
    </span>
  )
}

export function DecksPanel() {
  const [decks, setDecks] = useState<Deck[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [openId, setOpenId] = useState<string | null>(null)
  const [open, setOpen] = useState<Deck | null>(null)
  const [openLoading, setOpenLoading] = useState(false)

  const [newTitle, setNewTitle] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [confirmDeckId, setConfirmDeckId] = useState<string | null>(null)

  const [front, setFront] = useState('')
  const [back, setBack] = useState('')
  const [confirmCardId, setConfirmCardId] = useState<string | null>(null)

  const loadList = useCallback(async () => {
    try {
      setDecks(await learning.decks())
      setError(null)
    } catch (e) {
      setError(errMsg(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadOpen = useCallback(async (id: string) => {
    setOpenLoading(true)
    try {
      setOpen(await learning.deck(id))
      setError(null)
    } catch (e) {
      setOpen(null)
      setError(errMsg(e))
    } finally {
      setOpenLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadList()
  }, [loadList])

  useEffect(() => {
    if (openId) void loadOpen(openId)
    else setOpen(null)
  }, [openId, loadOpen])

  // run a mutation with shared busy/error handling; returns true on success
  const act = async (fn: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true)
    setActionError(null)
    try {
      await fn()
      return true
    } catch (e) {
      setActionError(errMsg(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  const createDeck = async (e: FormEvent) => {
    e.preventDefault()
    const title = newTitle.trim()
    if (!title) return
    if (await act(() => learning.createDeck({ title }))) {
      setNewTitle('')
      await loadList()
    }
  }

  const saveRename = async (id: string) => {
    const title = renameValue.trim()
    if (!title) return
    if (await act(() => learning.updateDeck(id, { title }))) {
      setRenamingId(null)
      await loadList()
      if (openId === id) await loadOpen(id)
    }
  }

  const removeDeck = async (id: string) => {
    if (await act(() => learning.deleteDeck(id))) {
      setConfirmDeckId(null)
      if (openId === id) setOpenId(null)
      await loadList()
    }
  }

  const addCard = async (e: FormEvent) => {
    e.preventDefault()
    if (!open) return
    const f = front.trim()
    const b = back.trim()
    if (!f || !b) return
    if (await act(() => learning.addCard(open.id, { front: f, back: b }))) {
      setFront('')
      setBack('')
      await loadOpen(open.id)
      void loadList()
    }
  }

  const removeCard = async (cardId: string) => {
    if (!open) return
    if (await act(() => learning.deleteCard(open.id, cardId))) {
      setConfirmCardId(null)
      await loadOpen(open.id)
      void loadList()
    }
  }

  const goBack = () => {
    setOpenId(null)
    setConfirmCardId(null)
    setActionError(null)
    setError(null)
  }

  const errorBanner = (msg: string | null) =>
    msg && (
      <p role="alert" className="mb-3 rounded-md border border-fail/30 px-3 py-2 text-[12px] text-fail">
        {msg}
      </p>
    )

  /* ------------------------------ deck detail ------------------------------ */
  if (openId) {
    return (
      <Panel>
        <PanelHead
          label={open ? open.title : 'deck'}
          right={
            <Btn onClick={goBack}>
              <span className="flex items-center gap-1.5"><ArrowLeft size={13} /> All decks</span>
            </Btn>
          }
        />
        <div className="px-5 pb-5">
          {errorBanner(error)}
          {errorBanner(actionError)}

          <form onSubmit={(e) => void addCard(e)} className="mb-4 flex flex-col gap-2" aria-label="Add card">
            <label className="flex flex-col gap-1">
              <span className="label-mono">front</span>
              <textarea
                value={front}
                onChange={(e) => setFront(e.target.value)}
                rows={2}
                placeholder="Question or prompt"
                className={FIELD}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="label-mono">back</span>
              <textarea
                value={back}
                onChange={(e) => setBack(e.target.value)}
                rows={2}
                placeholder="Answer"
                className={FIELD}
              />
            </label>
            <div>
              <button
                type="submit"
                disabled={busy || !front.trim() || !back.trim()}
                className="rounded-lg bg-ink/8 px-3 py-1.5 text-[13px] font-medium text-hi transition-colors duration-150 hover:bg-ink/12 disabled:pointer-events-none disabled:opacity-40"
              >
                <span className="flex items-center gap-1.5"><Plus size={13} /> Add card</span>
              </button>
            </div>
          </form>

          {openLoading && !open && <p className="py-6 text-center text-[13px] text-low" role="status">Loading cards…</p>}
          {open && open.cards.length === 0 && (
            <EmptyState title="No cards in this deck yet." hint="Add your first card above." />
          )}
          {open && open.cards.length > 0 && (
            <ul className="flex flex-col gap-px">
              {open.cards.map((c) => (
                <li key={c.id} className="flex items-start gap-3 rounded-[10px] px-3 py-2 hover:bg-ink/4">
                  <div className="min-w-0 flex-1">
                    <p className="whitespace-pre-wrap break-words text-[13px] text-hi">{c.front}</p>
                    <p className="whitespace-pre-wrap break-words text-[12px] text-low">{c.back}</p>
                  </div>
                  {confirmCardId === c.id ? (
                    <ConfirmDelete
                      what="card"
                      busy={busy}
                      onConfirm={() => void removeCard(c.id)}
                      onCancel={() => setConfirmCardId(null)}
                    />
                  ) : (
                    <IconBtn label={`Delete card "${c.front.slice(0, 40)}"`} danger onClick={() => setConfirmCardId(c.id)}>
                      <Trash2 size={14} />
                    </IconBtn>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>
    )
  }

  /* -------------------------------- deck list ------------------------------- */
  return (
    <Panel>
      <PanelHead label="decks" right={<Mono className="text-low">{decks.length} total</Mono>} />
      <div className="px-5 pb-5">
        {errorBanner(error)}
        {errorBanner(actionError)}

        <form onSubmit={(e) => void createDeck(e)} className="mb-4 flex items-center gap-2" aria-label="Create deck">
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="New deck title…"
            aria-label="New deck title"
            className={FIELD}
          />
          <button
            type="submit"
            disabled={busy || !newTitle.trim()}
            className="shrink-0 rounded-lg bg-ink/8 px-3 py-1.5 text-[13px] font-medium text-hi transition-colors duration-150 hover:bg-ink/12 disabled:pointer-events-none disabled:opacity-40"
          >
            <span className="flex items-center gap-1.5"><Plus size={13} /> Create</span>
          </button>
        </form>

        {loading && <p className="py-6 text-center text-[13px] text-low" role="status">Loading decks…</p>}
        {!loading && !error && decks.length === 0 && (
          <EmptyState title="No decks yet." hint="Create one above to start adding flashcards." />
        )}
        {!loading && error && decks.length === 0 && (
          <div className="flex justify-center py-4"><Btn onClick={() => { setLoading(true); void loadList() }}>Retry</Btn></div>
        )}

        <ul className="flex flex-col gap-px">
          {decks.map((d) => (
            <li key={d.id} className="flex items-center gap-3 rounded-[10px] px-3 py-2 hover:bg-ink/4">
              {renamingId === d.id ? (
                <form
                  className="flex min-w-0 flex-1 items-center gap-1"
                  onSubmit={(e) => { e.preventDefault(); void saveRename(d.id) }}
                >
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Escape') setRenamingId(null) }}
                    aria-label={`Rename deck ${d.title}`}
                    className={FIELD}
                  />
                  <IconBtn label="Save name" onClick={() => void saveRename(d.id)}><Check size={14} /></IconBtn>
                  <IconBtn label="Cancel rename" onClick={() => setRenamingId(null)}><X size={14} /></IconBtn>
                </form>
              ) : (
                <button
                  type="button"
                  onClick={() => { setOpenId(d.id); setActionError(null); setConfirmDeckId(null) }}
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                  aria-label={`Open deck ${d.title}`}
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-hi">{d.title}</span>
                  {d.due_cards > 0 && <Pill tone="pend">{d.due_cards} due</Pill>}
                  <Mono className="shrink-0 text-low">{d.total_cards} cards</Mono>
                </button>
              )}

              {renamingId !== d.id &&
                (confirmDeckId === d.id ? (
                  <ConfirmDelete
                    what={`deck ${d.title}`}
                    busy={busy}
                    onConfirm={() => void removeDeck(d.id)}
                    onCancel={() => setConfirmDeckId(null)}
                  />
                ) : (
                  <span className="flex shrink-0 items-center">
                    <IconBtn label={`Rename deck ${d.title}`} onClick={() => { setRenamingId(d.id); setRenameValue(d.title) }}>
                      <Pencil size={14} />
                    </IconBtn>
                    <IconBtn label={`Delete deck ${d.title}`} danger onClick={() => setConfirmDeckId(d.id)}>
                      <Trash2 size={14} />
                    </IconBtn>
                  </span>
                ))}
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  )
}
