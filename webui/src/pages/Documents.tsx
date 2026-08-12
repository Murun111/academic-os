import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Link2, Plus, Search } from 'lucide-react'
import {
  DOCUMENT_KINDS,
  documentsApi,
  type Document,
  type DocumentKind,
} from '../lib/documentsApi'
import { Btn, EmptyState, Mono, Panel, Pill, timeAgo } from '../components/ui'

const KIND_FILTERS: Array<DocumentKind | 'all'> = ['all', ...DOCUMENT_KINDS]

const STATUS_TONE: Record<string, string> = {
  draft: 'pending',
  in_review: 'pending',
  final: 'running',
}

export function Documents() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [kindFilter, setKindFilter] = useState<DocumentKind | 'all'>('all')
  const [tagFilter, setTagFilter] = useState('')
  const [titleQuery, setTitleQuery] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const [showAdd, setShowAdd] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newKind, setNewKind] = useState<DocumentKind>('essay')

  const load = () => {
    setLoading(true)
    void documentsApi
      .list({ kind: kindFilter === 'all' ? undefined : kindFilter, tag: tagFilter || undefined })
      .then((items) => {
        setDocuments(items)
        setError(false)
        setLoading(false)
      })
      .catch(() => {
        setError(true)
        setLoading(false)
      })
  }

  useEffect(() => {
    const t = setTimeout(load, 150)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kindFilter, tagFilter])

  const visible = documents.filter((d) =>
    titleQuery.trim() === '' ? true : d.title.toLowerCase().includes(titleQuery.trim().toLowerCase()),
  )

  const addDocument = async () => {
    if (!newTitle.trim()) return
    const res = await documentsApi.add({ title: newTitle.trim(), kind: newKind })
    if (res?.ok) {
      setNewTitle('')
      setShowAdd(false)
      load()
    }
  }

  return (
    <div className="mx-auto max-w-[900px]">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <p className="label-mono mb-1">essays · cv · transcripts · lors · certificates</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Documents</h1>
        </div>
        <Btn kind="primary" className="flex items-center gap-1.5" onClick={() => setShowAdd((s) => !s)}>
          <Plus size={13} /> Add document
        </Btn>
      </div>

      {showAdd && (
        <Panel className="mb-5 flex items-center gap-2.5 px-3.5 py-2.5">
          <input
            autoFocus
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void addDocument() }}
            placeholder="Document title…"
            className="flex-1 bg-transparent text-[13.5px] text-hi outline-none placeholder:text-low"
          />
          <select
            value={newKind}
            onChange={(e) => setNewKind(e.target.value as DocumentKind)}
            className="rounded-lg bg-transparent px-1 py-1.5 font-mono text-[11.5px] text-low outline-none hover:text-mid"
          >
            {DOCUMENT_KINDS.map((k) => (
              <option key={k} value={k} className="bg-raise">{k}</option>
            ))}
          </select>
          <Btn kind="primary" onClick={() => void addDocument()} disabled={!newTitle.trim()}>
            Create
          </Btn>
        </Panel>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="panel flex items-center gap-2.5 px-3.5 py-2">
          <Search size={14} className="text-low" />
          <input
            value={titleQuery}
            onChange={(e) => setTitleQuery(e.target.value)}
            placeholder="Search by title…"
            className="w-[200px] bg-transparent text-[13.5px] text-hi outline-none placeholder:text-low"
          />
        </div>
        <div className="panel flex items-center gap-2.5 px-3.5 py-2">
          <Mono className="text-low">tag</Mono>
          <input
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            placeholder="filter…"
            className="w-[120px] bg-transparent text-[13.5px] text-hi outline-none placeholder:text-low"
          />
        </div>
        <div className="flex gap-1">
          {KIND_FILTERS.map((k) => (
            <button
              key={k}
              onClick={() => setKindFilter(k)}
              className={`rounded-full px-3 py-1 font-mono text-[11.5px] transition-colors duration-150 ${
                kindFilter === k ? 'bg-ink/8 text-hi' : 'text-low hover:text-mid'
              }`}
            >
              {k}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <Panel className="mb-5">
          <EmptyState title="Couldn't reach the documents service." hint="Check the backend is running." />
        </Panel>
      )}

      {!error && loading && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => <div key={i} className="panel h-14 animate-pulse" />)}
        </div>
      )}

      {!error && !loading && visible.length === 0 && (
        <Panel>
          <EmptyState title="No documents yet." hint="Add your first essay, CV, or transcript above." />
        </Panel>
      )}

      {!error && !loading && visible.length > 0 && (
        <div className="flex flex-col gap-2">
          {visible.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              expanded={expandedId === doc.id}
              onToggle={() => setExpandedId(expandedId === doc.id ? null : doc.id)}
              onChanged={(updated) =>
                setDocuments((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

function DocumentRow({
  doc, expanded, onToggle, onChanged,
}: {
  doc: Document
  expanded: boolean
  onToggle: () => void
  onChanged: (d: Document) => void
}) {
  const [notes, setNotes] = useState(doc.notes)
  const [tagsInput, setTagsInput] = useState(doc.tags.join(', '))
  const [versionNote, setVersionNote] = useState('')
  const [showVersionInput, setShowVersionInput] = useState(false)

  useEffect(() => {
    setNotes(doc.notes)
    setTagsInput(doc.tags.join(', '))
  }, [doc.id, doc.notes, doc.tags])

  const saveNotes = async () => {
    if (notes === doc.notes) return
    const res = await documentsApi.update(doc.id, { notes })
    if (res?.ok) onChanged(res.item)
  }

  const saveTags = async () => {
    const tags = tagsInput.split(',').map((t) => t.trim()).filter(Boolean)
    if (JSON.stringify(tags) === JSON.stringify(doc.tags)) return
    const res = await documentsApi.update(doc.id, { tags })
    if (res?.ok) onChanged(res.item)
  }

  const submitVersion = async () => {
    if (!versionNote.trim()) return
    const res = await documentsApi.bumpVersion(doc.id, versionNote.trim())
    if (res?.ok) {
      onChanged(res.item)
      setVersionNote('')
      setShowVersionInput(false)
    }
  }

  return (
    <Panel className="overflow-hidden">
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-150 hover:bg-raise2"
      >
        {expanded ? <ChevronDown size={14} className="text-low" /> : <ChevronRight size={14} className="text-low" />}
        <span className="flex-1 truncate text-[13.5px] text-hi">{doc.title}</span>
        <Pill>{doc.kind}</Pill>
        <Pill tone={STATUS_TONE[doc.status]}>{doc.status}</Pill>
        <Mono className="text-low">v{doc.version}</Mono>
        <span className="flex items-center gap-1 text-low">
          <Link2 size={12} />
          <Mono>{doc.linked_application_ids.length}</Mono>
        </span>
        <Mono className="w-[46px] text-right text-low">{timeAgo(doc.updated_at)}</Mono>
      </button>

      {expanded && (
        <div className="border-t border-hairline px-4 py-4">
          <p className="label-mono mb-2">history</p>
          {doc.history.length === 0 ? (
            <p className="mb-4 text-[12.5px] text-low">No versions bumped yet.</p>
          ) : (
            <div className="mb-4 flex flex-col gap-1.5">
              {[...doc.history].reverse().map((h) => (
                <div key={h.version} className="flex items-center gap-2.5 text-[12.5px]">
                  <Mono className="w-[36px] text-low">v{h.version}</Mono>
                  <span className="flex-1 text-mid">{h.note}</span>
                  <Mono className="text-low">{timeAgo(h.at)}</Mono>
                </div>
              ))}
            </div>
          )}

          {showVersionInput ? (
            <div className="mb-4 flex items-center gap-2">
              <input
                autoFocus
                value={versionNote}
                onChange={(e) => setVersionNote(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') void submitVersion() }}
                placeholder="What changed in this version?"
                className="flex-1 rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-[12.5px] text-hi outline-none placeholder:text-low"
              />
              <Btn kind="primary" onClick={() => void submitVersion()} disabled={!versionNote.trim()}>
                Save
              </Btn>
              <Btn onClick={() => { setShowVersionInput(false); setVersionNote('') }}>Cancel</Btn>
            </div>
          ) : (
            <Btn kind="quiet" className="mb-4" onClick={() => setShowVersionInput(true)}>
              + New version
            </Btn>
          )}

          <p className="label-mono mb-1.5">tags</p>
          <input
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            onBlur={() => void saveTags()}
            placeholder="comma, separated, tags"
            className="mb-4 w-full rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-[12.5px] text-hi outline-none placeholder:text-low"
          />

          <p className="label-mono mb-1.5">notes</p>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => void saveNotes()}
            rows={4}
            placeholder="Essay text or free-form notes…"
            className="w-full resize-none rounded-lg border border-line bg-transparent px-2.5 py-2 text-[12.5px] leading-relaxed text-mid outline-none placeholder:text-low"
          />
        </div>
      )}
    </Panel>
  )
}
