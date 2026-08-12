import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, CalendarPlus, Monitor, Moon, Sun, Trash2 } from 'lucide-react'
import { Btn, Mono, Panel, PanelHead } from '../components/ui'
import { LmsSyncPanel } from '../components/LmsSyncPanel'
import { LocalAiPanel } from '../components/LocalAiPanel'
import { useOs } from '../lib/store'
import { profileApi } from '../lib/profileApi'
import { memoryApi, type MemoryItem } from '../lib/memoryApi'
import { STAGES, STAGE_ORDER } from '../lib/stageConfig'
import { TRACKS, TRACK_ORDER, trackApplies, trackConfig, daysToTest } from '../lib/trackConfig'
import { study } from '../lib/studyApi'

export function Settings() {
  const stage = useOs((s) => s.stage)
  const userName = useOs((s) => s.userName)
  const track = useOs((s) => s.track)
  const testDate = useOs((s) => s.testDate)
  const setStage = useOs((s) => s.setStage)
  const setUserName = useOs((s) => s.setUserName)
  const setTrack = useOs((s) => s.setTrack)
  const setTestDate = useOs((s) => s.setTestDate)
  const reminders = useOs((s) => s.reminders)
  const setReminders = useOs((s) => s.setReminders)
  const setTour = useOs((s) => s.setTour)
  const theme = useOs((s) => s.theme)
  const setTheme = useOs((s) => s.setTheme)
  const [reminderNote, setReminderNote] = useState('')
  const [nameDraft, setNameDraft] = useState(userName)
  const [saved, setSaved] = useState(false)
  const [planNote, setPlanNote] = useState('')
  const [seeding, setSeeding] = useState(false)

  const trackCfg = trackConfig(track)
  const countdown = daysToTest(testDate)

  const seedStudyPlan = async () => {
    if (!trackCfg?.studyPlan || !testDate) return
    setSeeding(true)
    const today = new Date().toISOString().slice(0, 10)
    let added = 0
    for (const step of trackCfg.studyPlan) {
      const d = new Date(`${testDate}T00:00:00`)
      d.setDate(d.getDate() - step.daysBeforeTest)
      let day = d.toISOString().slice(0, 10)
      if (day < today) day = today // late start: pull past steps to today
      await study.addTask({ title: step.title, day })
      added += 1
    }
    setSeeding(false)
    setPlanNote(`Added ${added} steps to your Study planner, anchored to ${testDate}.`)
  }

  // the store loads the profile async — sync the draft when it arrives
  useEffect(() => setNameDraft(userName), [userName])

  const commitName = async () => {
    const next = nameDraft.trim()
    if (next === userName) return
    await setUserName(next)
    setSaved(true)
    setTimeout(() => setSaved(false), 1600)
  }

  return (
    <div className="mx-auto max-w-[760px]">
      <div className="mb-6">
        <p className="label-mono mb-1">everything lives on this computer</p>
        <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Settings</h1>
      </div>

      <Panel className="mb-6">
        <PanelHead
          label="about you"
          right={saved ? (
            <span className="flex items-center gap-1 text-[12px] text-acc"><Check size={12} /> saved</span>
          ) : undefined}
        />
        <div className="px-5 pb-5">
          <p className="label-mono mb-1">your name</p>
          <input
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={() => void commitName()}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            placeholder="What should we call you?"
            className="mb-4 w-full max-w-[320px] rounded-lg border border-line bg-raise2 px-3 py-2 text-[13px] text-hi outline-none placeholder:text-low focus:border-ink/25"
          />

          <p className="label-mono mb-1.5">where you are</p>
          <div className="flex flex-wrap gap-2">
            {STAGE_ORDER.map((s) => (
              <button
                key={s}
                onClick={() => void setStage(s)}
                className={`rounded-lg border px-3 py-2 text-left transition-colors duration-150 ${
                  stage === s
                    ? 'border-ink/25 bg-ink/6 text-hi'
                    : 'border-line text-mid hover:border-ink/15 hover:text-hi'
                }`}
              >
                <span className="block text-[13px]">{STAGES[s].label}</span>
                <span className="block text-[11px] text-low">{STAGES[s].tagline}</span>
              </button>
            ))}
          </div>
          <p className="mt-2 text-[12px] text-low">
            This shapes the whole app — what the pipeline is called, which checklists you get, and
            what shows up first.
          </p>

          <p className="label-mono mt-4 mb-1.5">appearance</p>
          <div className="flex gap-2">
            {([
              { key: 'system', label: 'System', icon: Monitor },
              { key: 'light', label: 'Light', icon: Sun },
              { key: 'dark', label: 'Dark', icon: Moon },
            ] as const).map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setTheme(key)}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-[13px] transition-colors duration-150 ${
                  theme === key
                    ? 'border-ink/25 bg-ink/6 text-hi'
                    : 'border-line text-mid hover:border-ink/15 hover:text-hi'
                }`}
              >
                <Icon size={13} />
                {label}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[12px] text-low">
            System follows your Mac's appearance and switches with it automatically.
          </p>
        </div>
      </Panel>

      {trackApplies(stage) && (
        <Panel className="mb-6">
          <PanelHead
            label="after undergrad"
            right={trackCfg?.exam && countdown != null ? (
              <Mono className="text-pend">{trackCfg.exam} in {countdown}d</Mono>
            ) : undefined}
          />
          <div className="px-5 pb-5">
            <p className="label-mono mb-1.5">what's next for you</p>
            <div className="mb-1 flex flex-wrap gap-2">
              {TRACK_ORDER.map((t) => (
                <button
                  key={t}
                  onClick={() => void setTrack(track === t ? null : t)}
                  className={`rounded-lg border px-3 py-2 text-left transition-colors duration-150 ${
                    track === t
                      ? 'border-ink/25 bg-ink/6 text-hi'
                      : 'border-line text-mid hover:border-ink/15 hover:text-hi'
                  }`}
                >
                  <span className="block text-[13px]">{TRACKS[t].label}</span>
                  <span className="block text-[11px] text-low">{TRACKS[t].tagline}</span>
                </button>
              ))}
            </div>
            <p className="mb-4 text-[12px] text-low">
              This renames your pipeline, swaps in the right application checklists, and unlocks
              an exam study plan.
            </p>

            {trackCfg?.exam && (
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <p className="label-mono mb-1">{trackCfg.exam} date</p>
                  <input
                    type="date"
                    value={testDate}
                    onChange={(e) => void setTestDate(e.target.value)}
                    className="rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-ink/25"
                  />
                </div>
                {trackCfg.studyPlan && testDate && (
                  <Btn onClick={() => void seedStudyPlan()} disabled={seeding}>
                    <span className="flex items-center gap-1.5">
                      <CalendarPlus size={13} />
                      {seeding ? 'Adding…' : 'Add study plan to Study'}
                    </span>
                  </Btn>
                )}
              </div>
            )}
            {planNote && <p className="mt-2 text-[12.5px] text-mid">{planNote}</p>}
          </div>
        </Panel>
      )}

      <div data-tour="settings-ai">
        <LocalAiPanel />
      </div>

      <LmsSyncPanel onSynced={() => {}} />

      <div data-tour="settings-reminders">
      <Panel className="mt-6">
        <PanelHead label="reminders" />
        <div className="px-5 pb-5">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={reminders}
              onChange={(e) => void setReminders(e.target.checked)}
              className="size-3.5 accent-ink/70"
            />
            <span className="text-[13px] text-hi">Daily deadline notification</span>
          </label>
          <p className="mt-1 text-[12px] text-low">
            Once a day while the app is running, a Mac notification sums up everything due in
            the next 7 days. Nothing is sent anywhere — it's your Mac talking to you.
          </p>
          <div className="mt-3 flex items-center gap-3">
            <Btn
              onClick={async () => {
                setReminderNote('…')
                const r = await profileApi.testReminder()
                setReminderNote(
                  r?.sent
                    ? 'Sent — check the top-right corner of your screen.'
                    : r?.reason === 'nothing_due'
                      ? 'Nothing due in the next 7 days, so there was nothing to say.'
                      : 'Could not send the notification.',
                )
              }}
            >
              Send a test notification
            </Btn>
            {reminderNote && <span className="text-[12.5px] text-mid">{reminderNote}</span>}
          </div>
        </div>
      </Panel>
      </div>

      <div data-tour="settings-memory">
        <MemoryPanel />
      </div>

      <BackupPanel />

      <Panel className="mt-6">
        <PanelHead label="your data" />
        <div className="px-5 pb-5">
          <p className="mb-1 text-[12.5px] text-mid">
            Everything is stored in one folder on this computer — nothing is uploaded anywhere.
          </p>
          <Mono className="text-low">~/.academic-os</Mono>
          <p className="mt-2 text-[12px] text-low">
            Back it up by copying that folder. Deleting the app never deletes your data.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Btn onClick={() => setTour(true)}>Replay the walkthrough</Btn>
            <Link to="/export">
              <Btn>Progress report for a counselor (PDF)</Btn>
            </Link>
          </div>
          <UpdateCheck />
        </div>
      </Panel>
    </div>
  )
}

function MemoryPanel() {
  const [items, setItems] = useState<MemoryItem[]>([])
  const [loaded, setLoaded] = useState(false)
  const [confirmWipe, setConfirmWipe] = useState(false)

  const load = async () => {
    setItems(await memoryApi.items())
    setLoaded(true)
  }
  useEffect(() => { void load() }, [])

  const forgetOne = async (id: string) => {
    await memoryApi.forget(id)
    await load()
  }

  const forgetAll = async () => {
    if (!confirmWipe) {
      setConfirmWipe(true)
      return
    }
    await memoryApi.forgetAll()
    setConfirmWipe(false)
    await load()
  }

  return (
    <Panel className="mt-6">
      <PanelHead
        label="what this app remembers"
        right={loaded ? <Mono className="text-low">{items.length} memories</Mono> : undefined}
      />
      <div className="px-5 pb-5">
        <p className="mb-3 text-[12.5px] text-mid">
          Chat conversations leave behind small notes — facts, preferences, todos — that get
          recalled in later chats. They never leave this computer. Delete any of them here;
          recall stops immediately.
        </p>

        {loaded && items.length === 0 && (
          <Mono className="text-low">Nothing yet — memories come from Chat conversations.</Mono>
        )}

        {items.length > 0 && (
          <>
            <div className="mb-3 flex max-h-[320px] flex-col gap-1 overflow-y-auto">
              {items.map((m) => (
                <div key={m.item_id} className="flex items-start gap-2 rounded-[10px] px-2 py-1.5 hover:bg-ink/4">
                  <span className="mt-0.5 shrink-0 rounded-full border border-line px-1.5 font-mono text-[10px] text-low">
                    {m.kind}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12.5px] text-hi">{m.subject}</p>
                    <p className="line-clamp-2 text-[12px] leading-snug text-mid">{m.body}</p>
                  </div>
                  <button
                    onClick={() => void forgetOne(m.item_id)}
                    title="Forget this"
                    className="mt-0.5 shrink-0 text-low hover:text-fail"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
            <Btn kind={confirmWipe ? 'danger' : 'quiet'} onClick={() => void forgetAll()}>
              {confirmWipe ? 'Click again to forget everything' : 'Forget everything'}
            </Btn>
          </>
        )}
      </div>
    </Panel>
  )
}

function UpdateCheck() {
  const [version, setVersion] = useState('')
  const [repo, setRepo] = useState('')
  const [note, setNote] = useState('')
  const [latestUrl, setLatestUrl] = useState('')

  useEffect(() => {
    void fetch('/api/meta').then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (d) { setVersion(d.version); setRepo(d.repo) }
    }).catch(() => {})
  }, [])

  const check = async () => {
    setNote('Checking…')
    try {
      const r = await fetch(`https://api.github.com/repos/${repo}/releases/latest`)
      if (!r.ok) { setNote('Could not reach the update server.'); return }
      const rel = await r.json()
      const latest = String(rel.tag_name || '').replace(/^v/, '')
      if (!latest) { setNote('No releases published yet.'); return }
      if (latest === version) {
        setNote(`You're on the latest version (${version}).`)
        setLatestUrl('')
      } else {
        setNote(`Version ${latest} is available — you have ${version}.`)
        setLatestUrl(rel.html_url)
      }
    } catch {
      setNote('Could not check — are you offline?')
    }
  }

  return (
    <div className="mt-4 border-t border-hairline pt-3">
      <div className="flex items-center gap-3">
        <Mono className="text-low">version {version || '…'}</Mono>
        <Btn onClick={() => void check()} disabled={!repo}>Check for updates</Btn>
      </div>
      {note && (
        <p className="mt-1.5 text-[12.5px] text-mid">
          {note}{' '}
          {latestUrl && (
            <a href={latestUrl} target="_blank" rel="noreferrer" className="text-hi underline decoration-dotted">
              Download it here
            </a>
          )}
        </p>
      )}
    </div>
  )
}

