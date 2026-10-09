// Learning module client — talks to /api/learning/* on the Academic OS
// backend (same-origin, vite proxies /api). Unlike studyApi (which degrades
// to empty defaults), every call here throws LearningApiError on failure so
// the UI can branch on `.status` (404 missing, 422 invalid, 503 LLM down).
// studyApi does not use mock mode, so neither does this file.

const BASE = '/api/learning'

/* --------------------------------- types --------------------------------- */

export type SrsRating = 'again' | 'hard' | 'good' | 'easy'
export const SRS_RATINGS: readonly SrsRating[] = ['again', 'hard', 'good', 'easy']

export type QuestionType = 'multiple_choice' | 'true_false' | 'short_answer'
export type MasteryStatus = 'needs_review' | 'developing' | 'proficient' | 'mastered'
export const MASTERY_STATUSES: readonly MasteryStatus[] = [
  'needs_review',
  'developing',
  'proficient',
  'mastered',
]
export type Difficulty = 'easy' | 'medium' | 'hard'

export interface SrsState {
  ease_factor: number
  repetition: number
  interval_days: number
  next_review: string
  last_reviewed: string
  lapses: number
}

export interface Card {
  id: string
  front: string
  back: string
  hint: string
  explanation: string
  tags: string[]
  srs: SrsState
  created_at: string
  // only present on GET /due-cards
  deck_id?: string
  deck_title?: string
  course_name?: string
}

export interface Deck {
  id: string
  title: string
  description: string
  course_id: string | null
  course_name: string | null
  tags: string[]
  cards: Card[]
  total_cards: number
  due_cards: number
  created_at: string
  updated_at: string
}

export interface Question {
  id: string
  prompt: string
  type: QuestionType
  options: string[]
  correct_answer: string
  explanation: string
  concept: string
}

export interface QuestionResult {
  question_id: string
  prompt: string
  user_answer: unknown
  correct_answer: string
  is_correct: boolean
  explanation: string
  concept: string
}

export interface QuizAttempt {
  attempt_id: string
  score: number
  correct_count: number
  total_questions: number
  time_spent_secs: number
  breakdown: QuestionResult[]
  completed_at: string
}

export interface Quiz {
  id: string
  title: string
  topic: string
  course_id: string | null
  course_name: string | null
  time_limit_mins: number
  questions: Question[]
  attempts: QuizAttempt[]
  best_score: number | null
  created_at: string
  updated_at: string
}

export interface MasteryTopic {
  id: string
  name: string
  course_id: string | null
  course_name: string
  status: MasteryStatus
  attempts_count: number
  correct_count: number
  last_practiced: string
}

export interface MasteryMatrix {
  topics: MasteryTopic[]
  overall_mastery: number
}

export interface StudyGuide {
  id: string
  title: string
  topic: string
  content: string
  course_id: string | null
  course_name: string | null
  key_takeaways: string[]
  formulas: string[]
  tags: string[]
  created_at: string
  updated_at: string
}

export interface FocusSession {
  id: string
  duration_minutes: number
  topic: string
  goal: string
  reflections: string
  course_id: string | null
  course_name: string | null
  completed_at: string
}

export interface LearningOverview {
  cards_due_today: number
  total_cards: number
  total_decks: number
  total_quizzes: number
  quiz_attempts_count: number
  avg_quiz_score: number
  overall_mastery: number
  total_topics: number
  total_focus_minutes: number
  recent_focus_sessions: FocusSession[]
}

/* ------------------------------ request types ----------------------------- */

export interface CardCreate {
  front: string
  back: string
  hint?: string
  explanation?: string
  tags?: string[]
}

export interface DeckCreate {
  title: string
  description?: string
  course_id?: string | null
  course_name?: string | null
  tags?: string[]
  cards?: CardCreate[]
}

export interface DeckUpdate {
  title?: string | null
  description?: string | null
  course_id?: string | null
  course_name?: string | null
  tags?: string[] | null
}

export interface QuestionCreate {
  prompt: string
  type: QuestionType
  options: string[]
  correct_answer: string
  explanation: string
  concept?: string
}

export interface QuizCreate {
  title: string
  topic: string
  course_id?: string | null
  course_name?: string | null
  time_limit_mins?: number
  questions: QuestionCreate[]
}

export interface QuizSubmit {
  answers: Record<string, unknown>
  time_spent_secs?: number
}

