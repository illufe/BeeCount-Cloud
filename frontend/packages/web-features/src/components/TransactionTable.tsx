import { Fragment, useMemo } from 'react'

import type { AttachmentRef, ReadCategory, ReadTransaction } from '@beecount/api-client'
import { EmptyState, useLocale, useT } from '@beecount/ui'

import { currencySymbol } from '../lib/currencies'
import { composeTransactionRowTitle, type NoteDisplayMode } from '../lib/transactionRowTitle'
import { CategoryIcon } from './CategoryIcon'
import { CreatorEditorChip } from './TransactionRow'

export type TransactionTableProps = {
  items: ReadTransaction[]
  /** 分类列表:用于在行首渲染分类图标。不传 → 不显示图标。 */
  categories?: ReadCategory[]
  /** 自定义分类图标的预签预览 URL 字典(`icon_cloud_file_id → blob URL`)。 */
  iconPreviewUrlByFileId?: Record<string, string>
  loading?: boolean
  canManage?: boolean
  onEdit?: (row: ReadTransaction) => void
  onDelete?: (row: ReadTransaction) => void
  onCopy?: (row: ReadTransaction) => void
  onPreviewAttachment?: (refs: AttachmentRef[], startIndex: number) => Promise<void>
  /** 行整体点击 → 打开详情弹窗。编辑/复制/删除/附件均 stopPropagation。 */
  onSelect?: (row: ReadTransaction) => void
  /** 批量选择模式 —— 行首渲染 checkbox，点行切换选中。 */
  selectionMode?: boolean
  /** 已选 sync_id 集合(selectionMode=true 时生效)。 */
  selectedIds?: Set<string>
  /** 切换选中。event 透传给上层判断 shift / meta。row.id 是 sync_id。 */
  onToggleSelect?: (row: ReadTransaction, event: React.MouseEvent) => void
  /** §7 共享账本:为 true 时每行渲染"谁记的"头像 chip。默认 false。 */
  showCreator?: boolean
  /** §7 共享账本:当前 caller user_id，用来过滤"自己创建+编辑"的 tx。 */
  currentUserId?: string | null
  /** 跨账本场景显示账本名 chip。透传到行内。 */
  showLedger?: boolean
  /** 备注显示方式,默认 'category'。 */
  noteDisplayMode?: NoteDisplayMode
  emptyTitle?: string
  emptyDescription?: string
}

type DayGroup = {
  key: string
  date: Date
  label: string
  rows: ReadTransaction[]
  income: number
  expense: number
}

export function transactionTableAmount(row: Pick<ReadTransaction, 'amount' | 'native_amount' | 'exclude_from_stats'>): number {
  return row.exclude_from_stats ? 0 : row.native_amount ?? row.amount
}

/**
 * 随手记「流水」式交易表 —— 列式(非卡片)、按本地日期分组、一行一笔。
 *
 * 与 TransactionList / TransactionRow 的卡片布局并存:本组件只被 记一笔
 * (QuickAddPage)工作台使用,不改变 dialog / TransactionsPanel 的卡片渲染。
 * 行为与 TransactionRow 对齐:
 *  - 行点击 → onSelect(详情);编辑/复制/删除/附件按钮 stopPropagation;
 *  - 批量选择 checkbox(selectionMode)、hover 操作列(canManage 控制禁用);
 *  - 分类图标、📎 附件 chip、创建人头像、账本名 chip;
 *  - 外币交易:币种符号 + ≈ 本位币;不计收支 / 不计预算 小灰字标签。
 * 分组头显示本地日期(如「2026-07-14 周二」)+ 当日 收/支 小计。
 */
