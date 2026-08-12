import { useEffect, useState } from 'react'

export function DataFormatBanner() {
  const [incompatible, setIncompatible] = useState(false)

  useEffect(() => {
    void fetch('/api/meta')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.data_format?.compatible === false) setIncompatible(true)
      })
      .catch(() => {})
  }, [])

  if (!incompatible) return null

  return (
    <div className="fixed top-0 right-0 left-[92px] z-30 border-b border-pend/25 bg-pend/8 px-4 py-2 text-center text-[12.5px] text-pend lg:left-[254px]">
      This data was created by a newer version of Academic OS. Editing is disabled — update the app to continue.
    </div>
  )
}
