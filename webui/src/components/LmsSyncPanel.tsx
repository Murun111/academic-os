// LMS calendar-feed sync panel — lives at the bottom of the Courses page.
// Paste the private "calendar feed" URL from Canvas/Moodle/Brightspace;
// assignments and courses upsert on sync.
import { useEffect, useState } from 'react'
import { RefreshCw, Link2, Trash2, Unplug } from 'lucide-react'
import { connectorsApi, type CanvasConfig, type CanvasSyncResult, type IcsConfig } from '../lib/connectorsApi'
import { coursesApi } from '../lib/coursesApi'
import { Btn, Mono, Panel, PanelHead } from './ui'

export function LmsSyncPanel({ onSynced }: { onSynced: () => void }) {
  const [cfg, setCfg] = useState<IcsConfig | null>(null)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')

  const refresh = async () => setCfg(await connectorsApi.status())
  useEffect(() => { void refresh() }, [])

  const addFeed = async () => {
    if (!url.trim()) return
    setBusy(true)
    const ok = await connectorsApi.addFeed(url.trim())
    setNote(ok ? '' : 'That does not look like a valid URL.')
    if (ok) setUrl('')
    await refresh()
    setBusy(false)
  }

  const removeFeed = async (id: number) => {
    setBusy(true)
    await connectorsApi.removeFeed(id)
    await refresh()
    setBusy(false)
  }

  const syncNow = async () => {
    setBusy(true)
    setNote('Syncing…')
    const result = await connectorsApi.sync()
    if (result) {
      const errs = result.errors.length
      setNote(
        `Synced: ${result.created} new, ${result.updated} updated, ${result.unchanged} unchanged` +
        (errs ? ` · ${errs} feed error${errs > 1 ? 's' : ''}` : ''),
      )
      onSynced()
    } else {
      setNote('Sync failed — check the feed URL and your connection.')
    }
    await refresh()
    setBusy(false)
  }

  return (
    <Panel className="mt-6">
      <PanelHead
        label="school calendar sync"
        right={cfg?.last_sync ? <Mono className="text-low">last sync {cfg.last_sync.slice(0, 16).replace('T', ' ')}</Mono> : undefined}
      />
      <div className="px-4 pb-4">
        <p className="mb-3 text-[12.5px] text-mid">
          Paste your school calendar feed URL (Canvas: Calendar → Calendar Feed;
          Moodle/Brightspace have the same). Due dates sync into your courses —
          read-only, your school account is never touched.
        </p>
        <div className="mb-3 flex gap-2">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://school.instructure.com/feeds/calendars/user_….ics"
            className="h-9 flex-1 rounded-[10px] border border-line bg-transparent px-3 text-[13px] text-hi outline-none placeholder:text-low focus:border-ink/25"
          />
          <Btn onClick={() => void addFeed()} disabled={busy || !url.trim()}>
            <span className="flex items-center gap-1.5"><Link2 size={12} /> Add feed</span>
          </Btn>
        </div>
        {cfg && cfg.feeds.length > 0 && (
          <div className="mb-3 flex flex-col gap-1">
            {cfg.feeds.map((f) => (
              <div key={f.id} className="flex items-center gap-2 rounded-[8px] bg-ink/4 px-2.5 py-1.5">
                <Mono className="flex-1 truncate text-low">{f.host || 'calendar feed'} · configured</Mono>
                <button onClick={() => void removeFeed(f.id)} title="Remove feed" className="text-low hover:text-fail">
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-center gap-3">
          <Btn kind="primary" onClick={() => void syncNow()} disabled={busy || !cfg || cfg.feeds.length === 0}>
            <span className="flex items-center gap-1.5"><RefreshCw size={12} /> Sync now</span>
          </Btn>
          {note && <span className="text-[12.5px] text-mid">{note}</span>}
        </div>

        <CanvasSection onSynced={onSynced} />

        <DuplicateNotice onChanged={onSynced} />
      </div>
    </Panel>
  )
}

// ── duplicate detection ──────────────────────────────────────────────────────
// Connecting BOTH Canvas and a calendar feed creates the same class twice —
// the two sources can't recognize each other's copies. Detect likely pairs by
// normalized name and offer one-click removal of the feed copy (Canvas is the
// richer source).
function dupKey(name: string): string {
  return name.toLowerCase().split('(')[0].split('_')[0].trim()
}

function DuplicateNotice({ onChanged }: { onChanged: () => void }) {
  const [dupes, setDupes] = useState<{ id: string; name: string }[]>([])
  const [busy, setBusy] = useState(false)

  const scan = async () => {
    const res = await coursesApi.listCourses()
    const courses = res.courses
    const canvasKeys = new Set(courses.filter((c) => c.source === 'canvas').map((c) => dupKey(c.name)))
    const feedCopies = courses.filter(
      (c) => c.source !== 'canvas' && (c.source === 'ics' || c.term === 'Synced') &&
        dupKey(c.name).length >= 4 && canvasKeys.has(dupKey(c.name)),
    )
    setDupes(feedCopies.map((c) => ({ id: c.id, name: c.name })))
  }
  useEffect(() => { void scan() }, [])

  const removeCopy = async (id: string) => {
    setBusy(true)
    await coursesApi.deleteCourse(id)
    await scan()
    onChanged()
    setBusy(false)
  }

  if (dupes.length === 0) return null
  return (
    <div className="rounded-[10px] border border-pend/25 bg-pend/8 px-3 py-2.5">
      <p className="mb-1.5 text-[12.5px] text-hi">
        These classes exist twice — once from Canvas, once from the calendar feed. Canvas has
        more detail; you can safely remove the feed copies:
      </p>
      <div className="flex flex-col gap-1">
        {dupes.map((d) => (
          <div key={d.id} className="flex items-center justify-between gap-2">
            <span className="truncate text-[12.5px] text-mid">{d.name}</span>
            <Btn onClick={() => void removeCopy(d.id)} disabled={busy}>Remove feed copy</Btn>
          </div>
        ))}
      </div>
    </div>
  )
}

// Maps a total-sync-failure code (POST /api/connectors/canvas/sync responds
// 502 with {error, status?} on total failure) to copy a student can act on —
// never shows the raw exception text from the backend.
type CanvasSyncErrorKind = 'auth_error' | 'network_error' | 'canvas_error' | 'config_error' | 'unknown'

function canvasErrorMessage(kind: CanvasSyncErrorKind, status?: number): string {
  switch (kind) {
    case 'auth_error':
      return 'Canvas rejected the token — generate a new one and paste it again.'
    case 'network_error':
      return "Can't reach Canvas — check the internet connection and try again."
    case 'canvas_error':
      return `Canvas had a problem${status ? ` (HTTP ${status})` : ''} — try again in a bit.`
    default:
      return 'Canvas sync failed — check the token and URL.'
  }
}

function CanvasSection({ onSynced }: { onSynced: () => void }) {
  const [cfg, setCfg] = useState<CanvasConfig | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')

  const refresh = async () => setCfg(await connectorsApi.canvasStatus())
  useEffect(() => { void refresh() }, [])

  const connect = async () => {
    if (!baseUrl.trim() || !token.trim()) return
    setBusy(true)
    const ok = await connectorsApi.canvasConnect(baseUrl.trim(), token.trim())
    setNote(ok ? 'Connected — syncing your courses now…' : 'Could not save — check the URL and token.')
    if (ok) { setToken(''); setBaseUrl('') }
    await refresh()
    setBusy(false)
  }

  const disconnect = async () => {
    setBusy(true)
    await connectorsApi.canvasClear()
    setNote('Disconnected. Synced courses stay.')
    await refresh()
    setBusy(false)
  }

  const syncNow = async () => {
    setBusy(true)
    setNote('Syncing Canvas…')
    // connectorsApi.canvasSync() collapses any non-2xx to a bare null, which
    // loses the {error, status} the backend sends on a total failure — fetch
    // directly here so auth/network/other failures can get distinct copy.
    try {
      const res = await fetch('/api/connectors/canvas/sync', { method: 'POST' })
      if (res.ok) {
        const r = (await res.json()) as CanvasSyncResult
        const errs = r.errors.length
        setNote(
          `Canvas: ${r.courses} courses · ${r.created} new, ${r.updated} updated` +
          (errs ? ` · ${errs} error${errs > 1 ? 's' : ''}` : ''),
        )
        onSynced()
      } else {
        let kind: CanvasSyncErrorKind = 'unknown'
        let status: number | undefined
        try {
          const body = await res.json()
          if (body?.error === 'auth_error' || body?.error === 'network_error' ||
              body?.error === 'canvas_error' || body?.error === 'config_error') {
            kind = body.error
          }
          status = typeof body?.status === 'number' ? body.status : undefined
        } catch {
          // non-JSON body — fall back to the generic message
        }
        setNote(canvasErrorMessage(kind, status))
      }
    } catch {
      setNote('Canvas sync failed — check the token and URL.')
    }
    await refresh()
    setBusy(false)
  }

  return (
    <div className="mt-5 border-t border-hairline pt-4">
      <p className="label-mono mb-2">canvas (full sync)</p>
      <p className="mb-3 text-[12.5px] text-mid">
        Richer than the calendar feed: courses, assignments, submission status, and
        grades. In Canvas: Account → Settings → New Access Token. The token stays on
        this computer only.
      </p>
      {cfg?.connected ? (
        <div className="flex items-center gap-3">
          <Mono className="text-low">{cfg.base_url} · token {cfg.token_hint}</Mono>
          <Btn kind="primary" onClick={() => void syncNow()} disabled={busy}>
            <span className="flex items-center gap-1.5"><RefreshCw size={12} /> Sync Canvas</span>
          </Btn>
          <Btn onClick={() => void disconnect()} disabled={busy}>
            <span className="flex items-center gap-1.5"><Unplug size={12} /> Disconnect</span>
          </Btn>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://yourschool.instructure.com"
            className="h-9 rounded-[10px] border border-line bg-transparent px-3 text-[13px] text-hi outline-none placeholder:text-low focus:border-ink/25"
          />
          <div className="flex gap-2">
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              type="password"
              placeholder="paste your access token"
              className="h-9 flex-1 rounded-[10px] border border-line bg-transparent px-3 text-[13px] text-hi outline-none placeholder:text-low focus:border-ink/25"
            />
            <Btn onClick={() => void connect()} disabled={busy || !baseUrl.trim() || !token.trim()}>
              <span className="flex items-center gap-1.5"><Link2 size={12} /> Connect</span>
            </Btn>
          </div>
        </div>
      )}
      {note && <p className="mt-2 text-[12.5px] text-mid">{note}</p>}
    </div>
  )
}
