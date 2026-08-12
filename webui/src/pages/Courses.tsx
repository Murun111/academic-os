import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, Plus, Trash2, X } from 'lucide-react'
import {
  coursesApi, gradeTone,
  type Assignment, type AssignmentStatus, type CourseSummary,
} from '../lib/coursesApi'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../components/ui'

function fmtGrade(grade: number | null): string {
  return grade == null ? '—' : `${grade.toFixed(1)}%`
}

function AddCourseForm({ onAdd, onCancel }: { onAdd: (name: string, term: string, instructor: string) => void; onCancel: () => void }) {
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

function AddAssignmentForm({ onAdd, onCancel }: { onAdd: (title: string, due: string) => void; onCancel: () => void }) {
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

function AssignmentRow({
  a, courseName, onToggleStatus, onGradeCommit, onDelete,
}: {
  a: Assignment
  courseName?: string
  onToggleStatus: (a: Assignment) => void
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
      <span className="flex-1 truncate text-[13px] text-mid">{a.title}</span>
      {courseName && <Mono className="hidden shrink-0 text-low sm:block">{courseName}</Mono>}
      <Mono className="w-[76px] shrink-0 text-right text-low">{a.due ?? '—'}</Mono>
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
      <button onClick={() => onDelete(a)} className="shrink-0 text-low hover:text-fail">
        <Trash2 size={13} />
      </button>
    </div>
  )
}

export function Courses() {
  const [courses, setCourses] = useState<CourseSummary[]>([])
  const [dueSoon, setDueSoon] = useState<Assignment[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [showAddCourse, setShowAddCourse] = useState(false)
  const [addingAssignmentFor, setAddingAssignmentFor] = useState<string | null>(null)

  const load = useCallback(async () => {
    const s = await coursesApi.summary()
    setCourses(s.courses)
    setDueSoon(s.due_soon)
    setLoading(false)
  }, [])

  useEffect(() => { void load() }, [load])

  const loadAssignments = useCallback(async (courseId: string) => {
    const r = await coursesApi.listAssignments({ course_id: courseId })
    setAssignments(r.assignments)
  }, [])

  const toggleExpand = (courseId: string) => {
    if (expanded === courseId) {
      setExpanded(null)
      setAssignments([])
      return
    }
    setExpanded(courseId)
    setAddingAssignmentFor(null)
    void loadAssignments(courseId)
  }

  const addCourse = async (name: string, term: string, instructor: string) => {
    await coursesApi.addCourse({ name, term, instructor })
    setShowAddCourse(false)
    void load()
  }

  const deleteCourse = async (courseId: string) => {
    await coursesApi.deleteCourse(courseId)
    if (expanded === courseId) { setExpanded(null); setAssignments([]) }
    void load()
  }

  const addAssignment = async (courseId: string, title: string, due: string) => {
    await coursesApi.addAssignment({ course_id: courseId, title, due: due || null })
    setAddingAssignmentFor(null)
    void loadAssignments(courseId)
    void load()
  }

  const toggleAssignmentStatus = async (a: Assignment) => {
    const next: AssignmentStatus = a.status === 'done' ? 'todo' : 'done'
    await coursesApi.updateAssignment(a.id, { status: next })
    void loadAssignments(a.course_id)
    void load()
  }

  const commitGrade = async (a: Assignment, grade: number | null) => {
    await coursesApi.updateAssignment(a.id, { grade })
    void loadAssignments(a.course_id)
    void load()
  }

  const deleteAssignment = async (a: Assignment) => {
    await coursesApi.deleteAssignment(a.id)
    void loadAssignments(a.course_id)
    void load()
  }

  const courseNameById = (id: string) => courses.find((c) => c.id === id)?.name

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <p className="label-mono mb-1">courses · assignments · grades</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Courses</h1>
        </div>
        <Btn kind="primary" onClick={() => setShowAddCourse((v) => !v)}>
          <span className="flex items-center gap-1.5"><Plus size={13} /> Add course</span>
        </Btn>
      </div>

      {/* due soon strip */}
      <Panel className="mb-6">
        <PanelHead label="due soon · next 14 days" />
        <div className="flex flex-col gap-px px-2 pb-3">
          {dueSoon.length === 0 && <EmptyState title="Nothing due soon." />}
          {dueSoon.map((a) => (
            <div key={a.id} className="flex items-center gap-3 rounded-[10px] px-3 py-2">
              <span className="flex-1 truncate text-[13px] text-mid">{a.title}</span>
              <Mono className="text-low">{courseNameById(a.course_id) ?? ''}</Mono>
              <Mono className="w-[76px] text-right text-hi">{a.due}</Mono>
            </div>
          ))}
        </div>
      </Panel>

      {/* course list */}
      <p className="label-mono mb-2">all courses</p>
      {showAddCourse && (
        <div className="panel mb-3">
          <AddCourseForm onAdd={(n, t, i) => void addCourse(n, t, i)} onCancel={() => setShowAddCourse(false)} />
        </div>
      )}

      {loading && <EmptyState title="Loading courses…" />}
      {!loading && courses.length === 0 && !showAddCourse && (
        <EmptyState title="No courses yet." hint="Add your first course above." />
      )}

      <div className="flex flex-col gap-2">
        {courses.map((c) => (
            <div key={c.id} className="panel overflow-hidden">
              <button
                onClick={() => toggleExpand(c.id)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-150 hover:bg-raise2"
              >
                {expanded === c.id ? <ChevronDown size={14} className="shrink-0 text-low" /> : <ChevronRight size={14} className="shrink-0 text-low" />}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] text-hi">{c.name}</p>
                  <Mono className="text-low">{c.term}{c.instructor ? ` · ${c.instructor}` : ''}</Mono>
                </div>
                <Pill tone={gradeTone(c.grade)}>{fmtGrade(c.grade)}</Pill>
                <Mono className="w-[90px] shrink-0 text-right text-low">{c.open_assignments} open</Mono>
                <button
                  onClick={(e) => { e.stopPropagation(); void deleteCourse(c.id) }}
                  className="shrink-0 text-low hover:text-fail"
                >
                  <Trash2 size={13} />
                </button>
              </button>

              {expanded === c.id && (
                <div className="border-t border-hairline px-4 py-3">
                  <div className="flex flex-col gap-px">
                    {assignments.length === 0 && addingAssignmentFor !== c.id && (
                      <EmptyState title="No assignments yet." />
                    )}
                    {assignments.map((a) => (
                      <AssignmentRow
                        key={a.id}
                        a={a}
                        onToggleStatus={(x) => void toggleAssignmentStatus(x)}
                        onGradeCommit={(x, g) => void commitGrade(x, g)}
                        onDelete={(x) => void deleteAssignment(x)}
                      />
                    ))}
                  </div>
                  {addingAssignmentFor === c.id ? (
                    <AddAssignmentForm
                      onAdd={(title, due) => void addAssignment(c.id, title, due)}
                      onCancel={() => setAddingAssignmentFor(null)}
                    />
                  ) : (
                    <Btn className="mt-2" onClick={() => setAddingAssignmentFor(c.id)}>
                      <span className="flex items-center gap-1.5"><Plus size={12} /> Add assignment</span>
                    </Btn>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

      <p className="mt-6 border-t border-hairline pt-4 text-[12.5px] text-low">
        Connect Canvas or a school calendar link in{' '}
        <Link to="/settings" className="text-mid underline decoration-dotted hover:text-hi">Settings</Link>
        {' '}to pull courses and due dates in automatically.
      </p>
    </div>
  )
}
