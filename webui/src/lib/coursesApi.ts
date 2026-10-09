// Courses & Assignments client — talks to the academic-os backend at
// /api/courses/*. Self-contained: no imports from ../lib/{api,types}.
// Every call degrades to a safe empty default so the page stays calm
// if the backend is unreachable.

export type AssignmentStatus = 'todo' | 'done'

export interface Course {
  id: string
  name: string
  term: string
  instructor: string
  created_at: string
  source: string // "" = manual; "canvas" | "ics" = synced
  external_id: string
  canvas_score: number | null
  credits: number | null
  archived: boolean
}

export interface Assignment {
  id: string
  course_id: string
  title: string
  due: string | null
  status: AssignmentStatus
  grade: number | null
  weight: number | null
  notes: string
  created_at: string
}

export interface CourseSummary extends Course {
  grade: number | null
  open_assignments: number
}

export interface CoursesSummary {
  courses: CourseSummary[]
  due_soon: Assignment[]
}

export interface NewCourseInput {
  name: string
  term: string
  instructor?: string
}

export interface NewAssignmentInput {
  course_id: string
  title: string
  due?: string | null
  status?: AssignmentStatus
  grade?: number | null
  weight?: number | null
  notes?: string
}

async function cget<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`/api/courses${path}`)
    if (!r.ok) return fallback
    return (await r.json()) as T
  } catch {
    return fallback
  }
}

async function cwrite<T>(
  path: string,
  method: 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T | null> {
  try {
    const r = await fetch(`/api/courses${path}`, {
      method,
      headers: body === undefined ? undefined : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!r.ok) return null
    return (await r.json()) as T
  } catch {
    return null
  }
}

export interface SyllabusItem {
  title: string
  kind: string
  due: string | null
  weight: number | null
  points?: number | null
  source_line?: string
}

export interface SyllabusPreview {
  course_name: string | null
  items: SyllabusItem[]
  grading: { category: string; weight: number }[]
  warnings: string[]
  text_chars: number
}

export interface SyllabusApplyInput {
  course_id?: string
  new_course?: { name: string; term: string }
  items: { title: string; due: string | null; weight: number | null; points?: number | null; kind: string }[]
}

export interface SyllabusApplyResult {
  ok: boolean
  course: Course
  created: number
  skipped: number
  warnings?: string[]
}

// Unlike the calm-degrading helpers above, import errors must reach the user
// (503 = no model online, 502 = unparseable output, 415/413/422 = bad file).
export type SyllabusResult<T> = { ok: true; data: T } | { ok: false; status: number; error: string }

// FastAPI sends a string for HTTPException but a list of {loc, msg} for validation errors.
function detailText(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const d = detail[0] as { msg?: unknown; loc?: unknown }
    if (typeof d?.msg === 'string') {
      const loc = Array.isArray(d.loc) ? d.loc.filter((x) => x !== 'body').join('.') : ''
      return loc ? `${loc}: ${d.msg}` : d.msg
    }
  }
  return null
}

async function syllabusPost<T>(path: string, init: RequestInit): Promise<SyllabusResult<T>> {
  try {
    const r = await fetch(`/api/courses${path}`, { method: 'POST', ...init })
    if (!r.ok) {
      let error = `Request failed (${r.status})`
      try {
        const j = await r.json()
        error = detailText(j?.detail) ?? error
      } catch {
        /* keep default */
      }
      return { ok: false, status: r.status, error }
    }
    return { ok: true, data: (await r.json()) as T }
  } catch {
    return { ok: false, status: 0, error: 'Could not reach the backend.' }
  }
}

export function previewSyllabus(input: {
  file?: File
  text?: string
  term_start?: string
  term_year?: number
}): Promise<SyllabusResult<SyllabusPreview>> {
  const fd = new FormData()
  if (input.file) fd.append('file', input.file)
  else if (input.text !== undefined) fd.append('text', input.text)
  if (input.term_start) fd.append('term_start', input.term_start)
  if (input.term_year !== undefined) fd.append('term_year', String(input.term_year))
  return syllabusPost<SyllabusPreview>('/syllabus/preview', { body: fd })
}

export function applySyllabus(input: SyllabusApplyInput): Promise<SyllabusResult<SyllabusApplyResult>> {
  return syllabusPost<SyllabusApplyResult>('/syllabus/apply', {
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export const coursesApi = {
  summary: () => cget<CoursesSummary>('/summary', { courses: [], due_soon: [] }),

  listCourses: () => cget<{ courses: Course[]; count: number }>('', { courses: [], count: 0 }),
  addCourse: (input: NewCourseInput) =>
    cwrite<{ ok: boolean; course: Course }>('', 'POST', input),
  updateCourse: (id: string, fields: Partial<NewCourseInput> & { credits?: number | null; archived?: boolean }) =>
    cwrite<{ ok: boolean; course: Course }>(`/${id}`, 'PATCH', fields),
  deleteCourse: (id: string) => cwrite<{ ok: boolean }>(`/${id}`, 'DELETE'),

  listAssignments: (params: { course_id?: string; status?: AssignmentStatus } = {}) => {
    const q = new URLSearchParams()
    if (params.course_id) q.set('course_id', params.course_id)
    if (params.status) q.set('status', params.status)
    const qs = q.toString()
    return cget<{ assignments: Assignment[]; count: number }>(
      `/assignments${qs ? `?${qs}` : ''}`,
      { assignments: [], count: 0 },
    )
  },
  addAssignment: (input: NewAssignmentInput) =>
    cwrite<{ ok: boolean; assignment: Assignment }>('/assignments', 'POST', input),
  updateAssignment: (
    id: string,
    fields: Partial<Omit<NewAssignmentInput, 'course_id'>>,
  ) => cwrite<{ ok: boolean; assignment: Assignment }>(`/assignments/${id}`, 'PATCH', fields),
  deleteAssignment: (id: string) => cwrite<{ ok: boolean }>(`/assignments/${id}`, 'DELETE'),
}

export function gradeTone(grade: number | null): string {
  if (grade == null) return ''
  if (grade >= 90) return 'running'
  if (grade >= 70) return 'pending'
  return 'failed'
}
