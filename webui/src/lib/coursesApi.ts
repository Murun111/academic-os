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

export const coursesApi = {
  summary: () => cget<CoursesSummary>('/summary', { courses: [], due_soon: [] }),

  listCourses: () => cget<{ courses: Course[]; count: number }>('', { courses: [], count: 0 }),
  addCourse: (input: NewCourseInput) =>
    cwrite<{ ok: boolean; course: Course }>('', 'POST', input),
  updateCourse: (id: string, fields: Partial<NewCourseInput>) =>
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
