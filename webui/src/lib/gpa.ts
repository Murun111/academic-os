// GPA math — pure functions, no fetches. Standard US 4.0 letter scale.

export interface GradePoint {
  letter: string
  points: number
}

const SCALE: [number, string, number][] = [
  [93, 'A', 4.0],
  [90, 'A-', 3.7],
  [87, 'B+', 3.3],
  [83, 'B', 3.0],
  [80, 'B-', 2.7],
  [77, 'C+', 2.3],
  [73, 'C', 2.0],
  [70, 'C-', 1.7],
  [67, 'D+', 1.3],
  [63, 'D', 1.0],
  [60, 'D-', 0.7],
]

export function toLetter(pct: number): GradePoint {
  for (const [min, letter, points] of SCALE) {
    if (pct >= min) return { letter, points }
  }
  return { letter: 'F', points: 0.0 }
}

// Credit hours assumed when a course has none entered.
export const DEFAULT_CREDITS = 3

type GradedCourse = { grade: number | null; credits: number | null }

function weightedGpa(courses: GradedCourse[]): { gpa: number | null; graded: number } {
  const graded = courses.filter((c) => c.grade != null)
  if (graded.length === 0) return { gpa: null, graded: 0 }
  let points = 0
  let credits = 0
  for (const c of graded) {
    const cr = c.credits ?? DEFAULT_CREDITS
    points += toLetter(c.grade as number).points * cr
    credits += cr
  }
  return { gpa: credits > 0 ? points / credits : null, graded: graded.length }
}

// This term only — callers pass the active (non-archived) courses.
export function termGpa(courses: GradedCourse[]): { gpa: number | null; graded: number } {
  return weightedGpa(courses)
}

// Every graded course on record, archived ones included.
export function cumulativeGpa(courses: GradedCourse[]): { gpa: number | null; graded: number } {
  return weightedGpa(courses)
}

// Grade needed on the final for `targetPct` overall, given the current grade
// covers the remaining (100 - finalWeightPct)% of the course.
export function neededOnFinal(
  currentPct: number,
  finalWeightPct: number,
  targetPct: number,
): number | null {
  const w = finalWeightPct / 100
  if (w <= 0 || w > 1) return null
  return (targetPct - currentPct * (1 - w)) / w
}