export interface TopicCreate {
  name: string
  course_id?: string | null
  course_name?: string | null
  status?: MasteryStatus
}

export interface GuideCreate {
  title: string
  topic: string
  content: string
  course_id?: string | null
  course_name?: string | null
  key_takeaways?: string[]
  formulas?: string[]
  tags?: string[]
}

export interface FocusSessionCreate {
  duration_minutes: number
  topic: string
  goal?: string
  reflections?: string
  course_id?: string | null
  course_name?: string | null
}

export interface GenerateFlashcardsRequest {
  topic: string
  context_text?: string
  count?: number
  difficulty?: Difficulty
  save_to_deck?: boolean
  deck_title?: string
  course_id?: string | null
  course_name?: string | null
}

export interface GeneratedCard {
  front: string
  back: string
  hint: string
  explanation: string
  tags: string[]
}

export interface GenerateFlashcardsResponse {
  cards: GeneratedCard[]
  deck: Deck | null
}

export interface GenerateQuizRequest {
  topic: string
  context_text?: string
  num_questions?: number
  difficulty?: Difficulty
  save_as_quiz?: boolean
  quiz_title?: string
  course_id?: string | null
  course_name?: string | null
}

export type GeneratedQuestion = Omit<Question, 'id'>

export interface GenerateQuizResponse {
  questions: GeneratedQuestion[]
  quiz: Quiz | null
}

export interface GenerateGuideRequest {
  topic: string
  context_text?: string
  save_as_guide?: boolean
  course_id?: string | null
  course_name?: string | null
}

export interface GuideData {
  title: string
  summary_markdown: string
  key_takeaways: string[]
  formulas: string[]
  tags: string[]
}

export interface GenerateGuideResponse {
  guide_data: GuideData
  guide: StudyGuide | null
}

export interface TutorMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface TutorRequest {
  topic: string
  messages: TutorMessage[]
  context?: string
}

export interface TutorResponse {
  reply: string
}

export interface OkResponse {
  ok: boolean
}

/* --------------------------------- errors --------------------------------- */

