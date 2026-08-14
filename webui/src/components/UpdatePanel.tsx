// "Update now" panel — lives at the bottom of Settings, in the "your data"
// panel where the version + update-check UI used to sit.
//
// Backend contract (backend/routers/update.py + backend/services/updater.py):
// there's no separate "check" step — POST /install runs the whole
// check→download→verify→install→relaunch job in the background, and
// `available_version` only becomes known partway through that job. So
// unlike a typical "we already know vX.Y.Z is out, click to install" flow,
// eligible builds get one "Check for updates" action that both checks and
// installs; the version shows up once the job discovers it.
//
// updateApi fails soft to null/false when the route is missing entirely
// (older build, dev checkout with no self-updater wired up) — this panel
// then falls back to the plain "check on GitHub" link that shipped before
// self-update existed.
import { useEffect, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import { Btn, Mono } from './ui'
import { updateApi, type UpdateStatus } from '../lib/updateApi'

// Exact spelling of `state` is the updater agent's call — match on
// substrings so this keeps working even if the enum wording shifts.
type Phase = 'error' | 'restarting' | 'installing' | 'verifying' | 'downloading' | 'checking' | 'idle'

function phaseOf(status: UpdateStatus): Phase {
  if (status.error_kind) return 'error'
  const s = (status.state || '').toLowerCase()
  if (s.includes('restart')) return 'restarting'
  if (s.includes('install')) return 'installing'
  if (s.includes('verif')) return 'verifying'
  if (s.includes('download') || (status.pct != null && status.pct < 100)) return 'downloading'
  if (s.includes('check')) return 'checking'
  return 'idle'
}

const JOB_ACTIVE: Phase[] = ['checking', 'downloading', 'verifying', 'installing', 'restarting']

function errorCopy(status: UpdateStatus): string {
  switch (status.error_kind) {
    case 'network_error':
      return "Can't reach the update server — check your internet connection and try again."
    case 'verify_error':
      return 'The downloaded update failed a security check and was discarded. Try again.'
    case 'install_error':
      return 'The update could not be installed. Try again, or download it manually below.'
    default:
      return status.message || 'Update failed — try again.'
  }
}

export function UpdatePanel() {
  const [meta, setMeta] = useState<{ version: string; repo: string } | null>(null)
  const [status, setStatus] = useState<UpdateStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const poll = useRef<number | null>(null)

  // legacy "check on GitHub" flow — used when there's no backend update
  // endpoint at all, and kept as the manual path for non-eligible builds.
  const [checking, setChecking] = useState(false)
  const [checkNote, setCheckNote] = useState('')
  const [latestUrl, setLatestUrl] = useState('')

  const stopPoll = () => {
    if (poll.current) {
      window.clearInterval(poll.current)
      poll.current = null
    }
  }

  const startPoll = () => {
    stopPoll()
    const deadline = Date.now() + 10 * 60_000 // 10 min safety net, mirrors LocalAiPanel's start() guard
    poll.current = window.setInterval(() => {
      void (async () => {
        const next = await updateApi.status()
        // a fetch failure here (e.g. the server bounced mid-restart) should
        // not blank out the last real status — just keep waiting.
        if (next) setStatus(next)
        const phase = next ? phaseOf(next) : null
        const stillRunning = phase !== null && JOB_ACTIVE.includes(phase)
        if (!stillRunning || Date.now() > deadline) {
          stopPoll()
          setBusy(false)
        }
      })()
    }, 1000)
  }

  useEffect(() => {
    void fetch('/api/meta').then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (d) setMeta({ version: d.version, repo: d.repo })
    }).catch(() => {})

    void updateApi.status().then((s) => {
      setStatus(s)
      // Settings was reopened mid-update — resume polling instead of
      // leaving a stale "downloading 40%" frozen on screen.
      if (s && JOB_ACTIVE.includes(phaseOf(s))) {
        setBusy(true)
        startPoll()
      }
    })

    return () => stopPoll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const install = async () => {
    setBusy(true)
    await updateApi.install() // false on 409 (a job's already running elsewhere) or 400 (not eligible) — either way, the status poll below reflects the real state
    const fresh = await updateApi.status()
    if (fresh) setStatus(fresh)
    startPoll()
  }

  const checkGithub = async () => {
    if (!meta?.repo) return
    setChecking(true)
    setCheckNote('Checking…')
    try {
      const r = await fetch(`https://api.github.com/repos/${meta.repo}/releases/latest`)
      if (!r.ok) { setCheckNote('Could not reach the update server.'); setChecking(false); return }
      const rel = await r.json()
      const latest = String(rel.tag_name || '').replace(/^v/, '')
      if (!latest) { setCheckNote('No releases published yet.') }
      else if (latest === meta.version) { setCheckNote(`You're on the latest version (${meta.version}).`); setLatestUrl('') }
      else { setCheckNote(`Version ${latest} is available — you have ${meta.version}.`); setLatestUrl(rel.html_url) }
    } catch {
      setCheckNote('Could not check — are you offline?')
    }
    setChecking(false)
  }

  const version = status?.current_version || meta?.version || '…'
  const phase = status ? phaseOf(status) : null
  const jobActive = phase !== null && JOB_ACTIVE.includes(phase)

  return (
    <div className="mt-4 border-t border-hairline pt-3">
      <div className="flex flex-wrap items-center gap-3">
        <Mono className="text-low">version {version}</Mono>

        {/* rich mode: eligible build, no job running right now */}
        {status && status.eligible && !jobActive && phase !== 'error' && (
          <Btn
            onClick={() => void install()}
            disabled={busy}
            className="!border !border-acc/30 !bg-acc/12 !text-acc hover:!bg-acc/20"
          >
            Check for updates
          </Btn>
        )}

        {/* legacy manual check — dev builds (not eligible) and any build
            with no /api/update route at all. Also the transient state
            before the first status fetch resolves. */}
        {(!status || !status.eligible) && (
          <Btn onClick={() => void checkGithub()} disabled={checking || !meta?.repo}>
            Check for updates
          </Btn>
        )}
      </div>

      {status && phase === 'checking' && (
        <p className="mt-2 text-[12.5px] text-mid">Checking for updates…</p>
      )}

      {status && phase === 'downloading' && (
        <div className="mt-2">
          <div className="mb-1 flex items-baseline justify-between">
            <Mono className="text-mid">downloading update</Mono>
            <Mono className="text-hi">{status.pct ?? 0}%</Mono>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-ink/6">
            <div
              className="h-full rounded-full bg-acc/60 transition-[width] duration-500"
              style={{ width: `${status.pct ?? 0}%` }}
            />
          </div>
        </div>
      )}

      {status && phase === 'verifying' && (
        <p className="mt-2 text-[12.5px] text-mid">Verifying…</p>
      )}
      {status && phase === 'installing' && (
        <p className="mt-2 text-[12.5px] text-mid">
          Installing{status.available_version ? ` v${status.available_version}` : ''}…
        </p>
      )}
      {status && phase === 'restarting' && (
        <p className="mt-2 text-[12.5px] text-hi">
          Restarting — the app will reopen in a few seconds.
        </p>
      )}
      {status && phase === 'error' && (
        <div className="mt-2">
          <p className="text-[12.5px] text-fail">{errorCopy(status)}</p>
          <Btn className="mt-1.5" onClick={() => void install()} disabled={busy}>Try again</Btn>
        </div>
      )}
      {/* idle after a completed, no-op check — e.g. "You're already on the latest version." */}
      {status && phase === 'idle' && status.message && (
        <p className="mt-1.5 text-[12.5px] text-mid">{status.message}</p>
      )}

      {/* legacy note/link — GitHub check flow */}
      {checkNote && (
        <p className="mt-1.5 text-[12.5px] text-mid">
          {checkNote}{' '}
          {latestUrl && (
            <a href={latestUrl} target="_blank" rel="noreferrer" className="text-hi underline decoration-dotted">
              Download it here
            </a>
          )}
        </p>
      )}
      {/* backend already told us this build can't self-update (dev build,
          not under /Applications, non-macOS) — plain download link instead */}
      {status && !status.eligible && !checkNote && meta?.repo && (
        <div className="mt-1.5">
          {status.eligible_reason && <p className="text-[12px] text-low">{status.eligible_reason}</p>}
          <a
            href={`https://github.com/${meta.repo}/releases/latest`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[12.5px] text-hi underline decoration-dotted"
          >
            <Download size={11} /> Download the latest release
          </a>
        </div>
      )}
    </div>
  )
}
