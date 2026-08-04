import type {
  AgentInfo, AgentStats, Approval, ChatThread, Health, MemoryEntry,
  MemoryStats, OsEvent, Run,
} from './types'

// A believable slice of the living system, used when VITE_API_MODE !== 'real'.

const now = Date.now()
const iso = (msAgo: number) => new Date(now - msAgo).toISOString()
let seq = 0
export const nextId = (p: string) => `${p}_${(++seq).toString(36)}${(now % 1e6).toString(36)}`

export const agents: AgentInfo[] = [
  {
    name: 'chief-of-staff', description: 'Runs the morning briefing, delegates work, watches the queue.',
    state: 'running', autonomy: 'gated', currentTask: 'compiling evening digest from today’s runs',
    lastRun: iso(4 * 60_000), runsToday: 6, tools: ['vault', 'calendar', 'inbox'],
  },
  {
    name: 'kb-librarian', description: 'Ingests drops in raw/, compiles concepts into the wiki.',
    state: 'running', autonomy: 'auto', currentTask: 'compiling "spaced repetition" from 3 sources',
    lastRun: iso(11 * 60_000), runsToday: 9, tools: ['vault', 'kb'],
  },
  {
    name: 'translator', description: 'En↔Mn translation with translation-memory few-shot.',
    state: 'idle', autonomy: 'auto', lastRun: iso(48 * 60_000), runsToday: 14, tools: ['vault', 'tm'],
  },
  {
    name: 'inbox-triage', description: 'Sorts inbox drops, drafts replies for approval.',
    state: 'idle', autonomy: 'gated', lastRun: iso(2.2 * 3_600_000), runsToday: 3, tools: ['inbox', 'vault'],
  },
  {
    name: 'money-clerk', description: 'Categorizes transactions, flags anomalies against budget.',
    state: 'idle', autonomy: 'gated', lastRun: iso(5.1 * 3_600_000), runsToday: 2, tools: ['money'],
  },
  {
    name: 'research-scout', description: 'Overnight web research into vault notes, cited.',
    state: 'failed', autonomy: 'manual', lastRun: iso(7.4 * 3_600_000), runsToday: 1, tools: ['browser', 'vault'],
  },
]

export const approvals: Approval[] = [
  {
    id: nextId('ap'), agent: 'inbox-triage', tool: 'inbox.send_reply', risk: 'high',
    args: { to: 'landlord@example.com', subject: 'Re: lease renewal', body_preview: 'Happy to renew at the current rate through…' },
    reason: 'Outbound email is always gated.', requestedAt: iso(9 * 60_000),
  },
  {
    id: nextId('ap'), agent: 'money-clerk', tool: 'money.recategorize', risk: 'low',
    args: { txn: 'APPLE.COM/BILL 9.99', from: 'shopping', to: 'subscriptions' },
    reason: 'Bulk change touches 11 past transactions.', requestedAt: iso(31 * 60_000),
  },
  {
    id: nextId('ap'), agent: 'chief-of-staff', tool: 'calendar.create_event', risk: 'medium',
    args: { title: 'Deep work: translator eval', when: 'tomorrow 09:00–11:00', calendar: 'personal' },
    reason: 'Writes to iCloud CalDAV.', requestedAt: iso(52 * 60_000),
  },
]

