import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Pagination,
  useT,
} from '@beecount/ui'
import type { AttachmentRef, ReadAccount, ReadCategory, ReadTag, ReadTransaction } from '@beecount/api-client'

import { TransactionForm } from './TransactionForm'
import { TransactionList } from '../components/TransactionList'
import type { TxForm } from '../forms'

export type TransactionsPanelProps = {
  form: TxForm
  baseCurrency?: string
  currencyRates?: Record<string, number>
  rows: ReadTransaction[]
  total: number
  page: number
  pageSize: number
  accounts: ReadAccount[]
  categories: ReadCategory[]
  tags: ReadTag[]
  ledgerOptions: Array<{ ledger_id: string; ledger_name: string }>
  writeLedgerId: string
  onWriteLedgerIdChange: (ledgerId: string) => void
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
  canWrite: boolean
  dictionariesLoading?: boolean
  showCreatorColumn?: boolean
  showLedgerColumn?: boolean
  onFormChange: (next: TxForm) => void
  dialogOpen: boolean
  onDialogOpenChange: (open: boolean) => void
  onSave: () => Promise<boolean> | boolean
  onReset: () => void
  onReload: () => void
  onPreviewAttachment: (refs: AttachmentRef[], startIndex: number) => Promise<void>
  resolveAttachmentPreviewUrl: (ref: AttachmentRef) => Promise<string | null>
  iconPreviewUrlByFileId?: Record<string, string>
  onEdit: (row: ReadTransaction) => void
  onDelete: (row: ReadTransaction) => void
  onSelect?: (row: ReadTransaction) => void
  dialogOnlyMode?: boolean
  selectionMode?: boolean
  selectedIds?: Set<string>
  onToggleSelect?: (row: ReadTransaction, event: React.MouseEvent) => void
  showCreator?: boolean
  currentUserId?: string | null
  noteDisplayMode?: 'category' | 'note'
}

export function TransactionsPanel({
  form,
  baseCurrency,
  currencyRates,
  rows,
  total,
  page,
  pageSize,
  accounts,
  categories,
  tags,
  ledgerOptions,
  writeLedgerId,
  onWriteLedgerIdChange,
  onPageChange,
  onPageSizeChange,
  canWrite,
  dictionariesLoading = false,
  onFormChange,
  dialogOpen,
  onDialogOpenChange,
  onSave,
  onReset,
  onReload: _onReload,
  onPreviewAttachment,
  resolveAttachmentPreviewUrl,
  iconPreviewUrlByFileId,
  onEdit,
  onDelete,
  onSelect,
  dialogOnlyMode = false,
  selectionMode = false,
  selectedIds,
  onToggleSelect,
  showCreator = false,
  currentUserId,
  noteDisplayMode = 'category',
}: TransactionsPanelProps) {
  const t = useT()
  return (
    <>
      {!dialogOnlyMode ? (
        <div className="rounded-xl border border-border/50 bg-card">
          <TransactionList
            items={rows}
            tags={tags}
            categories={categories}
            iconPreviewUrlByFileId={iconPreviewUrlByFileId}
            variant="default"
            showCreator={showCreator}
            currentUserId={currentUserId}
            noteDisplayMode={noteDisplayMode}
            canManage={canWrite}
            onEdit={(row) => {
              onEdit(row)
              onDialogOpenChange(true)
            }}
            onDelete={onDelete}
            onSelect={onSelect}
            onPreviewAttachment={onPreviewAttachment}
            resolveAttachmentPreviewUrl={resolveAttachmentPreviewUrl}
            selectionMode={selectionMode}
            selectedIds={selectedIds}
            onToggleSelect={onToggleSelect}
          />
          <Pagination
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={onPageChange}
            onPageSizeChange={onPageSizeChange}
          />
        </div>
      ) : null}

      <Dialog open={dialogOpen} onOpenChange={onDialogOpenChange}>
        <DialogContent className="flex max-h-[85vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
          <DialogHeader className="border-b border-border/60 px-6 py-4">
            <DialogTitle>{form.editingId ? t('transactions.button.update') : t('transactions.button.create')}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <TransactionForm
              form={form}
              baseCurrency={baseCurrency}
              currencyRates={currencyRates}
              accounts={accounts}
              categories={categories}
              tags={tags}
              ledgerOptions={ledgerOptions}
              writeLedgerId={writeLedgerId}
              onWriteLedgerIdChange={onWriteLedgerIdChange}
              canWrite={canWrite}
              dictionariesLoading={dictionariesLoading}
              onFormChange={onFormChange}
              onSave={onSave}
              onReset={onReset}
              iconPreviewUrlByFileId={iconPreviewUrlByFileId}
              showActions={false}
            />
          </div>
          <DialogFooter className="shrink-0 border-t border-border/60 bg-card px-6 py-4">
            <Button
              variant="outline"
              onClick={() => {
                onReset()
                onDialogOpenChange(false)
              }}
            >
              {t('dialog.cancel')}
            </Button>
            <Button
              disabled={!canWrite || !writeLedgerId.trim() || (form.tx_type === 'transfer' && (!form.from_account_name.trim() || !form.to_account_name.trim()))}
              onClick={async () => {
                if (await onSave()) onDialogOpenChange(false)
              }}
            >
              {form.editingId ? t('transactions.button.update') : t('transactions.button.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