function BackupPanel() {
  const [path, setPath] = useState('')
  const [last, setLast] = useState<string | null>(null)
  const [autostart, setAutostart] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = async () => {
    try {
      const b = await (await fetch('/api/system/backup')).json()
      setPath(b.path)
      setLast(b.last_backup)
      const a = await (await fetch('/api/system/autostart')).json()
      setAutostart(!!a.enabled)
    } catch { /* backend down — panel stays empty */ }
  }
  useEffect(() => { void refresh() }, [])

  const savePath = async (p: string) => {
    setBusy(true)
    const r = await (await fetch('/api/system/backup/config', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ path: p }),
    })).json()
    setNote(r.error ? `Could not use that folder: ${r.error}` : p ? 'Backup folder set.' : 'Backup off.')
    await refresh()
    setBusy(false)
  }

  const backupNow = async () => {
    setBusy(true)
    setNote('Backing up…')
    const r = await (await fetch('/api/system/backup/now', { method: 'POST' })).json()
    setNote(r.ok ? `Backed up to ${r.dest}` : `Backup failed: ${r.error}`)
    await refresh()
    setBusy(false)
  }

  const toggleAutostart = async (enabled: boolean) => {
    setBusy(true)
    const r = await (await fetch('/api/system/autostart', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })).json()
    if (r.error) setNote(r.error)
    await refresh()
    setBusy(false)
  }

  return (
    <Panel className="mt-6">
      <PanelHead
        label="backup + always on"
        right={last ? <Mono className="text-low">last backup {last.slice(0, 16).replace('T', ' ')}</Mono> : undefined}
      />
      <div className="px-5 pb-5">
        <p className="label-mono mb-1">backup folder</p>
        <p className="mb-2 text-[12px] text-low">
          Pick any folder that syncs — iCloud Drive, Google Drive, Dropbox. Your data mirrors
          there every hour, so a lost laptop doesn't mean a lost application season.
        </p>
        <div className="flex gap-2">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onBlur={() => void savePath(path.trim())}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            placeholder="~/Library/Mobile Documents/com~apple~CloudDocs/AcademicOS"
            className="flex-1 rounded-lg border border-line bg-raise2 px-3 py-1.5 font-mono text-[12px] text-hi outline-none placeholder:text-low focus:border-ink/25"
          />
          <Btn onClick={() => void backupNow()} disabled={busy || !path.trim()}>Back up now</Btn>
        </div>

        <label className="mt-4 flex items-center gap-2">
          <input
            type="checkbox"
            checked={autostart}
            onChange={(e) => void toggleAutostart(e.target.checked)}
            className="size-3.5 accent-ink/70"
          />
          <span className="text-[13px] text-hi">Start Academic OS when you log in</span>
        </label>
        <p className="mt-1 text-[12px] text-low">
          Keeps deadline notifications and Canvas sync working without opening the app yourself.
        </p>

        {note && <p className="mt-2 text-[12.5px] text-mid">{note}</p>}
      </div>
    </Panel>
  )
}