export const runs: Run[] = [
  {
    id: nextId('run'), agent: 'kb-librarian', goal: 'Compile concept notes from 3 PDFs dropped in raw/',
    status: 'running', startedAt: iso(11 * 60_000), tokens: 18_240,
    steps: [
      { t: iso(11 * 60_000), kind: 'tool', label: 'kb_collect', durMs: 45_000, detail: 'raw/drop → 3 files converted', ok: true },
      { t: iso(9 * 60_000), kind: 'tool', label: 'kb_ingest', durMs: 160_000, detail: '14 images localized', ok: true },
      { t: iso(6 * 60_000), kind: 'llm', label: 'concept extraction', durMs: 210_000, detail: 'qwen3:14b · 6 candidate concepts', ok: true },
      { t: iso(2 * 60_000), kind: 'critic', label: 'verify vs sources', durMs: 95_000, detail: 'checking citations for "spaced repetition"', ok: true },
    ],
  },
  {
    id: nextId('run'), agent: 'translator', goal: 'Translate weekly letter to Mongolian',
    status: 'completed', startedAt: iso(49 * 60_000), elapsedMs: 74_000, tokens: 9_310,
    steps: [
      { t: iso(49 * 60_000), kind: 'tool', label: 'tm.retrieve', durMs: 4_000, detail: '8 few-shot pairs, avg sim 0.81', ok: true },
      { t: iso(48 * 60_000), kind: 'llm', label: 'translate', durMs: 38_000, detail: 'qwen3:14b + grammar KB', ok: true },
      { t: iso(47 * 60_000), kind: 'critic', label: 'back-translation chrF', durMs: 21_000, detail: '0.64 → confident', ok: true },
      { t: iso(47 * 60_000), kind: 'result', label: 'filed', durMs: 2_000, detail: 'wiki/_translations/2026-07-01-letter.md', ok: true },
    ],
  },
  {
    id: nextId('run'), agent: 'research-scout', goal: 'Survey local-first sync engines',
    status: 'failed', startedAt: iso(7.4 * 3_600_000), elapsedMs: 210_000, tokens: 4_100,
    steps: [
      { t: iso(7.4 * 3_600_000), kind: 'tool', label: 'browser.open', durMs: 180_000, detail: 'camofox-browser :9377', ok: false },
      { t: iso(7.3 * 3_600_000), kind: 'gate', label: 'retry denied', durMs: 8_000, detail: 'browser offline → 503, no fallback', ok: false },
    ],
  },
  {
    id: nextId('run'), agent: 'inbox-triage', goal: 'Morning inbox sweep',
    status: 'waiting_approval', startedAt: iso(12 * 60_000), tokens: 6_540,
    steps: [
      { t: iso(12 * 60_000), kind: 'tool', label: 'inbox.list', durMs: 6_000, detail: '17 new items', ok: true },
      { t: iso(10 * 60_000), kind: 'llm', label: 'draft replies', durMs: 51_000, detail: '2 drafts, 1 requires send', ok: true },
      { t: iso(9 * 60_000), kind: 'gate', label: 'inbox.send_reply', durMs: 3_000, detail: 'escalated to approvals', ok: true },
    ],
  },
]

export const events: OsEvent[] = [
  { id: nextId('ev'), t: iso(30_000), kind: 'agent', agent: 'kb-librarian', message: 'critic pass 2/3 on "spaced repetition"' },
  { id: nextId('ev'), t: iso(2 * 60_000), kind: 'vault', message: 'wiki/concepts/interleaving.md updated (+42 lines)' },
  { id: nextId('ev'), t: iso(4 * 60_000), kind: 'memory', message: 'consolidated 3 turns from thread "sleep schedule"' },
  { id: nextId('ev'), t: iso(6 * 60_000), kind: 'trigger', agent: 'kb-librarian', message: 'raw/ drop matched KB_AUTO_COMPILE' },
  { id: nextId('ev'), t: iso(9 * 60_000), kind: 'approval', agent: 'inbox-triage', message: 'inbox.send_reply escalated (high risk)' },
  { id: nextId('ev'), t: iso(14 * 60_000), kind: 'system', message: 'scheduler rescan: 6 agents, 4 cron triggers' },
]

// pool the mock engine draws from to keep the feed alive
export const eventScript: Array<Omit<OsEvent, 'id' | 't'>> = [
  { kind: 'vault', message: 'user/journal/2026-07-01.md saved' },
  { kind: 'agent', agent: 'kb-librarian', message: 'backlinked "spacing effect" ↔ "forgetting curve"' },
  { kind: 'memory', message: 'recall hit: 4 entries injected into chat turn' },
  { kind: 'agent', agent: 'chief-of-staff', message: 'digest section "money" drafted' },
  { kind: 'trigger', agent: 'translator', message: 'watch: wiki/_translations/review queue changed' },
  { kind: 'kb', message: 'kb_lint: 2 orphans, 1 stale article flagged' },
  { kind: 'system', message: 'ollama: qwen3:14b warm, 41 tok/s' },
  { kind: 'vault', message: 'raw/collected/paper-attention.md image pass done' },
  { kind: 'agent', agent: 'money-clerk', message: '3 transactions categorized (groceries, transit)' },
  { kind: 'memory', message: 'trajectory distilled from run kb-librarian#291' },
]

// occasionally drawn from by the mock event engine so the queue feels inhabited
export const approvalPool: Array<Omit<Approval, 'id' | 'requestedAt'>> = [
  {
    agent: 'chief-of-staff', tool: 'inbox.archive_bulk', risk: 'medium',
    args: { count: '23', filter: 'newsletters older than 30d' },
    reason: 'Bulk archive is destructive enough to gate.',
  },
  {
    agent: 'kb-librarian', tool: 'vault.delete_note', risk: 'high',
    args: { path: 'wiki/concepts/duplicate-spacing-effect.md', cause: 'duplicate of spacing-effect.md' },
    reason: 'Deletion in wiki/ always requires a human.',
  },
  {
    agent: 'money-clerk', tool: 'money.set_alert', risk: 'low',
    args: { category: 'eating out', threshold: '₮250,000/mo' },
    reason: 'New alert rule changes future notifications.',
  },
]