export function TransactionTable({
  items,
  categories,
  iconPreviewUrlByFileId,
  loading = false,
  canManage = true,
  onEdit,
  onDelete,
  onCopy,
  onPreviewAttachment,
  onSelect,
  selectionMode = false,
  selectedIds,
  onToggleSelect,
  showCreator = false,
  currentUserId,
  showLedger = false,
  noteDisplayMode = 'category',
  emptyTitle,
  emptyDescription,
}: TransactionTableProps) {
  const t = useT()
  const { locale } = useLocale()

  const categoryById = useMemo(() => {
    if (!categories || categories.length === 0) return undefined
    const map = new Map<string, ReadCategory>()
    for (const cat of categories) {
      if (cat.id) map.set(cat.id, cat)
    }
    return map
  }, [categories])

  // 按 happened_at 的本地日期分组;组内按时间倒序,组间按日期倒序(最新在前)。
  const groups = useMemo<DayGroup[]>(() => {
    const map = new Map<string, DayGroup>()
    for (const row of items) {
      const date = new Date(row.happened_at)
      const key = Number.isNaN(date.getTime()) ? '----' : localDateKey(date)
      let group = map.get(key)
      if (!group) {
        group = {
          key,
          date,
          label: Number.isNaN(date.getTime())
            ? '—'
            : `${key} ${date.toLocaleDateString(locale, { weekday: 'short' })}`,
          rows: [],
          income: 0,
          expense: 0,
        }
        map.set(key, group)
      }
      group.rows.push(row)
      const amount = transactionTableAmount(row)
      if (row.tx_type === 'income') group.income += amount
      else if (row.tx_type === 'expense') group.expense += amount
    }
    for (const group of map.values()) {
      group.rows.sort(
        (a, b) => new Date(b.happened_at).getTime() - new Date(a.happened_at).getTime()
      )
    }
    return [...map.values()].sort((a, b) => b.date.getTime() - a.date.getTime())
  }, [items, locale])

  const colCount = selectionMode ? 7 : 6
  const isInteractive = selectionMode || Boolean(onSelect)

  return (
    <div>
      {items.length === 0 && !loading ? (
        <EmptyState
          icon={
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
                 strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" />
              <path d="M3 10h18" />
              <path d="M8 14h4" />
            </svg>
          }
          title={emptyTitle || t('table.empty')}
          description={emptyDescription || ''}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="border-b border-border/60 bg-muted/30 text-xs text-muted-foreground">
                {selectionMode ? <th className="w-10 px-2 py-2" /> : null}
                <th className="whitespace-nowrap px-3 py-2 text-left font-medium">{t('transactions.table.time')}</th>
                <th className="whitespace-nowrap px-3 py-2 text-left font-medium">{t('transactions.table.category')}</th>
                <th className="whitespace-nowrap px-3 py-2 text-left font-medium">{t('transactions.table.account')}</th>
                <th className="whitespace-nowrap px-3 py-2 text-right font-medium">{t('transactions.table.amount')}</th>
                <th className="whitespace-nowrap px-3 py-2 text-left font-medium">{t('transactions.table.note')}</th>
                <th className="whitespace-nowrap px-3 py-2 text-right font-medium">{t('transactions.table.ops')}</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <Fragment key={group.key}>
                  {/* 日期分组头:本地日期 + 周几 + 当日 收/支 小计 */}
                  <tr className="border-b border-border/60 bg-muted/20">
                    <td colSpan={colCount} className="px-3 py-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-foreground">{group.label}</span>
                        {group.income > 0 || group.expense > 0 ? (
                          <span className="text-[11px] tabular-nums text-muted-foreground">
                            {group.income > 0 ? (
                              <span className="text-income">{t('quickAdd.incomeShort')} {formatAmountFixed(group.income)}</span>
                            ) : null}
                            {group.income > 0 && group.expense > 0 ? <span className="mx-1.5">·</span> : null}
                            {group.expense > 0 ? (
                              <span className="text-expense">{t('quickAdd.expenseShort')} {formatAmountFixed(group.expense)}</span>
                            ) : null}
                          </span>
                        ) : null}
                      </div>
                    </td>
                  </tr>

                  {group.rows.map((row) => (
                    <TransactionTableRow
                      key={row.id}
                      row={row}
                      categoryById={categoryById}
                      iconPreviewUrlByFileId={iconPreviewUrlByFileId}
                      canManage={canManage}
                      onEdit={onEdit}
                      onCopy={onCopy}
                      onDelete={onDelete}
                      onPreviewAttachment={onPreviewAttachment}
                      onSelect={onSelect}
                      selectionMode={selectionMode}
                      selected={selectedIds?.has(row.id) ?? false}
                      onToggleSelect={onToggleSelect}
                      showCreator={showCreator}
                      currentUserId={currentUserId}
                      showLedger={showLedger}
                      noteDisplayMode={noteDisplayMode}
                      isInteractive={isInteractive}
                    />
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-4 text-xs text-muted-foreground">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-muted-foreground/60 border-t-transparent" />
          <span className="ml-2">{t('txList.loading')}</span>
        </div>
      ) : null}
    </div>
  )
}

type TableRowProps = {
  row: ReadTransaction
  categoryById?: Map<string, ReadCategory>
  iconPreviewUrlByFileId?: Record<string, string>
  canManage: boolean
  onEdit?: (row: ReadTransaction) => void
  onCopy?: (row: ReadTransaction) => void
  onDelete?: (row: ReadTransaction) => void
  onPreviewAttachment?: (refs: AttachmentRef[], startIndex: number) => Promise<void>
  onSelect?: (row: ReadTransaction) => void
  selectionMode: boolean
  selected: boolean
  onToggleSelect?: (row: ReadTransaction, event: React.MouseEvent) => void
  showCreator: boolean
  currentUserId?: string | null
  showLedger: boolean
  noteDisplayMode: NoteDisplayMode
  isInteractive: boolean
}

function TransactionTableRow({
  row,
  categoryById,
  iconPreviewUrlByFileId,
  canManage,
  onEdit,
  onCopy,
  onDelete,
  onPreviewAttachment,
  onSelect,
  selectionMode,
  selected,
  onToggleSelect,
  showCreator,
  currentUserId,
  showLedger,
  noteDisplayMode,
  isInteractive,
}: TableRowProps) {
  const t = useT()
  const attachments = Array.isArray(row.attachments) ? row.attachments : []

  const amountTone = row.tx_type === 'expense' ? 'negative' : row.tx_type === 'income' ? 'positive' : 'default'
  const sign = row.tx_type === 'expense' ? '-' : row.tx_type === 'income' ? '+' : ''
  // 交易级多币种:折算快照存在且 ≠ 原币值 → 外币交易,金额旁标币种 + ≈ 折算。
  const isForeignCurrency =
    !!row.currency_code &&
    row.native_amount != null &&
    row.native_amount !== row.amount
  const categoryText = row.category_name || (row.tx_type === 'transfer' ? t('enum.txType.transfer') : '-')
  const rowTitle = composeTransactionRowTitle({
    mode: noteDisplayMode,
    categoryName: row.category_name,
    categoryText,
    note: row.note,
  })
  const accountText =
    row.tx_type === 'transfer'
      ? `${row.from_account_name || '-'} → ${row.to_account_name || '-'}`
      : row.account_name || '-'

  // 分类图标:优先按 category_id 精确匹配;匹配不到退化到按 name+kind 兜底。
  // (与 TransactionRow 保持同一查找逻辑。)
  const categoryEntry = (() => {
    if (!categoryById) return null
    const byId = row.category_id ? categoryById.get(row.category_id) : null
    if (byId) return byId
    if (!row.category_name) return null
    for (const cat of categoryById.values()) {
      if (cat.name === row.category_name && cat.kind === row.category_kind) return cat
    }
    return null
  })()

  const hasAttachments = attachments.length > 0 && Boolean(onPreviewAttachment)
  const firstAttachment = attachments[0]

  // 选择模式优先于 onSelect:点行 = 切换选中,不打开详情
  const handleRowClick = (event: React.MouseEvent<HTMLTableRowElement>) => {
    if (selectionMode && onToggleSelect) {
      onToggleSelect(row, event)
      return
    }
    if (onSelect) onSelect(row)
  }

  return (
    <tr
      onClick={isInteractive ? handleRowClick : undefined}
      role={isInteractive ? 'button' : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      onKeyDown={
        isInteractive
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                if (selectionMode && onToggleSelect) {
                  onToggleSelect(row, event as unknown as React.MouseEvent)
                } else if (onSelect) {
                  onSelect(row)
                }
              }
            }
          : undefined
      }
      className={`group border-b border-border/50 transition-colors hover:bg-accent/30 ${
        isInteractive ? 'cursor-pointer' : ''
      } ${selectionMode && selected ? 'bg-primary/8' : ''}`}
    >
      {selectionMode ? (
        <td className="px-2 py-1.5 text-center">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => undefined}
            onClick={(event) => {
              // 由父级统一处理点击 / shift / meta;阻止冒泡到行,避免双触发。
              event.stopPropagation()
              if (onToggleSelect) onToggleSelect(row, event)
            }}
            aria-label={t('common.select')}
            className="h-4 w-4 cursor-pointer accent-primary"
          />
        </td>
      ) : null}

      {/* 时间:HH:mm(完整日期在分组头) */}
      <td className="whitespace-nowrap px-3 py-1.5 font-mono tabular-nums text-xs text-muted-foreground">
        {formatTimeHM(row.happened_at)}
      </td>

      {/* 分类:图标 + 名称(转账显示"转账");跨账本时追加账本名 chip */}
      <td className="max-w-[180px] px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-1.5">
          {categoryEntry ? (
            <CategoryIcon
              icon={categoryEntry.icon}
              iconType={categoryEntry.icon_type}
              iconCloudFileId={categoryEntry.icon_cloud_file_id}
              iconPreviewUrlByFileId={iconPreviewUrlByFileId}
              size={16}
              className="shrink-0 text-muted-foreground"
            />
          ) : null}
          <span className="min-w-0 truncate text-[13px] text-muted-foreground">{rowTitle.primary}</span>
          {showLedger && row.ledger_name ? (
            <span
              className="inline-flex shrink-0 items-center rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium leading-none text-primary"
              title={row.ledger_name}
            >
              {row.ledger_name}
            </span>
          ) : null}
        </div>
      </td>

      {/* 账户:普通交易显示账户,转账显示 从 → 到 */}
      <td className="max-w-[150px] truncate px-3 py-1.5 text-[13px] text-muted-foreground">{accountText}</td>

      {/* 金额:右对齐、带符号、按收支着色;外币 + 币种符号 + ≈ 本位币 */}
      <td className="whitespace-nowrap px-3 py-1.5 text-right">
        <div className="flex flex-col items-end">
          <span className={`whitespace-nowrap font-mono tabular-nums text-[13px] font-semibold ${
            amountTone === 'positive'
              ? 'text-income'
              : amountTone === 'negative'
                ? 'text-expense'
                : 'text-foreground'
          }`}>
            {sign}
            {isForeignCurrency ? currencySymbol(row.currency_code as string) : ''}
            {formatAmountFixed(row.amount)}
          </span>
          {isForeignCurrency ? (
            <span
              className="whitespace-nowrap font-mono tabular-nums text-[11px] text-muted-foreground"
              title={t('transactions.convertedToBase')}
            >
              ≈{formatAmountFixed(row.native_amount as number)}
            </span>
          ) : null}
        </div>
      </td>

      {/* 备注:括号备注 + 📎 附件 + 不计收支/预算 小灰字 */}
      <td className="max-w-[340px] px-3 py-1.5">
        <div className="flex items-center gap-1.5">
          <span className="min-w-0 truncate text-[13px] text-muted-foreground">{rowTitle.parenNote || '-'}</span>
          {hasAttachments && firstAttachment ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                void onPreviewAttachment?.(attachments, 0)
              }}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-border/60 bg-muted/30 px-1.5 py-0.5 text-[11px] text-muted-foreground hover:border-primary/40 hover:text-primary"
              title={firstAttachment.originalName || firstAttachment.fileName || t('attachment.default')}
            >
              <span aria-hidden>📎</span>
              <span className="font-mono tabular-nums">{attachments.length}</span>
            </button>
          ) : null}
          {row.exclude_from_stats ? (
            <span className="shrink-0 whitespace-nowrap text-[10px] text-muted-foreground">· {t('txFlagExcludedTag')}</span>
          ) : null}
          {row.exclude_from_budget ? (
            <span className="shrink-0 whitespace-nowrap text-[10px] text-muted-foreground">· {t('txFlagBudgetExcludedTag')}</span>
          ) : null}
        </div>
      </td>

      {/* 操作:hover 出现 编辑/复制/删除(选择模式隐藏,避免与 checkbox 抢位) */}
      <td className="whitespace-nowrap px-3 py-1.5 text-right">
        <div className="flex items-center justify-end gap-2">
          {showCreator ? (
            <CreatorEditorChip row={row} currentUserId={currentUserId} t={t} />
          ) : null}
          {(onEdit || onCopy || onDelete) && !selectionMode ? (
            <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
              {onEdit ? (
                <button
                  type="button"
                  disabled={!canManage}
                  onClick={(event) => {
                    event.stopPropagation()
                    onEdit(row)
                  }}
                  className="rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-primary/15 hover:text-primary"
                >
                  {t('common.edit')}
                </button>
              ) : null}
              {onCopy ? (
                <button
                  type="button"
                  disabled={!canManage}
                  onClick={(event) => {
                    event.stopPropagation()
                    onCopy(row)
                  }}
                  className="rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-primary/15 hover:text-primary"
                >
                  {t('common.copy')}
                </button>
              ) : null}
              {onDelete ? (
                <button
                  type="button"
                  disabled={!canManage}
                  onClick={(event) => {
                    event.stopPropagation()
                    onDelete(row)
                  }}
                  className="rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                >
                  {t('common.delete')}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </td>
    </tr>
  )
}

function localDateKey(d: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function formatTimeHM(value: string | null | undefined): string {
  if (!value) return '--:--'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '--:--'
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatAmountFixed(value: number): string {
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}
