import { useEffect, useRef, useState } from 'react'

const POLL_INTERVAL_MS = 15_000
const REQUEST_TIMEOUT_MS = 3_000
const FAILURE_THRESHOLD = 2

async function pingBackend(): Promise<boolean> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const res = await fetch('/api/meta', { signal: controller.signal })
    return res.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

/** Polls /api/meta to detect whether the backend process is reachable.
 *  Starts optimistic (alive: true) and only flips to false after two
 *  consecutive failures, so a single slow tick doesn't flash the banner. */
export function useBackendAlive(): boolean {
  const [alive, setAlive] = useState(true)
  const failures = useRef(0)

  useEffect(() => {
    let cancelled = false

    async function check() {
      const ok = await pingBackend()
      if (cancelled) return
      if (ok) {
        failures.current = 0
        setAlive(true)
      } else {
        failures.current += 1
        if (failures.current >= FAILURE_THRESHOLD) setAlive(false)
      }
    }

    void check()
    const interval = setInterval(() => void check(), POLL_INTERVAL_MS)
    const onFocus = () => void check()
    window.addEventListener('focus', onFocus)

    return () => {
      cancelled = true
      clearInterval(interval)
      window.removeEventListener('focus', onFocus)
    }
  }, [])

  return alive
}