export function spawnApproval(): Approval {
  const seed = approvalPool[Math.floor(Math.random() * approvalPool.length)]
  const item: Approval = { ...seed, id: nextId('ap'), requestedAt: new Date().toISOString() }
  approvals.unshift(item)
  return item
}

export const memories: MemoryEntry[] = [
  { id: nextId('m'), kind: 'preference', text: 'Prefers evening deep-work blocks; mornings are for review only.', source: 'chat 06-28', t: iso(3 * 86_400_000), strength: 0.92 },
  { id: nextId('m'), kind: 'fact', text: 'Rent renewal deadline is July 15; landlord prefers email.', source: 'inbox-triage run', t: iso(86_400_000), strength: 0.88 },
  { id: nextId('m'), kind: 'trajectory', text: 'kb_compile works best with ≤3 sources per concept; more causes citation drift.', source: 'run #274 postmortem', t: iso(2 * 86_400_000), strength: 0.81 },
  { id: nextId('m'), kind: 'entity', text: 'camofox-browser: local scraping browser on :9377, flaky after sleep.', source: 'trace analysis', t: iso(5 * 86_400_000), strength: 0.77 },
  { id: nextId('m'), kind: 'preference', text: 'Mongolian translations: formal register for letters, casual for chat.', source: 'TM corrections', t: iso(4 * 86_400_000), strength: 0.9 },
  { id: nextId('m'), kind: 'fact', text: 'Monthly discretionary budget ₮1.8M, alerts at 80%.', source: 'money setup', t: iso(12 * 86_400_000), strength: 0.95 },
]

export const threads: ChatThread[] = [
  {
    id: nextId('th'), title: 'sleep schedule experiment', model: 'qwen3:14b', updated: iso(3 * 3_600_000),
    messages: [
      { role: 'user', content: 'Summarize how week 2 of the earlier-bedtime experiment went, using my journal.', t: iso(3.1 * 3_600_000) },
      { role: 'memory', content: '4 entries recalled: journal 06-24—06-29, preference "evening deep work"', t: iso(3.1 * 3_600_000) },
      { role: 'assistant', content: 'Week 2 held better than week 1: average lights-out 00:40 vs 01:25, and you logged deep-work blocks on 4 of 6 evenings. The two misses correlate with late gym sessions. Suggest moving gym to mornings on Tue/Thu next week.', t: iso(3 * 3_600_000), tokens: 412, elapsedMs: 5400 },
    ],
  },
  { id: nextId('th'), title: 'translator eval design', model: 'qwen3:14b', updated: iso(26 * 3_600_000), messages: [] },
  { id: nextId('th'), title: 'kb: what is interleaving?', model: 'llama3.3:8b', updated: iso(2 * 86_400_000), messages: [] },
]

export const health: Health = { backend: 'ok', ollama: 'ok', caldav: 'degraded', browser: 'offline' }

export const memoryStats: MemoryStats = {
  // the spine compounding: slow at first, steeper as agents run more
  growth: [
    12, 14, 15, 15, 17, 19, 22, 23, 25, 28, 28, 31, 35, 36, 40,
    41, 45, 49, 50, 54, 59, 61, 66, 70, 71, 77, 82, 84, 89, 94,
  ],
  byKind: { fact: 31, preference: 18, trajectory: 27, entity: 18 },
}

export const agentStats: Record<string, AgentStats> = {
  'chief-of-staff': { runsByDay: [4, 5, 4, 6, 5, 7, 6], completed: 36, failed: 1 },
  'kb-librarian': { runsByDay: [2, 6, 3, 8, 5, 11, 9], completed: 41, failed: 3 },
  translator: { runsByDay: [9, 12, 8, 15, 11, 13, 14], completed: 79, failed: 3 },
  'inbox-triage': { runsByDay: [3, 3, 2, 3, 4, 3, 3], completed: 20, failed: 1 },
  'money-clerk': { runsByDay: [1, 2, 1, 2, 1, 3, 2], completed: 12, failed: 0 },
  'research-scout': { runsByDay: [1, 0, 2, 1, 0, 1, 1], completed: 3, failed: 3 },
}
