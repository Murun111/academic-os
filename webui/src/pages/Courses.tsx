import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Archive, ArchiveRestore, ChevronDown, ChevronRight, Plus } from 'lucide-react'
import {
  coursesApi, gradeTone,
  type Assignment, type AssignmentStatus, type CourseSummary,
} from '../lib/coursesApi'
import { DEFAULT_CREDITS } from '../lib/gpa'
import { Btn, EmptyState, Mono, Panel, PanelHead, Pill } from '../components/ui'
import { GpaPanel, WhatIf } from '../components/GpaPanel'
import {
  AddAssignmentForm, AddCourseForm, AssignmentRow, ConfirmDelete, EditText,
} from '../components/CourseRows'

const ASSIGNMENT_FILTERS = ['all', 'open'] as const
type AssignmentFilter = (typeof ASSIGNMENT_FILTERS)[number]

function fmtGrade(grade: number | null): string {
  return grade == null ? '—' : `${grade.toFixed(1)}%`
}

export function Courses() {
  const [courses, setCourses] = useState<CourseSummary[]>([])
  const [dueSoon, setDueSoon] = useState<Assignment[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [showAddCourse, setShowAddCourse] = useState(false)
  const [addingAssignmentFor, setAddingAssignmentFor] = useState<string | null>(null)
  const [assignmentFilter, setAssignmentFilter] = useState<AssignmentFilter>('all')
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const [searchParams] = useSearchParams()
  const deepLinked = useRef(false)

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

  // Open a course and bring its card into view — used by the due-soon strip
  // and by the ?open=<courseId> deep link other pages navigate with.
  const openCourse = useCallback((courseId: string) => {
    setExpanded(courseId)
    setAddingAssignmentFor(null)
    setAssignmentFilter('all')
    void loadAssignments(courseId)
    requestAnimationFrame(() => {
      cardRefs.current[courseId]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }, [loadAssignments])

  const toggleExpand = (courseId: string) => {
    if (expanded === courseId) {
      setExpanded(null)
      setAssignments([])
      return
    }
    openCourse(courseId)
  }

  // Deep link: expand once, after the first load has confirmed the id exists.
  const openParam = searchParams.get('open')
  useEffect(() => {
    if (deepLinked.current || loading || !openParam) return
    if (!courses.some((c) => c.id === openParam)) return
    deepLinked.current = true
    openCourse(openParam)
  }, [courses, loading, openParam, openCourse])

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

  const commitAssignmentTitle = async (a: Assignment, title: string) => {
    await coursesApi.updateAssignment(a.id, { title })
    void loadAssignments(a.course_id)
    void load()
  }

  const commitAssignmentDue = async (a: Assignment, due: string | null) => {
    await coursesApi.updateAssignment(a.id, { due })
    void loadAssignments(a.course_id)
    void load()
  }

  const deleteAssignment = async (a: Assignment) => {
    await coursesApi.deleteAssignment(a.id)
    void loadAssignments(a.course_id)
    void load()
  }

  const courseNameById = (id: string) => courses.find((c) => c.id === id)?.name

  const setArchived = async (courseId: string, archived: boolean) => {
    await coursesApi.updateCourse(courseId, { archived })
    if (archived && expanded === courseId) { setExpanded(null); setAssignments([]) }
    void load()
  }

  const commitCourseField = async (
    courseId: string,
    fields: { name?: string; term?: string; instructor?: string; credits?: number | null },
  ) => {
    await coursesApi.updateCourse(courseId, fields)
    void load()
  }

  const commitCredits = async (courseId: string, raw: string) => {
    const trimmed = raw.trim()
    const parsed = trimmed === '' ? null : Number(trimmed)
    const credits = parsed === null || Number.isNaN(parsed) ? null : parsed
    await commitCourseField(courseId, { credits })
  }

  const active = courses.filter((c) => !c.archived)
  const archived = courses.filter((c) => c.archived)
  const shownAssignments = assignmentFilter === 'open'
    ? assignments.filter((a) => a.status !== 'done')
    : assignments

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <p className="label-mono mb-1">courses · assignments · grades</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Courses</h1>
        </div>
        <span data-tour="courses-add">
          <Btn kind="primary" onClick={() => setShowAddCourse((v) => !v)}>
            <span className="flex items-center gap-1.5"><Plus size={13} /> Add course</span>
          </Btn>
        </span>
      </div>

      <GpaPanel courses={active} allCourses={courses} />

      {/* due soon strip */}
      <Panel className="mb-6">
        <PanelHead label="due soon · next 14 days" />
        <div className="flex flex-col gap-px px-2 pb-3">
          {dueSoon.length === 0 && <EmptyState title="Nothing due soon." />}
          {dueSoon.map((a) => (
            <button
              key={a.id}
              onClick={() => openCourse(a.course_id)}
              title="Open this course"
              className="flex items-center gap-3 rounded-[10px] px-3 py-2 text-left transition-colors duration-150 hover:bg-ink/4"
            >
              <span className="flex-1 truncate text-[13px] text-mid">{a.title}</span>
              <Mono className="text-low">{courseNameById(a.course_id) ?? ''}</Mono>
              <Mono className="w-[76px] text-right text-hi">{a.due}</Mono>
            </button>
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
      {!loading && active.length === 0 && !showAddCourse && (
        <EmptyState title="No courses yet." hint="Add your first course above." />
      )}

      <div className="flex flex-col gap-2">
        {active.map((c) => (
            <div
              key={c.id}
              ref={(el) => { cardRefs.current[c.id] = el }}
              className="panel overflow-hidden scroll-mt-6"
            >
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
                <ConfirmDelete onConfirm={() => void deleteCourse(c.id)} label={`Delete ${c.name}`} />
              </button>

              {expanded === c.id && (
                <div className="border-t border-hairline px-4 py-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <EditText
                      value={c.name}
                      onCommit={(v) => void commitCourseField(c.id, { name: v })}
                      placeholder="Course name"
                      ariaLabel="Course name"
                      className="w-[200px] text-[12.5px]"
                    />
                    <EditText
                      value={c.term}
                      onCommit={(v) => void commitCourseField(c.id, { term: v })}
                      placeholder="Term, e.g. Fall 2026"
                      ariaLabel="Term"
                      className="w-[140px] font-mono"
                    />
                    <EditText
                      value={c.instructor}
                      onCommit={(v) => void commitCourseField(c.id, { instructor: v })}
                      placeholder="Instructor"
                      ariaLabel="Instructor"
                      allowEmpty
                      className="w-[150px] font-mono"
                    />
                  </div>
                  <div className="mb-2 flex flex-wrap items-center gap-3 text-[12.5px] text-mid">
                    <label className="flex items-center gap-1.5">
                      credit hours
                      <input
                        defaultValue={c.credits == null ? '' : String(c.credits)}
                        onBlur={(e) => { if (e.target.value.trim() !== (c.credits == null ? '' : String(c.credits))) void commitCredits(c.id, e.target.value) }}
                        placeholder={String(DEFAULT_CREDITS)}
                        className="w-[48px] rounded-md border border-line bg-raise2 px-1.5 py-1 text-right font-mono text-[11px] text-hi outline-none placeholder:text-low"
                      />
                    </label>
                    <button
                      onClick={() => void setArchived(c.id, true)}
                      className="flex items-center gap-1.5 text-low transition-colors duration-150 hover:text-mid"
                    >
                      <Archive size={12} /> Archive course
                    </button>
                  </div>
                  {c.grade != null && <WhatIf current={c.grade} />}
                  <div className="mt-3 flex items-center gap-1.5">
                    <span className="label-mono">assignments</span>
                    {ASSIGNMENT_FILTERS.map((f) => (
                      <button
                        key={f}
                        onClick={() => setAssignmentFilter(f)}
                        className={`rounded-full border px-2 py-0.5 font-mono text-[10.5px] transition-colors duration-150 ${
                          assignmentFilter === f
                            ? 'border-line text-hi'
                            : 'border-transparent text-low hover:text-mid'
                        }`}
                      >
                        {f}
                      </button>
                    ))}
                  </div>
                  <div className="mt-1 flex flex-col gap-px">
                    {shownAssignments.length === 0 && addingAssignmentFor !== c.id && (
                      <EmptyState
                        title={assignmentFilter === 'open' && assignments.length > 0
                          ? 'Nothing open — everything here is done.'
                          : 'No assignments yet.'}
                      />
                    )}
                    {shownAssignments.map((a) => (
                      <AssignmentRow
                        key={a.id}
                        a={a}
                        onToggleStatus={(x) => void toggleAssignmentStatus(x)}
                        onTitleCommit={(x, t) => void commitAssignmentTitle(x, t)}
                        onDueCommit={(x, d) => void commitAssignmentDue(x, d)}
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

      {archived.length > 0 && (
        <div className="mt-6">
          <p className="label-mono mb-2">archived · {archived.length}</p>
          <div className="flex flex-col gap-2">
            {archived.map((c) => (
              <div key={c.id} className="panel flex items-center gap-3 px-4 py-2.5 opacity-70">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13.5px] text-mid">{c.name}</p>
                  <Mono className="text-low">{c.term}</Mono>
                </div>
                <Pill tone={gradeTone(c.grade)}>{fmtGrade(c.grade)}</Pill>
                <button
                  onClick={() => void setArchived(c.id, false)}
                  className="flex shrink-0 items-center gap-1.5 text-[12px] text-low transition-colors duration-150 hover:text-mid"
                >
                  <ArchiveRestore size={12} /> Restore
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="mt-6 border-t border-hairline pt-4 text-[12.5px] text-low">
        Connect Canvas or a school calendar link in{' '}
        <Link to="/settings" className="text-mid underline decoration-dotted hover:text-hi">Settings</Link>
        {' '}to pull courses and due dates in automatically.
      </p>
    </div>
  )
}
