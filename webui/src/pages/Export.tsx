// Counselor / parent export — a print-ready one-pager. The browser's
// "Save as PDF" does the heavy lifting; @media print CSS hides the app chrome.
import { useEffect, useState } from 'react'
import { Printer } from 'lucide-react'
import { Btn, Mono } from '../components/ui'
import { applicationsApi, requirementsProgress, type Application, type ApplicationCosts } from '../lib/applicationsApi'
import { coursesApi, type CourseSummary } from '../lib/coursesApi'
import { useOs } from '../lib/store'

const STATUS_TEXT: Record<string, string> = {
  researching: 'Researching', preparing: 'Preparing', submitted: 'Submitted',
  interview: 'Interview', decision: 'Decision',
}

function usd(n: number): string {
  return `$${Math.round(n).toLocaleString()}`
}

export function Export() {
  const userName = useOs((s) => s.userName)
  const [apps, setApps] = useState<Application[]>([])
  const [costs, setCosts] = useState<ApplicationCosts | null>(null)
  const [courses, setCourses] = useState<CourseSummary[]>([])

  useEffect(() => {
    void applicationsApi.list().then(setApps)
    void applicationsApi.costs().then(setCosts)
    void coursesApi.listCourses().then((r) => setCourses(r.courses as CourseSummary[]))
  }, [])

  const today = new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
  const sorted = [...apps].sort((a, b) => (a.deadline ?? '9999') < (b.deadline ?? '9999') ? -1 : 1)

  return (
    <div className="print-report mx-auto max-w-[820px]">
      <div className="mb-5 flex items-end justify-between print:hidden">
        <div>
          <p className="label-mono mb-1">print or save as pdf — share with a counselor or parent</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Progress Report</h1>
        </div>
        <Btn kind="primary" onClick={() => window.print()}>
          <span className="flex items-center gap-1.5"><Printer size={13} /> Print / Save as PDF</span>
        </Btn>
      </div>

      {/* report header */}
      <div className="mb-6 border-b border-line pb-3">
        <h2 className="text-[20px] font-semibold tracking-[-0.01em]">
          {userName ? `${userName} — ` : ''}Application Progress
        </h2>
        <Mono className="text-low">prepared {today} · Academic OS</Mono>
      </div>

      {/* 1. college list */}
      <section className="mb-6">
        <p className="label-mono mb-2">applications + scholarships</p>
        {sorted.length === 0 && <p className="text-[13px] text-mid">No applications yet.</p>}
        {sorted.length > 0 && (
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left">
                <th className="py-1.5 pr-3 font-medium text-low">Name</th>
                <th className="py-1.5 pr-3 font-medium text-low">Type</th>
                <th className="py-1.5 pr-3 font-medium text-low">Deadline</th>
                <th className="py-1.5 pr-3 font-medium text-low">Status</th>
                <th className="py-1.5 pr-3 font-medium text-low">Checklist</th>
                <th className="py-1.5 font-medium text-low">Result</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((a) => (
                <tr key={a.id} className="border-b border-hairline align-top">
                  <td className="py-1.5 pr-3 text-hi">{a.name}{a.org ? <span className="text-low"> · {a.org}</span> : ''}</td>
                  <td className="py-1.5 pr-3 text-mid">{a.type}</td>
                  <td className="py-1.5 pr-3 font-mono text-[11.5px] text-mid">{a.deadline ?? '—'}</td>
                  <td className="py-1.5 pr-3 text-mid">{STATUS_TEXT[a.status]}</td>
                  <td className="py-1.5 pr-3 font-mono text-[11.5px] text-mid">
                    {a.requirements.length > 0 ? requirementsProgress(a.requirements) : '—'}
                  </td>
                  <td className="py-1.5 text-mid">{a.decision_result || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* 2. money summary */}
      {costs && (
        <section className="mb-6">
          <p className="label-mono mb-2">money</p>
          <div className="flex flex-wrap gap-x-8 gap-y-1 text-[13px]">
            <span className="text-mid">Application fees still due: <span className="text-hi">{usd(costs.fees_due)}</span></span>
            <span className="text-mid">Fees waived: <span className="text-hi">{usd(costs.fees_waived)}</span></span>
            <span className="text-mid">Scholarships applied for: <span className="text-hi">{usd(costs.potential_awards)}</span></span>
            <span className="text-mid">Awards won: <span className="text-hi">{usd(costs.won_awards)}</span></span>
          </div>
        </section>
      )}

      {/* 3. outstanding checklist items */}
      <section className="mb-6">
        <p className="label-mono mb-2">what's left to do</p>
        {sorted.filter((a) => a.requirements.some((r) => !r.done)).length === 0 && (
          <p className="text-[13px] text-mid">Every checklist item is done.</p>
        )}
        {sorted.filter((a) => a.requirements.some((r) => !r.done)).map((a) => (
          <div key={a.id} className="mb-2">
            <p className="text-[13px] text-hi">{a.name}</p>
            <p className="text-[12.5px] text-mid">
              {a.requirements.filter((r) => !r.done).map((r) => r.label).join(' · ')}
            </p>
          </div>
        ))}
      </section>

      {/* 4. grades snapshot */}
      {courses.length > 0 && (
        <section className="mb-6">
          <p className="label-mono mb-2">current courses + grades</p>
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left">
                <th className="py-1.5 pr-3 font-medium text-low">Course</th>
                <th className="py-1.5 pr-3 font-medium text-low">Term</th>
                <th className="py-1.5 font-medium text-low">Grade</th>
              </tr>
            </thead>
            <tbody>
              {courses.map((c) => (
                <tr key={c.id} className="border-b border-hairline">
                  <td className="py-1.5 pr-3 text-hi">{c.name}</td>
                  <td className="py-1.5 pr-3 text-mid">{c.term}</td>
                  <td className="py-1.5 font-mono text-[11.5px] text-mid">
                    {c.grade != null ? `${c.grade.toFixed(1)}%` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <Mono className="text-low">Generated locally by Academic OS — no data left this computer.</Mono>
    </div>
  )
}
