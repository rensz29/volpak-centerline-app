import { FileUp, Loader2 } from 'lucide-react'
import { useRef, useState } from 'react'

import { CheckRow, FormField } from '@/components/setup/FormParts'
import { ProblemLine } from '@/components/setup/VersionDialogs'
import { asProblem } from '@/components/setup/versionUtils'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ACCEPT, MAX_FILE_BYTES, ocapApi, readBase64 } from '@/services/ocapApi'
import { ApiProblem } from '@/services/http'
import type { OcapDocument, OcapLanguage, OcapVersion } from '@/types/ocapApi'
import { cn } from '@/utils/cn'

import { LANGUAGE_LABEL, sizeLabel } from './ocapModel'

/**
 * A Manager uploads a PDF or Word file: a new OCAP, or a new version of one. It's scanned for malware, read into
 * sections with their pages, and kept as a Draft until it's activated (OCP-01, OCP-03, ADR-0031).
 */
export function UploadDialog({ document: doc, onClose, onDone }: {
  /** null: a new OCAP */
  document: OcapDocument | null
  onClose: () => void
  onDone: (v: OcapVersion) => void
}) {
  const picker = useRef<HTMLInputElement>(null)
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')
  const [language, setLanguage] = useState<OcapLanguage>(doc?.versions[0]?.language ?? 'en')
  const [file, setFile] = useState<File | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)

  const choose = (f: File | null) => {
    setProblem(f && f.size > MAX_FILE_BYTES ? new ApiProblem(0, { detail: `${f.name} is ${sizeLabel(f.size)}: 20 MB at most` }) : null)
    setFile(f && f.size <= MAX_FILE_BYTES ? f : null)
  }

  const submit = async () => {
    if (!file) return
    setBusy(true)
    setProblem(null)
    try {
      const upload = { language, source: file.name, contentBase64: await readBase64(file), reason }
      onDone(doc ? await ocapApi.addVersion(doc.id, upload) : await ocapApi.create({ ...upload, code, title }))
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }
  const fileError = problem?.forField('contentBase64')

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileUp className="size-5" aria-hidden /> {doc ? `A new version of ${doc.code}` : 'Upload an OCAP'}
          </DialogTitle>
          <DialogDescription>
            A PDF or Word (.docx) file with text in it, 20 MB at most. It's scanned, read into sections with their pages and kept
            as a Draft: check its sections, then activate it.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {!doc && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-[160px_1fr]">
              <FormField label="Code" error={problem?.forField('code')}>
                <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="OCAP-017" />
              </FormField>
              <FormField label="Title" error={problem?.forField('title')}>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Vertical sealing temperature" />
              </FormField>
            </div>
          )}
          <FormField label="File" error={fileError}>
            <input ref={picker} type="file" accept={ACCEPT} className="hidden" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
            <button type="button" onClick={() => picker.current?.click()}
                    className={cn('border-line hover:bg-surface-muted w-full rounded-md border border-dashed px-3 py-4 text-left text-[13px]',
                                  fileError && 'border-critical')}>
              {file ? (
                <span className="text-ink font-medium">{file.name} <span className="text-ink-muted font-normal">· {sizeLabel(file.size)}</span></span>
              ) : (
                <span className="text-ink-soft">Choose a PDF or Word file…</span>
              )}
            </button>
          </FormField>
          <FormField label="Written in" error={problem?.forField('language')}
                     hint="The search reads it by its language: English words by their stem, Filipino words as written.">
            <Select value={language} onValueChange={(v) => setLanguage(v as OcapLanguage)}>
              <SelectTrigger size="sm" className="max-w-[200px]" aria-label="The OCAP's language">
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
          <FormField label="Reason" error={problem?.forField('reason')}>
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
                      placeholder={doc ? 'e.g. Revision 3: the heater check moved before the probe' : 'e.g. From the quality binder, 2026 edition'} />
          </FormField>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={busy || !file || !reason.trim() || (!doc && (!code.trim() || !title.trim()))}
                  onClick={() => void submit()}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} Upload as a Draft
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Activate a version: it's searched from now on. Any other Active version of the OCAP is kept or retired
 * (OCP-03). Or suspend an Active one: it stops being searched.
 */
export function StatusDialog({ version: v, action, otherActive, onClose, onDone }: {
  version: OcapVersion
  action: 'activate' | 'suspend'
  /** The numbers of the OCAP's other Active versions */
  otherActive: number[]
  onClose: () => void
  onDone: (v: OcapVersion) => void
}) {
  const [reason, setReason] = useState('')
  const [earlier, setEarlier] = useState<'keep' | 'supersede'>('supersede')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)
  const others = otherActive.map((n) => `v${n}`).join(', ')

  const submit = async () => {
    setBusy(true)
    setProblem(null)
    try {
      onDone(action === 'activate' ? await ocapApi.activate(v.id, reason, earlier) : await ocapApi.suspend(v.id, reason))
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{action === 'activate' ? `Activate ${v.code} v${v.number}` : `Suspend ${v.code} v${v.number}`}</DialogTitle>
          <DialogDescription>
            {action === 'activate'
              ? `Its ${v.sections.length} section${v.sections.length === 1 ? '' : 's'} are searched from now on and offered to operators after their reasons.`
              : 'It stops being searched. Requests that already chose one of its sections keep it.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {action === 'activate' && otherActive.length > 0 && (
            <FormField label={`${others} ${otherActive.length === 1 ? 'is' : 'are'} Active`}>
              <div className="flex flex-col gap-2">
                <CheckRow checked={earlier === 'supersede'} onChange={(on) => setEarlier(on ? 'supersede' : 'keep')}
                          label={`Retire ${others}`} description="Superseded: only this version is searched" />
                <CheckRow checked={earlier === 'keep'} onChange={(on) => setEarlier(on ? 'keep' : 'supersede')}
                          label={`Keep ${others} Active too`} description="Both are searched, e.g. while a line still runs the old way" />
              </div>
            </FormField>
          )}
          <FormField label="Reason" error={problem?.forField('reason')}>
            <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
                      placeholder={action === 'activate' ? 'e.g. Approved by the QA lead' : 'e.g. Under review after an audit finding'} />
          </FormField>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Back
          </Button>
          <Button type="button" size="sm" disabled={busy || !reason.trim()}
                  className={cn(action === 'suspend' && 'bg-critical-solid hover:bg-critical-solid/90')} onClick={() => void submit()}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />} {action === 'activate' ? 'Activate' : 'Suspend'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
