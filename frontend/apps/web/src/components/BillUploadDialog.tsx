import { useState } from 'react'

import { uploadBill, type ReadAccount } from '@beecount/api-client'
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  useT,
} from '@beecount/ui'

import { localizeError } from '../i18n/errors'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  account: ReadAccount | null
  ledgerId: string | null
  token: string
}

export function BillUploadDialog({ open, onOpenChange, account, ledgerId, token }: Props) {
  const t = useT()
  const [file, setFile] = useState<File | null>(null)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  const reset = () => {
    setFile(null)
    setPending(false)
    setMessage(null)
    setFailed(false)
  }

  const handleOpenChange = (next: boolean) => {
    if (!next && pending) return
    if (!next && !pending) reset()
    onOpenChange(next)
  }

  const submit = async () => {
    if (!file || !ledgerId || !account || pending) {
      setFailed(true)
      setMessage(t(!ledgerId ? 'accounts.bill.ledgerRequired' : 'accounts.bill.fileRequired'))
      return
    }
    setPending(true)
    setFailed(false)
    setMessage(null)
    try {
      await uploadBill(token, { ledgerId, accountId: account.id, file })
      setMessage(t('accounts.bill.success'))
    } catch (error) {
      setFailed(true)
      setMessage(localizeError(error, t))
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('accounts.bill.title')}</DialogTitle>
          <DialogDescription>
            {t('accounts.bill.description', { account: account?.name || '' })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="bill-upload-file">{t('accounts.bill.file')}</Label>
          <input
            id="bill-upload-file"
            type="file"
            accept=".pdf,.csv,.tsv,.xlsx"
            disabled={pending}
            onChange={(event) => {
              setFile(event.target.files?.[0] || null)
              setMessage(null)
              setFailed(false)
            }}
            className="block w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <p className="text-xs text-muted-foreground">{t('accounts.bill.formats')}</p>
          {message ? (
            <p className={`text-sm ${failed ? 'text-destructive' : 'text-muted-foreground'}`}>
              {message}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => handleOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button disabled={pending} onClick={() => void submit()}>
            {pending ? t('accounts.bill.uploading') : t('accounts.bill.upload')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
