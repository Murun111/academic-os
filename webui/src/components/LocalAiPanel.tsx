// Local AI panel — shows whether AI is available and drives the bundled
// model download when neither Ollama nor a downloaded model exists.
import { useEffect, useRef, useState } from 'react'
import { Cpu, Download, Play, Square } from 'lucide-react'
import { localaiApi, type LocalAiStatus } from '../lib/localaiApi'
import { Btn, Mono, Panel, PanelHead, StatusDot } from './ui'

export function LocalAiPanel() {
  const [s, setS] = useState<LocalAiStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const poll = useRef<number | null>(null)

  const refresh = async () => setS(await localaiApi.status())
  useEffect(() => {
    void refresh()
    return () => { if (poll.current) window.clearInterval(poll.current) }
  }, [])

  // poll while a download is running
  useEffect(() => {
    const active = s?.download && !s.download.done && !s.download.error
    if (active && !poll.current) {
      poll.current = window.setInterval(() => void refresh(), 2000)
    }
    if (!active && poll.current) {
      window.clearInterval(poll.current)
      poll.current = null
    }
  }, [s])

  const download = async (model: 'standard' | 'small') => {
    setBusy(true)
    const ok = await localaiApi.download(model)
    setNote(ok ? 'Downloading — you can keep using the app.' : 'Could not start the download.')
    await refresh()
    setBusy(false)
  }

  const start = async () => {
    setBusy(true)
    setNote('Starting local AI (first start loads the model — up to a minute)…')
    const ok = await localaiApi.start()
    setNote(ok ? 'Local AI running.' : 'Could not start — see status below.')
    await refresh()
    setBusy(false)
  }

  const stopServer = async () => {
    setBusy(true)
    await localaiApi.stop()
    setNote('Stopped.')
    await refresh()
    setBusy(false)
  }

  if (!s) return null
  const dl = s.download
  const downloading = !!dl && !dl.done && !dl.error

  return (
    <Panel className="mb-6">
      <PanelHead
        label="local ai"
        right={
          <span className="flex items-center gap-1.5">
            <StatusDot state={s.running ? 'running' : 'idle'} live={s.running} />
            <Mono className="text-low">{s.running ? `serving :${s.port}` : 'stopped'}</Mono>
          </span>
        }
      />
      <div className="px-5 pb-4">
        {!s.binary && (
          <p className="text-[12.5px] text-mid">
            Bundled AI engine not found in this build — install Ollama instead, or use a
            packaged release.
          </p>
        )}

        {s.binary && !s.model && !downloading && (
          <>
            <p className="mb-3 text-[12.5px] text-mid">
              <Cpu size={12} className="mr-1 inline" />
              AI features (essay feedback, agent briefings) can run fully on this
              computer — no account, nothing uploaded. One-time model download:
            </p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(s.models).map(([key, m]) => (
                <Btn key={key} onClick={() => void download(key as 'standard' | 'small')} disabled={busy}>
                  <span className="flex items-center gap-1.5">
                    <Download size={12} /> {m.label} · {(m.size_mb / 1024).toFixed(1)}GB
                  </span>
                </Btn>
              ))}
            </div>
          </>
        )}

        {downloading && dl && (
          <div>
            <div className="mb-1 flex items-baseline justify-between">
              <Mono className="text-mid">downloading {dl.model}</Mono>
              <Mono className="text-hi">{dl.pct ?? 0}%</Mono>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-black/6">
              <div className="h-full rounded-full bg-black/40 transition-[width] duration-500"
                   style={{ width: `${dl.pct ?? 0}%` }} />
            </div>
          </div>
        )}

        {dl?.error && (
          <p className="text-[12.5px] text-fail">
            Download failed: {dl.error} — click the model button to resume.
          </p>
        )}

        {s.model && (
          <div className="flex items-center gap-3">
            <Mono className="text-low">model: {s.models[s.model]?.label ?? s.model}</Mono>
            {s.running ? (
              <Btn onClick={() => void stopServer()} disabled={busy}>
                <span className="flex items-center gap-1.5"><Square size={11} /> Stop</span>
              </Btn>
            ) : (
              <Btn kind="primary" onClick={() => void start()} disabled={busy}>
                <span className="flex items-center gap-1.5"><Play size={11} /> Start</span>
              </Btn>
            )}
          </div>
        )}

        {note && <p className="mt-2 text-[12.5px] text-mid">{note}</p>}
      </div>
    </Panel>
  )
}
