import { CheckCircle2, Loader2, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

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
import { ApiProblem } from '@/services/http'
import { configApi } from '@/services/configApi'
import type { RulesOverview, RulesVersion } from '@/types/configApi'

import { FormField } from '../FormParts'
import { ProblemLine } from '../VersionDialogs'
import { asProblem } from '../versionUtils'

/** Which SKUs a version would let the engine monitor, shown before activating it. */
export function RulesReadiness({ number }: { number: number }) {
  const [version, setVersion] = useState<RulesVersion | null>(null)

  useEffect(() => {
    configApi
      .rulesVersion(number)
      .then(setVersion)
      .catch(() => setVersion(null))
  }, [number])

  if (!version) return null
  const skus = Object.entries(version.readiness)
  const ready = skus.filter(([, gaps]) => gaps.length === 0).length
  return (
    <div className="border-line rounded-md border px-3 py-2 text-[13px]">
      <p className="text-ink font-medium">
        SKUs ready under v{number}: {ready} of {skus.length}
      </p>
      {skus.length === 0 ? (
        <p className="text-ink-soft text-[12px]">
          No SKUs in the list yet. Whatever the machine runs is unconfigured, so monitoring pauses (OPC-08).
        </p>
      ) : (
        <ul className="mt-1 flex flex-col gap-0.5 text-[12px]">
          {skus.map(([code, gaps]) => (
            <li key={code} className="flex items-center gap-1.5">
              {gaps.length === 0 ? (
                <CheckCircle2 className="text-normal size-3.5" aria-hidden />
              ) : (
                <TriangleAlert className="text-warning size-3.5" aria-hidden />
              )}
              <span className="font-mono">{code}</span>
              <span className="text-ink-soft">{gaps.length === 0 ? 'ready' : `${gaps.length} zone(s) incomplete: monitoring pauses on it`}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Add a SKU (code as the machine publishes it) or rename one. */
export function SkuDialog({
  sku,
  onClose,
  onSaved,
}: {
  sku: { code: string; name: string } | null
  onClose: () => void
  onSaved: (overview: RulesOverview) => void
}) {
  const [code, setCode] = useState(sku?.code ?? '')
  const [name, setName] = useState(sku?.name ?? '')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<ApiProblem | null>(null)

  const submit = async () => {
    setBusy(true)
    setProblem(null)
    try {
      onSaved(sku ? await configApi.renameSku(sku.code, name, reason) : await configApi.addSku(code.trim(), name, reason))
    } catch (caught) {
      setProblem(asProblem(caught))
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{sku ? `Rename SKU ${sku.code}` : 'Add a SKU'}</DialogTitle>
          <DialogDescription>
            {sku
              ? 'The code stays as the machine publishes it; only the name changes.'
              : 'Use the code exactly as the machine will publish it in its SKU field (O-15). Then give it targets in a rules version.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          {!sku && (
            <FormField label="SKU code" error={problem?.forField('code')} hint="Letters, digits, . _ / -; up to 40">
              <Input value={code} onChange={(e) => setCode(e.target.value)} className="h-8 font-mono text-[13px]" aria-label="SKU code" />
            </FormField>
          )}
          <FormField label="Name" error={problem?.forField('name')}>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Mayonnaise 30 ml sachet"
              className="h-8 text-[13px]"
              aria-label="SKU name"
            />
          </FormField>
          <FormField label="Reason" hint="Optional; kept in the change history">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} className="h-8 text-[13px]" aria-label="Reason" />
          </FormField>
          <ProblemLine problem={problem} />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" size="sm" disabled={busy} onClick={() => void submit()}>
            {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {sku ? 'Rename' : 'Add SKU'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
