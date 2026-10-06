import { Loader2, MessageSquareText, Paperclip, X } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'

import { LANGUAGE_LABEL, sizeLabel } from '@/components/ocap/ocapModel'
import { CheckRow, FormField } from '@/components/setup/FormParts'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ACCEPT, MAX_FILE_BYTES, readBase64 } from '@/services/ocapApi'
import type { GuidanceBody } from '@/services/workflowApi'
import type { OcapLanguage } from '@/types/ocapApi'

/**
 * A Manager's guidance (GDE-01, ADR-0031): the text, at most one PDF or Word file (scanned before it's kept), and,
 * optionally, the guidance kept as a reusable OCAP that's searched from then on.
 */
export function GuidanceForm({ text, busy, onSend }: {
  /** The text box, kept as a draft by the card */
  text: ReactNode
  busy: boolean
  onSend: (body: (text: string) => Promise<GuidanceBody>) => void
}) {
  const picker = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [reusable, setReusable] = useState(false)
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')
  const [language, setLanguage] = useState<OcapLanguage>('en')

  const choose = (f: File | null) => {
    setFileError(f && f.size > MAX_FILE_BYTES ? `${f.name} is ${sizeLabel(f.size)}: 20 MB at most` : null)
    setFile(f && f.size <= MAX_FILE_BYTES ? f : null)
  }

  const send = () =>
    onSend(async (t) => ({
      text: t,
      ...(file ? { attachment: { name: file.name, contentBase64: await readBase64(file) } } : {}),
      ...(reusable ? { reusable: { code: code.trim(), title: title.trim(), language } } : {}),
    }))

  return (
    <div className="flex flex-col gap-2">
      {text}
      <div className="flex flex-wrap items-center gap-2">
        <input ref={picker} type="file" accept={ACCEPT} className="hidden" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
        {file ? (
          <span className="border-line text-ink inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12px]">
            <Paperclip className="size-3.5" aria-hidden /> {file.name} · {sizeLabel(file.size)}
            <button type="button" className="text-ink-muted hover:text-ink" aria-label="Remove the file" onClick={() => choose(null)}>
              <X className="size-3.5" aria-hidden />
            </button>
          </span>
        ) : (
          <Button type="button" variant="outline" size="sm" onClick={() => picker.current?.click()}>
            <Paperclip className="size-4" aria-hidden /> Attach a PDF or Word file
          </Button>
        )}
        {fileError && <span className="text-critical text-[12px]">{fileError}</span>}
      </div>
      <CheckRow checked={reusable} onChange={setReusable} label="Also keep it as a reusable OCAP"
                description="Active at once: later reasons with these words are offered it. The file isn't part of it." />
      {reusable && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[140px_1fr_140px]">
          <FormField label="Code">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="OCAP-050" aria-label="The new OCAP's code" />
          </FormField>
          <FormField label="Title">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Trial films on the verticals"
                   aria-label="The new OCAP's title" />
          </FormField>
          <FormField label="Written in">
            <Select value={language} onValueChange={(v) => setLanguage(v as OcapLanguage)}>
              <SelectTrigger size="sm" aria-label="The guidance's language">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(LANGUAGE_LABEL) as OcapLanguage[]).map((l) => (
                  <SelectItem key={l} value={l}>
                    {LANGUAGE_LABEL[l]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
      )}
      <Button type="button" size="sm" className="self-end" disabled={busy || (reusable && (!code.trim() || !title.trim()))}
              onClick={send}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <MessageSquareText className="size-4" aria-hidden />} Send the
        guidance
      </Button>
    </div>
  )
}
