import { MonitorX } from 'lucide-react'

/** Shown in place of the model when the browser can't draw it: the rest of the page works without it. */
export function TwinUnavailable({ detail }: { detail: string }) {
  return (
    <div className="text-nav-fg flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
      <MonitorX className="size-6" aria-hidden />
      <p className="text-nav-fg-strong text-[13px] font-medium">The 3D view can't be shown here</p>
      <p className="max-w-sm text-[12px]">{detail} Every zone is in the panel and in the table below.</p>
    </div>
  )
}
