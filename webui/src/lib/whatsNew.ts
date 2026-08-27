// "What's new" changelog shown once after an in-app update lands. Same
// once-only localStorage pattern as the first-run Tour (TOUR_DONE_KEY): the
// key stores the last version the user has already been shown, so the modal
// fires exactly once per version bump and never on a fresh install (the Tour
// owns first-run).

export const WHATS_NEW_KEY = 'academicos.whatsNewSeen'

export interface WhatsNewEntry {
  title: string
  items: string[]
}

// Student-facing highlights per version — what a user actually sees and feels,
// not the technical changelog. Keep entries short; only versions with a
// user-visible change need one.
export const CHANGELOG: Record<string, WhatsNewEntry> = {
  '0.4.1': {
    title: "What's new",
    items: [
      'Updates now install themselves — one click in Settings, no more downloading and dragging.',
      'The Mac app is signed by Apple, so it opens with no security warning.',
      'Chat answers stream in as they are written instead of appearing all at once.',
      'A round of privacy and security hardening under the hood — your data still never leaves your computer.',
    ],
  },
}

/** Compare two dotted version strings; true when `a` is strictly newer than `b`. */
function isNewer(a: string, b: string): boolean {
  const pa = a.split('.').map((n) => parseInt(n, 10))
  const pb = b.split('.').map((n) => parseInt(n, 10))
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? 0
    const y = pb[i] ?? 0
    if (x !== y) return x > y
  }
  return false
}

/**
 * Whether to show the "what's new" modal for `current`, given the last version
 * the user was shown (`seen`, from localStorage; null on a fresh install).
 * Only fires on a real upgrade with changelog content — never on first run,
 * never on a downgrade / dev build.
 */
export function shouldShowWhatsNew(current: string, seen: string | null): boolean {
  if (!seen) return false // fresh install → the Tour handles first-run, stay quiet
  if (!CHANGELOG[current]) return false
  return isNewer(current, seen)
}
