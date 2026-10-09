import type { ResumeTemplate } from './types'
import { template as hsActivities } from './hs-activities'
import { template as hsFirstJob } from './hs-first-job'
import { template as undergradInternship } from './undergrad-internship'
import { template as undergradResearch } from './undergrad-research'
import { template as gapyearWork } from './gapyear-work'
import { template as gradAcademicCv } from './grad-academic-cv'
import { template as beyondProfessional } from './beyond-professional'
import { template as beyondFellowshipCv } from './beyond-fellowship-cv'

export type { ResumeTemplate }

export const RESUME_TEMPLATES: Record<string, ResumeTemplate> = {
  'hs-activities': hsActivities,
  'hs-first-job': hsFirstJob,
  'undergrad-internship': undergradInternship,
  'undergrad-research': undergradResearch,
  'gapyear-work': gapyearWork,
  'grad-academic-cv': gradAcademicCv,
  'beyond-professional': beyondProfessional,
  'beyond-fellowship-cv': beyondFellowshipCv,
}

export function templatesFor(ids: string[]): ResumeTemplate[] {
  return ids.map((id) => RESUME_TEMPLATES[id]).filter((t): t is ResumeTemplate => !!t)
}