/** Thrown for any non-2xx response or network failure. status 0 = network. */
export class LearningApiError extends Error {
  readonly status: number
  readonly detail: string
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`)
    this.name = 'LearningApiError'
    this.status = status
    this.detail = detail
  }
  get isUnavailable(): boolean {
    return this.status === 503
  }
  get isNotFound(): boolean {
    return this.status === 404
  }
}

export function isLearningApiError(e: unknown): e is LearningApiError {
  return e instanceof LearningApiError
}

/** True when the error means the backend/LLM is down (503) or unreachable. */
export function isUnavailable(e: unknown): boolean {
  return e instanceof LearningApiError && (e.status === 503 || e.status === 0)
}

/* --------------------------------- helpers -------------------------------- */

async function errorDetail(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: unknown }
    if (typeof j.detail === 'string') return j.detail
    if (j.detail !== undefined) return JSON.stringify(j.detail)
  } catch {
    /* body not JSON */
  }
  return r.statusText || `HTTP ${r.status}`
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let r: Response
  try {
    r = await fetch(`${BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (e) {
    throw new LearningApiError(0, e instanceof Error ? e.message : 'Network error')
  }
  if (!r.ok) throw new LearningApiError(r.status, await errorDetail(r))
  return (await r.json()) as T
}

function qs(params: Record<string, string | undefined>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ''
}

const enc = encodeURIComponent

/* ------------------------------ deck import ------------------------------ */

export type ImportFormat = 'auto' | 'apkg' | 'quizlet' | 'delimited'

export interface ImportInput {
  file?: File
  text?: string
  format?: ImportFormat
  term_sep?: string
  row_sep?: string
}

export interface ImportCard {
  front: string
  back: string
  tags: string[]
}

export interface ImportPreview {
  cards: ImportCard[]
  total: number
  warnings: string[]
  skipped: number
}

export interface ImportDeckInput extends ImportInput {
  deck_title: string
  course_id?: string
  course_name?: string
}

export interface ImportDeckResult {
  deck: Deck
  imported: number
  warnings: string[]
  skipped: number
}

function importForm(input: ImportInput & Partial<ImportDeckInput>): FormData {
  const f = new FormData()
  if (input.file) f.append('file', input.file)
  if (input.text) f.append('text', input.text)
  f.append('format', input.format ?? 'auto')
  if (input.term_sep) f.append('term_sep', input.term_sep)
  if (input.row_sep) f.append('row_sep', input.row_sep)
  if (input.deck_title !== undefined) f.append('deck_title', input.deck_title)
  if (input.course_id) f.append('course_id', input.course_id)
  if (input.course_name) f.append('course_name', input.course_name)
  return f
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  let r: Response
  try {
    r = await fetch(`${BASE}${path}`, { method: 'POST', body: form })
  } catch (e) {
    throw new LearningApiError(0, e instanceof Error ? e.message : 'Network error')
  }
  if (!r.ok) throw new LearningApiError(r.status, await errorDetail(r))
  return (await r.json()) as T
}

/* ---------------------------------- client -------------------------------- */

export const learning = {
  overview: () => request<LearningOverview>('GET', '/overview'),

  // decks + cards
  decks: (courseId?: string) => request<Deck[]>('GET', `/decks${qs({ course_id: courseId })}`),
  createDeck: (deck: DeckCreate) => request<Deck>('POST', '/decks', deck),
  deck: (id: string) => request<Deck>('GET', `/decks/${enc(id)}`),
  updateDeck: (id: string, patch: DeckUpdate) =>
    request<Deck>('PATCH', `/decks/${enc(id)}`, patch),
  deleteDeck: (id: string) => request<OkResponse>('DELETE', `/decks/${enc(id)}`),
  addCard: (deckId: string, card: CardCreate) =>
    request<Card>('POST', `/decks/${enc(deckId)}/cards`, card),
  deleteCard: (deckId: string, cardId: string) =>
    request<OkResponse>('DELETE', `/decks/${enc(deckId)}/cards/${enc(cardId)}`),
  dueCards: (deckId?: string) => request<Card[]>('GET', `/due-cards${qs({ deck_id: deckId })}`),
  reviewCard: (deckId: string, cardId: string, rating: SrsRating) =>
    request<Card>('POST', `/decks/${enc(deckId)}/cards/${enc(cardId)}/review`, { rating }),

  // import (multipart; preview saves nothing)
  importPreview: (input: ImportInput) =>
    postForm<ImportPreview>('/import/preview', importForm(input)),
  importDeck: (input: ImportDeckInput) =>
    postForm<ImportDeckResult>('/import', importForm(input)),

  // quizzes
  quizzes: (courseId?: string) =>
    request<Quiz[]>('GET', `/quizzes${qs({ course_id: courseId })}`),
  createQuiz: (quiz: QuizCreate) => request<Quiz>('POST', '/quizzes', quiz),
  quiz: (id: string) => request<Quiz>('GET', `/quizzes/${enc(id)}`),
  deleteQuiz: (id: string) => request<OkResponse>('DELETE', `/quizzes/${enc(id)}`),
  submitQuiz: (id: string, submission: QuizSubmit) =>
    request<QuizAttempt>('POST', `/quizzes/${enc(id)}/submit`, submission),

  // mastery
  mastery: () => request<MasteryMatrix>('GET', '/mastery'),
  addTopic: (topic: TopicCreate) => request<MasteryTopic>('POST', '/mastery/topics', topic),
  setTopicStatus: (id: string, status: MasteryStatus) =>
    request<MasteryTopic>('PATCH', `/mastery/topics/${enc(id)}`, { status }),

  // guides
  guides: (courseId?: string) =>
    request<StudyGuide[]>('GET', `/guides${qs({ course_id: courseId })}`),
  createGuide: (guide: GuideCreate) => request<StudyGuide>('POST', '/guides', guide),
  guide: (id: string) => request<StudyGuide>('GET', `/guides/${enc(id)}`),
  deleteGuide: (id: string) => request<OkResponse>('DELETE', `/guides/${enc(id)}`),

  // focus
  focusSessions: () => request<FocusSession[]>('GET', '/focus'),
  logFocus: (session: FocusSessionCreate) => request<FocusSession>('POST', '/focus', session),

  // AI
  generateFlashcards: (req: GenerateFlashcardsRequest) =>
    request<GenerateFlashcardsResponse>('POST', '/generate/flashcards', req),
  generateQuiz: (req: GenerateQuizRequest) =>
    request<GenerateQuizResponse>('POST', '/generate/quiz', req),
  generateGuide: (req: GenerateGuideRequest) =>
    request<GenerateGuideResponse>('POST', '/generate/guide', req),
  tutor: (req: TutorRequest) => request<TutorResponse>('POST', '/tutor', req),
}
