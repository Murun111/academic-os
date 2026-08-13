import { useState } from 'react'
import { type CourseSummary } from '../lib/coursesApi'
import { cumulativeGpa, DEFAULT_CREDITS, neededOnFinal, termGpa, toLetter } from '../lib/gpa'
import { Mono, Panel, PanelHead } from './ui'

export function GpaPanel({ courses, allCourses }: { courses: CourseSummary[]; allCourses: CourseSummary[] }) {
  const { gpa, graded } = termGpa(courses)
  const hasArchivedGrade = allCourses.some((c) => c.archived && c.grade != null)
  const cumulative = hasArchivedGrade ? cumulativeGpa(allCourses) : { gpa: null, graded: 0 }
  if (gpa == null && cumulative.gpa == null) return null
  const hasBlankCredits = courses.some((c) => c.grade != null && c.credits == null)
  return (
    <Panel className="mb-6">
      <PanelHead label="term gpa" />
      {gpa != null && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 pb-4">
          <span className="text-[32px] font-semibold tracking-[-0.02em] text-hi">{gpa.toFixed(2)}</span>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {courses.filter((c) => c.grade != null).map((c) => {
              const gp = toLetter(c.grade as number)
              return (
                <span key={c.id} className="text-[12.5px] text-mid">
                  {c.name} <Mono className="text-low">{gp.letter} · {gp.points.toFixed(1)}</Mono>
                </span>
              )
            })}
          </div>
        </div>
      )}
      {gpa != null && (
        <p className="px-5 pb-1.5 text-[11.5px] text-low">
          {graded} of {courses.length} courses graded, weighted by credit hours
          {hasBlankCredits ? ` (blank credits count as ${DEFAULT_CREDITS})` : ''}.
        </p>
      )}
      {cumulative.gpa != null && (
        <p className="px-5 pb-3 pt-1.5 text-[11.5px] text-low">
          cumulative {cumulative.gpa.toFixed(2)} across {cumulative.graded} courses
        </p>
      )}
    </Panel>
  )
}

export function WhatIf({ current }: { current: number }) {
  const [worth, setWorth] = useState('')
  const [target, setTarget] = useState('')
  const w = Number(worth)
  const t = Number(target)
  const valid = worth.trim() !== '' && target.trim() !== '' && !Number.isNaN(w) && !Number.isNaN(t)
  const needed = valid ? neededOnFinal(current, w, t) : null

  let verdict = ''
  if (valid && needed != null) {
    if (needed <= 0) verdict = `Already secured — even a 0 on the final keeps ${t}%.`
    else if (needed > 100) verdict = `Not reachable with the final alone (needs ${needed.toFixed(1)}%).`
    else verdict = `Need ${needed.toFixed(1)}% on the final.`
  }

  return (
    <div className="mt-3 rounded-lg border border-line bg-raise2 px-3 py-2.5">
      <p className="label-mono mb-1.5">what do i need on the final?</p>
      <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-mid">
        <span>Final is worth</span>
        <input
          value={worth}
          onChange={(e) => setWorth(e.target.value)}
          placeholder="30"
          className="w-[48px] rounded-md border border-line bg-raise2 px-1.5 py-1 text-right font-mono text-[11px] text-hi outline-none placeholder:text-low"
        />
        <span>% of the grade, and I want</span>
        <input
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="90"
          className="w-[48px] rounded-md border border-line bg-raise2 px-1.5 py-1 text-right font-mono text-[11px] text-hi outline-none placeholder:text-low"
        />
        <span>% overall.</span>
      </div>
      {verdict && <p className="mt-1.5 text-[12.5px] text-hi">{verdict}</p>}
    </div>
  )
}
