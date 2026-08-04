// LMS calendar-feed sync panel — lives at the bottom of the Courses page.
// Paste the private "calendar feed" URL from Canvas/Moodle/Brightspace;
// assignments and courses upsert on sync.
import { useEffect, useState } from 'react'
import { RefreshCw, Link2, Trash2, Unplug } from 'lucide-react'
import { connectorsApi, type CanvasConfig, type IcsConfig } from '../lib/connectorsApi'
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

  const removeFeed = async (feed: string) => {
    setBusy(true)
    await connectorsApi.removeFeed(feed)
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
            className="h-9 flex-1 rounded-[10px] border border-line bg-transparent px-3 text-[13px] text-hi outline-none placeholder:text-low focus:border-black/25"
          />
          <Btn onClick={() => void addFeed()} disabled={busy || !url.trim()}>
            <span className="flex items-center gap-1.5"><Link2 size={12} /> Add feed</span>
          </Btn>
        </div>
        {cfg && cfg.feeds.length > 0 && (
          <div className="mb-3 flex flex-col gap-1">
            {cfg.feeds.map((f) => (
              <div key={f} className="flex items-center gap-2 rounded-[8px] bg-black/4 px-2.5 py-1.5">
                <Mono className="flex-1 truncate text-low">{f}</Mono>
                <button onClick={() => void removeFeed(f)} title="Remove feed" className="text-low hover:text-fail">
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
      </div>
    </Panel>
  )
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
    setNote(ok ? 'Connected. Run a sync.' : 'Could not save — check the URL and token.')
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
    const r = await connectorsApi.canvasSync()
    if (r) {
      const errs = r.errors.length
      setNote(
        `Canvas: ${r.courses} courses · ${r.created} new, ${r.updated} updated` +
        (errs ? ` · ${errs} error${errs > 1 ? 's' : ''}` : ''),
      )
      onSynced()
    } else {
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
            className="h-9 rounded-[10px] border border-line bg-transparent px-3 text-[13px] text-hi outline-none placeholder:text-low focus:border-black/25"
          />
          <div className="flex gap-2">
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              type="password"
              placeholder="paste your access token"
              className="h-9 flex-1 rounded-[10px] border border-line bg-transparent px-3 text-[13px] text-hi outline-none placeholder:text-low focus:border-black/25"
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
