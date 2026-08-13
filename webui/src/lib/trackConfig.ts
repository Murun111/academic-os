// Track-aware tailoring — the second axis after stage. What comes after
// undergrad (pre-med, pre-law, …) lives HERE as data, same rule as
// stageConfig: components read this map and never branch on track.
import type { ApplicationType } from './applicationsApi'

export type Track = 'premed' | 'prelaw' | 'predental' | 'gradschool' | 'unsure'

export interface StudyPlanStep {
  title: string
  daysBeforeTest: number // task lands this many days before the exam
}

export interface TrackConfig {
  label: string // human name shown on the picker card
  tagline: string // one-liner under the picker option
  exam: string | null // short exam name for the countdown pill ("MCAT")
  appsTitle?: string // overrides the stage's Applications page title
  appsSub?: string
  // overrides the stage's requirement templates for these types
  requirementTemplates?: Partial<Record<ApplicationType, string[]>>
  studyPlan?: StudyPlanStep[] // seeded into the Study planner, anchored to the exam date
  // med/dental cycles: secondary applications land between Submitted and
  // Interview — adds a "Secondaries" column to the board for these tracks
  secondaries?: boolean
}

export const TRACKS: Record<Track, TrackConfig> = {
  premed: {
    label: 'Pre-med',
    tagline: 'MCAT, then med school applications',
    exam: 'MCAT',
    secondaries: true,
    appsTitle: 'Med Schools',
    appsSub: 'med schools · scholarships · deadlines',
    requirementTemplates: {
      grad: ['MCAT score', 'AMCAS primary application', 'Personal statement', 'Letters of evaluation', 'Casper (if required)', 'Secondary essays', 'Transcript'],
    },
    studyPlan: [
      { title: 'Register for the MCAT', daysBeforeTest: 90 },
      { title: 'MCAT: start content review', daysBeforeTest: 84 },
      { title: 'MCAT: full-length practice test 1', daysBeforeTest: 42 },
      { title: 'MCAT: full-length practice test 2', daysBeforeTest: 21 },
      { title: 'MCAT: final review week begins', daysBeforeTest: 7 },
    ],
  },
  prelaw: {
    label: 'Pre-law',
    tagline: 'LSAT, then law school applications',
    exam: 'LSAT',
    // top law schools have a post-submission round too (Kira assessments,
    // interview-invite screens, "why us" addenda) — same board shape
    secondaries: true,
    appsTitle: 'Law Schools',
    appsSub: 'law schools · scholarships · deadlines',
    requirementTemplates: {
      grad: ['LSAT score', 'Personal statement', 'Letters of recommendation', 'CAS report (LSAC)', 'Resume', 'Transcript'],
    },
    studyPlan: [
      { title: 'Register for the LSAT', daysBeforeTest: 75 },
      { title: 'LSAT: start logic games practice', daysBeforeTest: 70 },
      { title: 'LSAT: timed practice test 1', daysBeforeTest: 35 },
      { title: 'LSAT: timed practice test 2', daysBeforeTest: 14 },
      { title: 'LSAT: final review week begins', daysBeforeTest: 7 },
    ],
  },
  predental: {
    label: 'Pre-dental',
    tagline: 'DAT, then dental school applications',
    exam: 'DAT',
    secondaries: true,
    appsTitle: 'Dental Schools',
    appsSub: 'dental schools · scholarships · deadlines',
    requirementTemplates: {
      grad: ['DAT score', 'AADSAS application', 'Personal statement', 'Letters of evaluation', 'Shadowing hours log', 'Transcript'],
    },
    studyPlan: [
      { title: 'Register for the DAT', daysBeforeTest: 75 },
      { title: 'DAT: start content review', daysBeforeTest: 70 },
      { title: 'DAT: full practice test 1', daysBeforeTest: 30 },
      { title: 'DAT: PAT section practice block', daysBeforeTest: 21 },
      { title: 'DAT: final review week begins', daysBeforeTest: 7 },
    ],
  },
  gradschool: {
    label: 'Grad school',
    tagline: 'GRE (if needed), then a masters or PhD',
    exam: 'GRE',
    studyPlan: [
      { title: 'Check if your programs require the GRE', daysBeforeTest: 80 },
      { title: 'Register for the GRE', daysBeforeTest: 60 },
      { title: 'GRE: practice test 1', daysBeforeTest: 30 },
      { title: 'GRE: practice test 2', daysBeforeTest: 14 },
    ],
  },
  unsure: {
    label: 'Not sure yet',
    tagline: 'Keep options open — no tailoring',
    exam: null,
  },
}

export const TRACK_ORDER: Track[] = ['premed', 'prelaw', 'predental', 'gradschool', 'unsure']

/** Stages where the "what's next" track applies. */
export function trackApplies(stage: string | null): boolean {
  return stage === 'undergrad' || stage === 'gapyear' || stage === 'beyond'
}

/** Track config, or null when unset / not applicable. */
export function trackConfig(track: Track | null): TrackConfig | null {
  return track ? TRACKS[track] : null
}

/** Days until the exam; null when no date set or already past. */
export function daysToTest(testDate: string): number | null {
  if (!testDate) return null
  const days = Math.ceil((new Date(`${testDate}T00:00:00`).getTime() - Date.now()) / 86_400_000)
  return days >= 0 ? days : null
}
