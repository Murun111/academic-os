// ?nomotion strips entrance animations app-wide — for automation, screenshots,
// and rAF-throttled contexts (hidden tabs in test harnesses freeze mid-tween).
export const NO_MOTION = new URLSearchParams(window.location.search).has('nomotion')
