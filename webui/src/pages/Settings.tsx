import { useEffect, useState } from 'react'
import { Check, CalendarPlus } from 'lucide-react'
import { Btn, Mono, Panel, PanelHead } from '../components/ui'
import { LmsSyncPanel } from '../components/LmsSyncPanel'
import { LocalAiPanel } from '../components/LocalAiPanel'
import { useOs } from '../lib/store'
import { profileApi } from '../lib/profileApi'
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
            className="mb-4 w-full max-w-[320px] rounded-lg border border-line bg-raise2 px-3 py-2 text-[13px] text-hi outline-none placeholder:text-low focus:border-black/25"
          />

          <p className="label-mono mb-1.5">where you are</p>
          <div className="flex flex-wrap gap-2">
            {STAGE_ORDER.map((s) => (
              <button
                key={s}
                onClick={() => void setStage(s)}
                className={`rounded-lg border px-3 py-2 text-left transition-colors duration-150 ${
                  stage === s
                    ? 'border-black/25 bg-black/6 text-hi'
                    : 'border-line text-mid hover:border-black/15 hover:text-hi'
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
                      ? 'border-black/25 bg-black/6 text-hi'
                      : 'border-line text-mid hover:border-black/15 hover:text-hi'
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
                    className="rounded-lg border border-line bg-raise2 px-3 py-1.5 text-[13px] text-hi outline-none focus:border-black/25"
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

      <LocalAiPanel />

      <LmsSyncPanel onSynced={() => {}} />

      <Panel className="mt-6">
        <PanelHead label="reminders" />
        <div className="px-5 pb-5">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={reminders}
              onChange={(e) => void setReminders(e.target.checked)}
              className="size-3.5 accent-black/70"
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
        </div>
      </Panel>
    </div>
  )
}
