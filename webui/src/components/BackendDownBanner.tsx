import { useBackendAlive } from '../lib/health'

export function BackendDownBanner() {
  const alive = useBackendAlive()

  if (alive) return null

  return (
    <div className="fixed top-0 right-0 left-[92px] z-30 border-b border-fail/25 bg-fail/8 px-4 py-2 text-center text-[12.5px] text-fail lg:left-[254px]">
      Can't reach the app on this computer — your data is safe. Quit and reopen Academic OS.
    </div>
  )
}
