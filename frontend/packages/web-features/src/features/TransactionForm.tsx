import { useMemo, useState, type ReactNode } from 'react'

import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useT,
} from '@beecount/ui'
import type { ReadAccount, ReadCategory, ReadTag, WorkspaceCategory } from '@beecount/api-client'

import { AccountDropdown } from '../components/AccountDropdown'
import { CategoryDropdown } from '../components/CategoryDropdown'
import { CurrencySelectorTrigger } from '../components/CurrencySelector'
import { TagPickerDialog } from '../components/TagPickerDialog'
import type { TxForm } from '../forms'
import { groupAccountPickerOptions } from '../lib/accountGroups'
import { openNativePicker } from '../lib/datePicker'
import { tagTextColorOn } from '../lib/tagColorPalette'

export type TransactionFormProps = {
  form: TxForm
  baseCurrency?: string
  currencyRates?: Record<string, number>
  accounts: readonly ReadAccount[]
  categories: readonly ReadCategory[]
  tags: readonly ReadTag[]
  ledgerOptions: Array<{ ledger_id: string; ledger_name: string }>
  writeLedgerId: string
  onWriteLedgerIdChange: (ledgerId: string) => void
  canWrite: boolean
  dictionariesLoading?: boolean
  onFormChange: (next: TxForm) => void
  onSave: () => Promise<boolean> | boolean
  onReset: () => void
  iconPreviewUrlByFileId?: Record<string, string>
  /** Dialog 由 TransactionsPanel 自己提供 footer；inline 页面显示自己的操作区。 */
  showActions?: boolean
  /** 内联宽幅页面（如 记一笔 quick-add）使用更密的横向布局；dialog 保持默认。 */
  compact?: boolean
  /** 是否显示标签编辑；QuickAdd 明确隐藏，旧交易/全局编辑 dialog 保持显示。 */
  showTags?: boolean
}

