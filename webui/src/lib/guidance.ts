// First-gen guidance layer: plain-language glossary for admissions/financial-aid
// jargon. Data only — components read this map, never branch on term keys.
import type { Stage } from './stageConfig'

export interface GuidanceEntry {
  title: string
  body: string
  stages: Stage[]
}

export const GUIDANCE: Record<string, GuidanceEntry> = {
  lor: {
    title: 'Letters of recommendation (LOR)',
    body: "A recommendation letter is written by a teacher, professor, employer, or supervisor who can speak to your work and character. Give your recommender at least a few weeks' notice, and share your resume and what you're applying for so the letter is specific rather than generic. Most portals let you waive your right to read the letter — waiving is generally seen as a sign of trust by admissions committees.",
    stages: ['highschool', 'undergrad', 'grad', 'gapyear', 'beyond'],
  },
  sop: {
    title: 'Statement of purpose (SOP)',
    body: "A statement of purpose is a graduate-application essay explaining your research interests, relevant background, and why a specific program fits your goals. Unlike a personal statement, it stays focused on academic and professional fit rather than personal narrative. Tailor it to each program — naming faculty or labs you'd want to work with is a common expectation.",
    stages: ['grad', 'gapyear', 'beyond'],
  },
  'personal-statement': {
    title: 'Personal statement',
    body: "A personal statement is a narrative essay about who you are — your background, challenges, and motivations — rather than your academic plans. Undergraduate and scholarship applications weight it heavily because it's often the only place your voice comes through directly. Write several drafts and get at least one outside read before submitting.",
    stages: ['highschool', 'undergrad', 'beyond'],
  },
  fafsa: {
    title: 'FAFSA',
    body: 'The FAFSA (Free Application for Federal Student Aid) is the US federal form that determines eligibility for federal grants, loans, and work-study. US-centric: only US citizens and eligible noncitizens can file it. File it as early as the application window allows, since some state and institutional aid is awarded first-come, first-served.',
    stages: ['highschool', 'undergrad'],
  },
  'css-profile': {
    title: 'CSS Profile',
    body: "The CSS Profile is a financial aid application used by several hundred, mostly private, US colleges, in addition to (not instead of) the FAFSA. US-centric: it's run by the College Board and often carries a per-school fee, though fee waivers exist for low-income applicants. Check each school's own list of required aid forms — not all schools that use it list it clearly.",
    stages: ['highschool', 'undergrad'],
  },
  'fee-waiver': {
    title: 'Fee waiver',
    body: "A fee waiver removes the application (or CSS Profile / testing) fee for applicants who demonstrate financial need. Most platforms — Common App, individual college portals — have a built-in waiver request, usually self-certified or confirmed by a counselor. Ask your school counselor if you're unsure whether you qualify; the fee itself is often $50-$90 per school when not waived.",
    stages: ['highschool', 'undergrad'],
  },
  'rolling-admission': {
    title: 'Rolling admission',
    body: "Rolling admission means a school reviews and decides on applications as they arrive, rather than in one batch after a fixed deadline. Applying earlier generally improves your odds, since more spots and more aid money are still available. There's usually still a final deadline even though decisions come out on a rolling basis.",
    stages: ['highschool', 'undergrad'],
  },
  'early-decision': {
    title: 'Early decision (ED)',
    body: "Early decision is a binding application plan — if admitted, you're committed to attend and must withdraw other applications. It typically has an earlier deadline and earlier notification than regular decision, and can carry a small admissions-rate edge. Only apply ED if the school is truly your first choice and you're confident about affording it before seeing the aid offer.",
    stages: ['highschool'],
  },
  'early-action': {
    title: 'Early action (EA)',
    body: "Early action is a non-binding early application plan — you get an earlier decision without being committed to enroll. It's separate from early decision, which is binding; some schools offer both, or a restrictive/single-choice EA that limits your other early applications. EA is generally lower-risk than ED since you keep the option to compare offers.",
    stages: ['highschool'],
  },
  'demonstrated-interest': {
    title: 'Demonstrated interest',
    body: "Demonstrated interest is a school's read on how likely you are to enroll if admitted, judged by things like campus visits, opening admissions emails, or attending virtual info sessions. Not every school tracks or weighs it — check whether a school lists it as a factor before spending time on it. When it matters, a few real actions (attending a webinar, emailing an admissions rep a genuine question) count more than volume.",
    stages: ['highschool'],
  },
  transcript: {
    title: 'Transcript',
    body: "A transcript is the official record of your courses and grades, issued directly by your school's registrar or counseling office. Most applications require an official transcript sent directly by the institution — a copy you upload yourself usually isn't accepted as final. Request transcripts well before deadlines, since school offices can take time to process them, especially during peak season.",
    stages: ['highschool', 'undergrad', 'grad', 'gapyear', 'beyond'],
  },
  'weighted-gpa': {
    title: 'Weighted GPA',
    body: 'A weighted GPA gives extra points for harder courses (AP, IB, honors), so it runs higher than an unweighted GPA on the same transcript. US-centric: this is a US high school convention. Colleges usually recalculate GPA using their own formula, so the weighted number on your transcript is not always what shows up in their evaluation.',
    stages: ['highschool'],
  },
  'common-app': {
    title: 'Common App',
    body: "The Common App is a shared US undergraduate application platform accepted by most, but not all, four-year colleges, letting you fill in core information once and reuse it across schools. US-centric: some public university systems and many international schools use their own separate portals instead. Each school can still add its own supplemental essays and requirements on top of the shared form.",
    stages: ['highschool'],
  },
  gre: {
    title: 'GRE',
    body: "The GRE (Graduate Record Examination) is a standardized test some graduate programs use in admissions, though many US programs have dropped or made it optional in recent years. Requirements vary a lot by field — STEM programs are more likely to still require or recommend it than humanities programs. Check each program's current policy directly, since it changes often and generic advice about GRE requirements goes stale fast.",
    stages: ['grad', 'gapyear', 'beyond'],
  },
  'toefl-ielts': {
    title: 'TOEFL / IELTS',
    body: "TOEFL and IELTS are English proficiency tests required by many US and English-medium programs for applicants whose education wasn't primarily in English. Requirements and accepted minimum scores vary by program, and some schools waive the requirement if you studied in English for a certain number of years. Register early — test dates and score-report processing can take weeks, and scores typically expire after two years.",
    stages: ['undergrad', 'grad', 'gapyear', 'beyond'],
  },
  assistantship: {
    title: 'Assistantship',
    body: 'An assistantship is a graduate funding package tied to work — usually a teaching assistantship (TA) or research assistantship (RA) — that typically covers tuition plus a stipend in exchange for a set number of work hours per week. It is distinct from a fellowship, which usually has no work requirement attached. Ask specifically whether an offer includes full tuition remission, since a "funded" offer can still leave a balance.',
    stages: ['grad', 'gapyear'],
  },
  stipend: {
    title: 'Stipend',
    body: "A stipend is the living-expense payment that comes with an assistantship or fellowship, paid on a regular schedule — often monthly — rather than as a lump sum. It's meant to cover cost of living, not to be extra spending money, so weigh it against the actual cost of living where the program is located. Ask whether it's taxable, since treatment varies and affects what you actually take home.",
    stages: ['grad', 'gapyear', 'beyond'],
  },
  waitlist: {
    title: 'Waitlist',
    body: "Being waitlisted means you weren't offered admission outright but could still be admitted later if space opens up, often after the school's initial deposit deadline passes. Schools generally don't rank waitlists publicly, and movement off a waitlist is unpredictable from year to year. If you want to stay in the running, follow the school's specific instructions for confirming waitlist interest — a generic 'letter of continued interest' isn't always welcome or required.",
    stages: ['highschool', 'undergrad', 'grad', 'gapyear'],
  },
  deferral: {
    title: 'Deferral',
    body: 'A deferral means your application, usually from an early decision or early action round, is pushed into the regular decision pool for reconsideration rather than accepted or denied outright. It is not a rejection, but the regular pool is generally described as more competitive than the early round. Some schools invite a short update letter after a deferral; check whether yours does before sending one unsolicited.',
    stages: ['highschool', 'grad', 'gapyear'],
  },
  'need-blind': {
    title: 'Need-blind admission',
    body: "Need-blind admission means your ability to pay isn't considered when deciding whether to admit you — a small number of well-resourced schools apply this, and fewer still extend it to international applicants. Need-blind does not guarantee your financial need will be fully met once you're admitted; that's a separate policy, sometimes called 'meets full need.' Check both policies separately for any school where cost is a deciding factor.",
    stages: ['highschool', 'undergrad'],
  },
  'pell-grant': {
    title: 'Pell Grant',
    body: "The Pell Grant is a US federal grant for undergraduates with significant financial need — unlike a loan, it doesn't have to be repaid. US-centric: eligibility is determined by your FAFSA data, primarily your family's financial situation and your enrollment status. It has a lifetime eligibility limit measured in semesters/terms, not just a per-year cap, so it doesn't renew indefinitely.",
    stages: ['highschool', 'undergrad'],
  },
  'work-study': {
    title: 'Work-study',
    body: "Federal work-study is a US need-based program that subsidizes part-time campus or approved off-campus jobs for students, listed as part of a financial aid offer. US-centric: being awarded work-study doesn't guarantee a job — you usually still have to find and apply for a work-study-eligible position yourself. It also doesn't pay automatically toward tuition; it's a paycheck for hours worked, so it helps most with ongoing expenses, not the upfront bill.",
    stages: ['highschool', 'undergrad', 'grad', 'gapyear'],
  },
}

/** Entries relevant to a stage, or all entries when stage is null (pre-onboarding). */
export function guidanceForStage(stage: Stage | null): [string, GuidanceEntry][] {
  return Object.entries(GUIDANCE)
    .filter(([, entry]) => stage === null || entry.stages.includes(stage))
    .sort((a, b) => a[1].title.localeCompare(b[1].title))
}
