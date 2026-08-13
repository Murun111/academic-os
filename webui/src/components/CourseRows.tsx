import { useEffect, useState } from 'react'
import { Trash2, X } from 'lucide-react'
import { type Assignment } from '../lib/coursesApi'
import { Btn, Mono } from './ui'

// On-blur text field. Empty stays empty only where the backend allows it —
// name / term / title revert instead of sending a value that would be rejected.
export function EditText({
  value, onCommit, placeholder, ariaLabel, allowEmpty = false, className = '',
}: {
  value: string
  onCommit: (next: string) => void
  placeholder?: string
  ariaLabel?: string
  allowEmpty?: boolean
  className?: string
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  return (
    <input
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        const next = draft.trim()
        if (!next && !allowEmpty) { setDraft(value); return }
        if (next !== value) onCommit(next)
      }}
      placeholder={placeholder}
      aria-label={ariaLabel}
      className={`rounded-md border border-line bg-raise2 px-1.5 py-1 text-[11px] text-hi outline-none placeholder:text-low ${className}`}
    />
  )
}

// Two-click delete: the trash icon arms a confirm that disarms itself after 3s.
export function ConfirmDelete({ onConfirm, label }: { onConfirm: () => void; label: string }) {
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 3000)
    return () => clearTimeout(t)
  }, [armed])

  if (armed) {
    return (
      <button
        onClick={(e) => { e.stopPropagation(); setArmed(false); onConfirm() }}
        className="shrink-0 rounded-full border border-fail/30 px-2 py-0.5 font-mono text-[10.5px] text-fail transition-colors duration-150 hover:bg-fail/10"
      >
        Sure? Delete
      </button>
    )
  }
  return (
    <button
      onClick={(e) => { e.stopPropagation(); setArmed(true) }}
      aria-label={label}
      className="shrink-0 text-low transition-colors duration-150 hover:text-fail"
    >
      <Trash2 size={13} />
    </button>
  )
}

export function AddCourseForm({ onAdd, onCancel }: { onAdd: (name: string, term: string, instructor: string) => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [term, setTerm] = useState('')
  const [instructor, setInstructor] = useState('')
  return (
    <div className="flex flex-wrap items-center gap-2 px-5 pb-4">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Course name"
        className="min-w-[160px] flex-1 rounded-lg border border-line bg-raise2 px-2.5 py-1.5 text-[13px] text-hi outline-none placeholder:text-low"
      />
      <input
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        placeholder="Term, e.g. Fall 2026"
        className="w-[160px] rounded-lg border border-line bg-raise2 px-2.5 py-1.5 text-[13px] text-hi outline-none placeholder:text-low"
      />
      <input
        value={instructor}
        onChange={(e) => setInstructor(e.target.value)}
        placeholder="Instructor (optional)"
        className="w-[160px] rounded-lg border border-line bg-raise2 px-2.5 py-1.5 text-[13px] text-hi outline-none placeholder:text-low"
      />
      <Btn
        kind="primary"
        onClick={() => {
          if (!name.trim() || !term.trim()) return
          onAdd(name.trim(), term.trim(), instructor.trim())
        }}
      >
        Add
      </Btn>
      <Btn onClick={onCancel}><X size={14} /></Btn>
    </div>
  )
}

export function AddAssignmentForm({ onAdd, onCancel }: { onAdd: (title: string, due: string) => void; onCancel: () => void }) {
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')
  return (
    <div className="flex flex-wrap items-center gap-2 py-2">
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Assignment title"
        className="min-w-[160px] flex-1 rounded-lg border border-line bg-raise2 px-2.5 py-1.5 text-[13px] text-hi outline-none placeholder:text-low"
      />
      <input
        type="date"
        value={due}
        onChange={(e) => setDue(e.target.value)}
        className="rounded-lg border border-line bg-raise2 px-2.5 py-1.5 text-[13px] text-hi outline-none"
      />
      <Btn
        kind="primary"
        onClick={() => {
          if (!title.trim()) return
          onAdd(title.trim(), due)
        }}
      >
        Add
      </Btn>
      <Btn onClick={onCancel}><X size={14} /></Btn>
    </div>
  )
}

export function AssignmentRow({
  a, courseName, onToggleStatus, onTitleCommit, onDueCommit, onGradeCommit, onDelete,
}: {
  a: Assignment
  courseName?: string
  onToggleStatus: (a: Assignment) => void
  onTitleCommit: (a: Assignment, title: string) => void
  onDueCommit: (a: Assignment, due: string | null) => void
  onGradeCommit: (a: Assignment, grade: number | null) => void
  onDelete: (a: Assignment) => void
}) {
  const [gradeDraft, setGradeDraft] = useState(a.grade == null ? '' : String(a.grade))
  useEffect(() => setGradeDraft(a.grade == null ? '' : String(a.grade)), [a.grade])

  return (
    <div className="flex items-center gap-3 rounded-[10px] px-3 py-2 hover:bg-ink/4">
      <button
        onClick={() => onToggleStatus(a)}
        className={`shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10.5px] transition-colors duration-150 ${
          a.status === 'done'
            ? 'border-run/30 text-run'
            : 'border-line text-low hover:text-mid'
        }`}
      >
        {a.status}
      </button>
      <EditText
        value={a.title}
        onCommit={(title) => onTitleCommit(a, title)}
        placeholder="Assignment title"
        ariaLabel="Assignment title"
        className="min-w-0 flex-1 text-[13px]"
      />
      {courseName && <Mono className="hidden shrink-0 text-low sm:block">{courseName}</Mono>}
      <input
        type="date"
        value={a.due ?? ''}
        onChange={(e) => onDueCommit(a, e.target.value || null)}
        aria-label="Due date"
        className="w-[124px] shrink-0 rounded-md border border-line bg-raise2 px-1.5 py-1 font-mono text-[11px] text-hi outline-none"
      />
      <input
        value={gradeDraft}
        onChange={(e) => setGradeDraft(e.target.value)}
        onBlur={() => {
          const trimmed = gradeDraft.trim()
          const parsed = trimmed === '' ? null : Number(trimmed)
          const next = parsed === null || Number.isNaN(parsed) ? null : parsed
          if (next !== a.grade) onGradeCommit(a, next)
        }}
        placeholder="grade"
        className="w-[56px] shrink-0 rounded-md border border-line bg-raise2 px-1.5 py-1 text-right font-mono text-[11px] text-hi outline-none placeholder:text-low"
      />
      <ConfirmDelete onConfirm={() => onDelete(a)} label={`Delete ${a.title}`} />
    </div>
  )
}