export function TransactionForm({
  form,
  baseCurrency = 'CNY',
  currencyRates,
  accounts,
  categories,
  tags,
  ledgerOptions,
  writeLedgerId,
  onWriteLedgerIdChange,
  canWrite,
  dictionariesLoading = false,
  onFormChange,
  onSave,
  onReset,
  iconPreviewUrlByFileId,
  showActions = true,
  compact = false,
  showTags = true,
}: TransactionFormProps) {
  const t = useT()
  const isTransfer = form.tx_type === 'transfer'
  const [tagPickerOpen, setTagPickerOpen] = useState(false)
  const tagColorByName = useMemo(() => {
    const colors = new Map<string, string>()
    for (const tag of tags) {
      const name = tag.name.trim().toLowerCase()
      if (name && tag.color && !colors.has(name)) colors.set(name, tag.color)
    }
    return colors
  }, [tags])

  // 按账户类型分组(现金/银行卡/信用卡/支付宝/微信/投资/保险/贷款/不动产/其他),
  // 复用资产页"类型分组"的心智模型,避免账户平铺成一长串难找。
  const groupedAccountOptions = useMemo(
    () => groupAccountPickerOptions(
      t,
      accounts,
      {
        pinned: new Set(
          [form.account_name, form.from_account_name, form.to_account_name]
            .map((name) => name.trim())
            .filter(Boolean),
        ),
      },
    ),
    [accounts, form.account_name, form.from_account_name, form.to_account_name, t],
  )

  const selectedCategoryRow = useMemo<WorkspaceCategory | null>(() => {
    const name = form.category_name.trim().toLowerCase()
    if (!name) return null
    return (
      (categories as readonly WorkspaceCategory[]).find(
        (row) => row.kind === form.tx_type && row.name.trim().toLowerCase() === name,
      ) ?? null
    )
  }, [categories, form.category_name, form.tx_type])

  // 币种跟随账户(账户已绑定唯一币种)。实收/实付以所选账户币种为准;未选账户时退回账本本位币。
  const effectiveCurrency = useMemo(() => {
    const name = form.account_name.trim()
    if (name) {
      const row = (accounts as readonly ReadAccount[]).find((a) => a.name.trim() === name)
      if (row?.currency) return row.currency.toUpperCase()
    }
    return (baseCurrency || 'CNY').toUpperCase()
  }, [accounts, form.account_name, baseCurrency])

  const canSubmit = Boolean(writeLedgerId.trim()) &&
    (!isTransfer || (Boolean(form.from_account_name.trim()) && Boolean(form.to_account_name.trim())))

  const applyTxType = (nextType: TxForm['tx_type']) => {
    if (nextType === 'transfer') {
      onFormChange({
        ...form,
        tx_type: nextType,
        account_name: '',
        currency: '',
        category_name: '',
        category_kind: 'transfer',
        exclude_from_stats: false,
        exclude_from_budget: false,
      })
      return
    }
    onFormChange({
      ...form,
      tx_type: nextType,
      category_kind: nextType,
      category_name: form.category_kind === nextType ? form.category_name : '',
      from_account_name: '',
      to_account_name: '',
      exclude_from_budget: nextType === 'expense' ? form.exclude_from_budget : false,
    })
  }

  // 标签编辑字段:compact(快速记账)下独占一整行,不占用 4 列网格的横向单元格;
  // dialog 保持普通单元格。QuickAdd 传 showTags=false 时不渲染。
  const tagsField = showTags ? (
    <div className={compact ? 'col-span-full space-y-1' : 'space-y-1'}>
      <Label>{t('tags.title')}</Label>
      <button
        type="button"
        disabled={dictionariesLoading}
        onClick={() => setTagPickerOpen(true)}
        className="flex h-10 w-full items-center gap-2 rounded-md border border-input bg-muted px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="flex flex-1 items-center gap-1 overflow-hidden">
          {form.tags.length === 0 ? (
            <span className="text-muted-foreground">{t('common.none')}</span>
          ) : (
            <span className="flex flex-wrap items-center gap-1 overflow-hidden">
              {form.tags.slice(0, 3).map((name) => {
                const color = tagColorByName.get(name.trim().toLowerCase()) || '#94a3b8'
                return (
                  <span
                    key={name}
                    className="inline-flex h-5 max-w-[120px] items-center rounded-full px-1.5 text-[11px] leading-none"
                    style={{ background: color, color: tagTextColorOn(color) }}
                    title={name}
                  >
                    <span className="truncate">{name}</span>
                  </span>
                )
              })}
              {form.tags.length > 3 ? (
                <span className="text-[11px] text-muted-foreground">+{form.tags.length - 3}</span>
              ) : null}
            </span>
          )}
        </span>
        <span className="text-xs text-muted-foreground opacity-60">▾</span>
      </button>
    </div>
  ) : null

  return (
    <>
      <div className={compact ? 'grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4' : 'grid gap-3 md:grid-cols-2'}>
      {!compact ? (
        <div className="space-y-1">
          <Label>{t('shell.ledger')}</Label>
          <Select
            value={writeLedgerId || undefined}
            onValueChange={onWriteLedgerIdChange}
            disabled={Boolean(form.editingId)}
          >
            <SelectTrigger><SelectValue placeholder={t('shell.ledger')} /></SelectTrigger>
            <SelectContent>
              {ledgerOptions.map((ledger) => (
                <SelectItem key={ledger.ledger_id} value={ledger.ledger_id}>
                  {ledger.ledger_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      {compact ? (
        <>
          {/* 第一行:类型 / 分类(转账→从账户+到账户)/ 账户 / 金额。
              横向单元格:label 在左、控件在右,lg 4 列正好占满一行。 */}
          <InlineField label={t('transactions.table.type')}>
            <Select value={form.tx_type} onValueChange={(value) => applyTxType(value as TxForm['tx_type'])}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="expense">{t('enum.txType.expense')}</SelectItem>
                <SelectItem value="income">{t('enum.txType.income')}</SelectItem>
                <SelectItem value="transfer">{t('enum.txType.transfer')}</SelectItem>
              </SelectContent>
            </Select>
          </InlineField>

          {/* 转账无分类:隐藏该字段(isTransfer 时 category 恒为空),避免紧凑网格
              第一行变成"类型/分类(禁用)/从账户/到账户/金额"5 项把金额挤到单独一行。
              隐藏后恰好 4 项:"类型/从账户/到账户/金额" 占满第一行,恢复两行布局。 */}
          {!isTransfer ? (
            <InlineField label={t('transactions.table.category')}>
              <CategoryDropdown
                kind={form.tx_type === 'income' ? 'income' : 'expense'}
                rows={categories as readonly WorkspaceCategory[]}
                selected={selectedCategoryRow}
                dictionariesLoading={dictionariesLoading}
                iconPreviewUrlByFileId={iconPreviewUrlByFileId}
                placeholder={t('transactions.placeholder.categoryName')}
                onSelect={(category) => onFormChange({
                  ...form,
                  category_name: category.name.trim(),
                  category_kind: form.tx_type,
                })}
              />
            </InlineField>
          ) : null}

          {isTransfer ? (
            <>
              <AccountDropdown
                inline
                label={t('transactions.placeholder.fromAccountName')}
                value={form.from_account_name}
                groups={groupedAccountOptions}
                disabled={dictionariesLoading}
                onSelect={(value) => onFormChange({ ...form, from_account_name: value })}
              />
              <AccountDropdown
                inline
                label={t('transactions.placeholder.toAccountName')}
                value={form.to_account_name}
                groups={groupedAccountOptions}
                disabled={dictionariesLoading}
                onSelect={(value) => onFormChange({ ...form, to_account_name: value })}
              />
            </>
          ) : (
            <AccountDropdown
              inline
              label={t('transactions.table.account')}
              value={form.account_name}
              groups={groupedAccountOptions}
              disabled={dictionariesLoading}
              allowNone
              placeholder={t('transactions.placeholder.noAccount')}
              onSelect={(value) => onFormChange({ ...form, account_name: value })}
            />
          )}

          <InlineField label={t('transactions.table.amount')}>
            {!isTransfer ? (
              <div className="flex items-center gap-1.5">
                <Input
                  className="min-w-0 flex-1"
                  placeholder={t('transactions.placeholder.amount')}
                  value={form.amount}
                  onChange={(event) => onFormChange({ ...form, amount: event.target.value })}
                />
                <span
                  className="shrink-0 rounded-md border border-input bg-muted/60 px-2 py-1 text-xs font-medium text-muted-foreground"
                  title={t('transactions.currencyFromAccount')}
                >
                  {effectiveCurrency}
                </span>
              </div>
            ) : (
              <Input
                placeholder={t('transactions.placeholder.amount')}
                value={form.amount}
                onChange={(event) => onFormChange({ ...form, amount: event.target.value })}
              />
            )}
          </InlineField>

          {tagsField}

          {/* 第二行:时间 / 备注 / 开关 chips / 操作按钮 */}
          <InlineField label={t('transactions.table.time')}>
            <Input
              type="datetime-local"
              step={60}
              onClick={openNativePicker}
              value={isoToDatetimeLocal(form.happened_at)}
              onChange={(event) => onFormChange({
                ...form,
                happened_at: datetimeLocalToIso(event.target.value, form.happened_at),
              })}
            />
          </InlineField>
          <InlineField label={t('transactions.table.note')}>
            <Input
              placeholder={t('transactions.placeholder.note')}
              value={form.note}
              onChange={(event) => onFormChange({ ...form, note: event.target.value })}
            />
          </InlineField>
          <div className="flex items-center gap-1.5">
            {!isTransfer ? (
              <SwitchChip
                label={t('txFlagExcludeFromStats')}
                checked={form.exclude_from_stats}
                onChange={() => onFormChange({ ...form, exclude_from_stats: !form.exclude_from_stats })}
              />
            ) : null}
            {form.tx_type === 'expense' ? (
              <SwitchChip
                label={t('txFlagExcludeFromBudget')}
                checked={form.exclude_from_budget}
                onChange={() => onFormChange({ ...form, exclude_from_budget: !form.exclude_from_budget })}
              />
            ) : null}
          </div>
          {showActions ? (
            <div className="flex items-center justify-end gap-2">
              <Button variant="outline" size="sm" onClick={onReset}>{t('transactions.button.reset')}</Button>
              <Button size="sm" disabled={!canWrite || !canSubmit} onClick={() => void onSave()}>
                {form.editingId ? t('transactions.button.update') : t('transactions.button.create')}
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <>
          <div className="space-y-1">
            <Label>{t('transactions.table.type')}</Label>
            <Select value={form.tx_type} onValueChange={(value) => applyTxType(value as TxForm['tx_type'])}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="expense">{t('enum.txType.expense')}</SelectItem>
                <SelectItem value="income">{t('enum.txType.income')}</SelectItem>
                <SelectItem value="transfer">{t('enum.txType.transfer')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {!isTransfer ? (
            <div className="space-y-1">
              <Label>{t('transactions.table.category')}</Label>
              <CategoryDropdown
                kind={form.tx_type === 'income' ? 'income' : 'expense'}
                rows={categories as readonly WorkspaceCategory[]}
                selected={selectedCategoryRow}
                dictionariesLoading={dictionariesLoading}
                iconPreviewUrlByFileId={iconPreviewUrlByFileId}
                placeholder={t('transactions.placeholder.categoryName')}
                onSelect={(category) => onFormChange({
                  ...form,
                  category_name: category.name.trim(),
                  category_kind: form.tx_type,
                })}
              />
            </div>
          ) : null}

          {isTransfer ? (
            <>
              <AccountDropdown
                label={t('transactions.placeholder.fromAccountName')}
                value={form.from_account_name}
                groups={groupedAccountOptions}
                disabled={dictionariesLoading}
                onSelect={(value) => onFormChange({ ...form, from_account_name: value })}
              />
              <AccountDropdown
                label={t('transactions.placeholder.toAccountName')}
                value={form.to_account_name}
                groups={groupedAccountOptions}
                disabled={dictionariesLoading}
                onSelect={(value) => onFormChange({ ...form, to_account_name: value })}
              />
            </>
          ) : (
            <AccountDropdown
              label={t('transactions.table.account')}
              value={form.account_name}
              groups={groupedAccountOptions}
              disabled={dictionariesLoading}
              allowNone
              placeholder={t('transactions.placeholder.noAccount')}
              onSelect={(value) => onFormChange({ ...form, account_name: value })}
            />
          )}

          <div className="space-y-1">
            <Label>{t('transactions.table.amount')}</Label>
            <>
              <Input
                placeholder={t('transactions.placeholder.amount')}
                value={form.amount}
                onChange={(event) => onFormChange({ ...form, amount: event.target.value })}
              />
              {!isTransfer ? (
                <CurrencySelectorTrigger
                  value={form.currency || baseCurrency}
                  onChange={(code) => onFormChange({
                    ...form,
                    currency: code.toUpperCase() === baseCurrency.toUpperCase() ? '' : code,
                    account_name: '',
                  })}
                  ratesToBase={currencyRates}
                  rateBase={baseCurrency}
                />
              ) : null}
            </>
          </div>

          {tagsField}

          <div className="space-y-1">
            <Label>{t('transactions.table.time')}</Label>
            <Input
              type="datetime-local"
              step={60}
              onClick={openNativePicker}
              value={isoToDatetimeLocal(form.happened_at)}
              onChange={(event) => onFormChange({
                ...form,
                happened_at: datetimeLocalToIso(event.target.value, form.happened_at),
              })}
            />
          </div>
          <div className="space-y-1 md:col-span-2">
            <Label>{t('transactions.table.note')}</Label>
            <Input
              placeholder={t('transactions.placeholder.note')}
              value={form.note}
              onChange={(event) => onFormChange({ ...form, note: event.target.value })}
            />
          </div>
          {!isTransfer ? (
            <SwitchRow
              label={t('txFlagExcludeFromStats')}
              checked={form.exclude_from_stats}
              compact={compact}
              onChange={() => onFormChange({ ...form, exclude_from_stats: !form.exclude_from_stats })}
            />
          ) : null}
          {form.tx_type === 'expense' ? (
            <SwitchRow
              label={t('txFlagExcludeFromBudget')}
              checked={form.exclude_from_budget}
              compact={compact}
              onChange={() => onFormChange({ ...form, exclude_from_budget: !form.exclude_from_budget })}
            />
          ) : null}
          {showActions ? (
            <div className="mt-4 flex justify-end gap-2 md:col-span-2">
              <Button variant="outline" onClick={onReset}>{t('transactions.button.reset')}</Button>
              <Button disabled={!canWrite || !canSubmit} onClick={() => void onSave()}>
                {form.editingId ? t('transactions.button.update') : t('transactions.button.create')}
              </Button>
            </div>
          ) : null}
        </>
      )}
      </div>
      {showTags ? (
        <TagPickerDialog
          open={tagPickerOpen}
          onClose={() => setTagPickerOpen(false)}
          tags={tags}
          selectedNames={form.tags}
          onChange={(names) => onFormChange({ ...form, tags: names })}
          onClearAll={() => onFormChange({ ...form, tags: [] })}
        />
      ) : null}
    </>
  )
}

/**
 * compact(快速记账)表单的横向单元格:label 在左、控件在右,整格高度只占一行,
 * 让 4 列网格把表单压到两行。label 用灰小字 + whitespace-nowrap 避免换行;
 * 控件用 min-w-0 flex-1 自适应剩余宽度。
 */
function InlineField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <Label className="shrink-0 whitespace-nowrap text-xs font-medium text-muted-foreground">{label}</Label>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function SwitchRow({ label, checked, onChange, compact = false }: { label: string; checked: boolean; onChange: () => void; compact?: boolean }) {
  return (
    <div className={`flex items-center justify-between rounded-lg border border-border/60 bg-muted/20 px-3 py-2${compact ? '' : ' md:col-span-2'}`}>
      <p className="text-sm font-medium">{label}</p>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={onChange}
        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors ${checked ? 'bg-primary' : 'bg-muted-foreground/30'}`}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
      </button>
    </div>
  )
}

/** 紧凑的开关 chip(内联表单底部使用),相比 SwitchRow 大幅减少占位。 */
function SwitchChip({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${checked ? 'border-primary/50 bg-primary/10 text-primary' : 'border-border/60 bg-muted/20 text-muted-foreground'}`}
    >
      <span className={`h-2 w-2 shrink-0 rounded-full ${checked ? 'bg-primary' : 'bg-muted-foreground/40'}`} />
      {label}
    </button>
  )
}

function isoToDatetimeLocal(iso: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function datetimeLocalToIso(local: string, fallback: string): string {
  if (!local) return fallback
  const date = new Date(local)
  return Number.isNaN(date.getTime()) ? fallback : date.toISOString()
}
