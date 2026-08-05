// Stage-aware UI configuration. Every difference between stages lives HERE,
// as data — components read this map and never branch on stage directly.
import type { ApplicationType } from './applicationsApi'

export type Stage = 'highschool' | 'undergrad' | 'gapyear' | 'grad' | 'beyond'

export interface StageConfig {
  label: string            // human name shown in the picker
  tagline: string          // one-liner under the picker option
  appsTitle: string        // Applications page h1
  appsSub: string          // label-mono line above the h1
  defaultType: ApplicationType
  // nav paths in display order; paths not listed keep their default order after these
  navOrder: string[]
  // requirement templates offered when creating an application, per type
  requirementTemplates: Partial<Record<ApplicationType, string[]>>
}

export const STAGES: Record<Stage, StageConfig> = {
  highschool: {
    label: 'High school',
    tagline: 'Applying to colleges and scholarships',
    appsTitle: 'Colleges',
    appsSub: 'colleges · scholarships · deadlines',
    defaultType: 'undergrad',
    navOrder: ['/', '/applications', '/study', '/courses', '/documents', '/routines'],
    requirementTemplates: {
      undergrad: ['Common App essay', 'Transcript request', 'SAT/ACT scores', 'Recommendation letters', 'FAFSA / financial aid', 'Application fee or waiver'],
      scholarship: ['Essay', 'Transcript', 'Recommendation letter', 'Proof of eligibility'],
    },
  },
  undergrad: {
    label: 'Undergrad',
    tagline: 'Courses now, internships and what comes next',
    appsTitle: 'Applications',
    appsSub: 'internships · programs · scholarships',
    defaultType: 'exchange',
    navOrder: ['/', '/courses', '/study', '/applications', '/documents', '/routines'],
    requirementTemplates: {
      exchange: ['Application form', 'Transcript', 'Statement of interest', 'Advisor approval'],
      scholarship: ['Essay', 'Transcript', 'Recommendation letter', 'Proof of eligibility'],
      grad: ['Statement of purpose', 'Transcript', 'Recommendation letters', 'GRE scores (if required)', 'CV / resume'],
    },
  },
  gapyear: {
    label: 'Gap year',
    tagline: 'Graduated — working or studying for the next step',
    appsTitle: 'Applications',
    appsSub: 'programs · scholarships · deadlines',
    defaultType: 'grad',
    navOrder: ['/', '/applications', '/study', '/documents', '/routines', '/courses'],
    requirementTemplates: {
      grad: ['Statement of purpose', 'CV / resume', 'Transcript request', 'Recommendation letters (ask early — professors forget you)', 'Entrance exam score', 'Application fee or waiver'],
      scholarship: ['Essay', 'Transcript', 'Recommendation letter', 'Proof of eligibility'],
      exchange: ['Application form', 'CV / resume', 'Statement of interest'],
    },
  },
  grad: {
    label: 'Grad school',
    tagline: 'Programs, funding, and the SOP grind',
    appsTitle: 'Programs',
    appsSub: 'programs · funding · deadlines',
    defaultType: 'grad',
    navOrder: ['/', '/applications', '/documents', '/study', '/courses', '/routines'],
    requirementTemplates: {
      grad: ['Statement of purpose', 'CV / resume', 'Transcript', '3 recommendation letters', 'GRE scores (if required)', 'Writing sample'],
      scholarship: ['Research proposal', 'CV / resume', 'Recommendation letter', 'Budget justification'],
    },
  },
  beyond: {
    label: 'Beyond',
    tagline: 'Fellowships, research, and career moves',
    appsTitle: 'Applications',
    appsSub: 'fellowships · positions · programs',
    defaultType: 'scholarship',
    navOrder: ['/', '/applications', '/documents', '/study', '/routines', '/courses'],
    requirementTemplates: {
      scholarship: ['Proposal', 'CV / resume', 'Recommendation letters', 'Budget'],
      exchange: ['Application form', 'CV / resume', 'Statement of interest'],
    },
  },
}

export const STAGE_ORDER: Stage[] = ['highschool', 'undergrad', 'gapyear', 'grad', 'beyond']

/** Config for the current stage; falls back to a neutral default pre-onboarding. */
export function stageConfig(stage: Stage | null): StageConfig {
  return stage ? STAGES[stage] : STAGES.undergrad
}
