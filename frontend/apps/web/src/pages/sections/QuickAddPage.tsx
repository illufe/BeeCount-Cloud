import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  fetchWorkspaceAccounts,
  fetchWorkspaceAnalytics,
  fetchWorkspaceCategories,
  fetchWorkspaceTags,
  fetchWorkspaceTransactions,
  createTransaction,
  deleteTransaction,
  updateTransaction,
  type WorkspaceAccount,
  type WorkspaceAnalytics,
  type WorkspaceCategory,
  type WorkspaceTag,
  type WorkspaceTransaction,
  type ReadTransaction,
} from '@beecount/api-client'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Pagination,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useT,
  useToast,
} from '@beecount/ui'
import {
  AccountMultiSelect,
  CategoryMultiSelect,
  TransactionForm,
  TransactionTable,
  buildTxPayload,
  canWriteTransactions,
  groupAccountPickerOptions,
  isCustomDateFilter,
  loadRatesToBase,
  naturalMonthDateRange,
  openNativePicker,
  quickAddFormAfterSave,
  resolveCurrencyFields,
  txDefaults,
  validateTxForm,
  type TxForm,
} from '@beecount/web-features'

import { useLedgerWrite } from '../../app/useLedgerWrite'
import { useAuth } from '../../context/AuthContext'
import { useLedgers } from '../../context/LedgersContext'
import { useSyncRefresh } from '../../context/SyncSocketContext'
import { localizeError } from '../../i18n/errors'
import { dispatchOpenDetailTx } from '../../lib/txDialogEvents'

type QuickAddFilter = {
  q: string
  txType: '' | 'expense' | 'income' | 'transfer'
  categorySyncId: string[]
  categoryName: string[]
  accountSyncId: string[]
  amountMin: string
  amountMax: string
  dateFrom: string
  dateTo: string
}

const PAGE_SIZE_DEFAULT = 20

function currentMonthKey(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function defaultFilter(): QuickAddFilter {
  return {
    q: '',
    txType: '',
    categorySyncId: [],
    categoryName: [],
    accountSyncId: [],
    amountMin: '',
    amountMax: '',
    dateFrom: '',
    dateTo: '',
  }
}

function formatAmount(value: number, fixed = false): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: fixed ? 2 : 0,
    maximumFractionDigits: 2,
  })
}

function initialFilter(): QuickAddFilter {
  const month = currentMonthKey()
  return { ...defaultFilter(), ...(naturalMonthDateRange(month) || {}) }
}

function dateToIso(value: string, exclusive = false): string | undefined {
  if (!value) return undefined
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return undefined
  if (exclusive) date.setDate(date.getDate() + 1)
  return date.toISOString()
}

function rowToForm(row: WorkspaceTransaction, baseCurrency: string): TxForm {
  const currency = (row.currency_code || '').toUpperCase()
  const base = baseCurrency.toUpperCase()
  return {
    ...txDefaults(),
    editingId: row.id,
    editingOwnerUserId: row.created_by_user_id || '',
    tx_type: row.tx_type,
    amount: String(row.amount),
    happened_at: row.happened_at,
    note: row.note || '',
    category_name: row.category_name || '',
    category_kind: (row.category_kind as TxForm['category_kind']) || 'expense',
    account_name: row.account_name || '',
    from_account_name: row.from_account_name || '',
    to_account_name: row.to_account_name || '',
    currency: currency === base ? '' : currency,
    original_currency: currency === base ? '' : currency,
    tags: row.tags_list?.length
      ? row.tags_list
      : (row.tags || '').split(',').map((tag) => tag.trim()).filter(Boolean),
    attachments: Array.isArray(row.attachments) ? row.attachments : [],
    exclude_from_stats: Boolean(row.exclude_from_stats),
    exclude_from_budget: Boolean(row.exclude_from_budget),
  }
}

export function QuickAddPage() {
  const t = useT()
  const toast = useToast()
  const { token } = useAuth()
  const { ledgers, activeLedgerId } = useLedgers()
  const { retryOnConflict } = useLedgerWrite()
  const [writeLedgerId, setWriteLedgerId] = useState('')
  const [form, setForm] = useState<TxForm>(txDefaults)
  const [accounts, setAccounts] = useState<WorkspaceAccount[]>([])
  const [categories, setCategories] = useState<WorkspaceCategory[]>([])
  const [tags, setTags] = useState<WorkspaceTag[]>([])
  const [currencyRates, setCurrencyRates] = useState<Record<string, number>>({})
  const [rows, setRows] = useState<WorkspaceTransaction[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState({ income_total: 0, expense_total: 0, balance: 0 })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT)
  const [filter, setFilter] = useState<QuickAddFilter>(initialFilter)
  const [appliedFilter, setAppliedFilter] = useState<QuickAddFilter>(initialFilter)
  const [selectedMonth, setSelectedMonth] = useState(currentMonthKey)
  const [displayYear, setDisplayYear] = useState(new Date().getFullYear())
  const [yearData, setYearData] = useState<WorkspaceAnalytics | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const transactionsRequestRef = useRef(0)
  const yearRequestRef = useRef(0)

  const writableLedgers = useMemo(
    () => ledgers.filter((ledger) => canWriteTransactions(ledger.role)),
    [ledgers],
  )
  const activeWritableLedger = useMemo(
    () => writableLedgers.find((ledger) => ledger.ledger_id === activeLedgerId) || null,
    [activeLedgerId, writableLedgers],
  )
  const ledgerOptions = useMemo(
    () => activeWritableLedger ? [{ ledger_id: activeWritableLedger.ledger_id, ledger_name: activeWritableLedger.ledger_name }] : [],
    [activeWritableLedger],
  )
  const ledgerCurrency = useMemo(
    () => (activeWritableLedger?.currency || 'CNY').toUpperCase(),
    [activeWritableLedger],
  )
  // 筛选栏分类:与类型联动。income/expense 只显示对应方向;全部 按方向分组展示(支出/收入两组);转账 隐藏分类筛选。
  const filterCategoryKind = filter.txType === 'income' ? 'income' : filter.txType === 'expense' ? 'expense' : 'all'

  // 分类 id → 展示名(子分类带父级前缀),用于多选触发文案回填。
  const categoryLabelById = useMemo(() => {
    const map = new Map<string, string>()
    for (const row of categories) {
      const parent = (row.parent_name || '').trim()
      map.set(row.id, parent ? `${parent} / ${row.name}` : row.name)
    }
    return map
  }, [categories])

  // 筛选栏分类:随手记式两级目录(左右两栏) + 多选,见 CategoryMultiSelect。
  // 筛选栏账户:随手记式两级目录(左=账户类型,右=账户) + 多选,见 AccountMultiSelect。
  // 筛选栏只展示可见账户，历史交易仍可通过其它条件查询。
  const filterAccountGroups = useMemo(
    () => groupAccountPickerOptions(t, accounts),
    [accounts, t],
  )
  const filterIsCustomDate = useMemo(
    () => isCustomDateFilter(appliedFilter, selectedMonth),
    [appliedFilter, selectedMonth],
  )

  const loadTransactions = useCallback(async () => {
    const requestId = ++transactionsRequestRef.current
    if (!token || !activeLedgerId) {
      setRows([])
      setTotal(0)
      setSummary({ income_total: 0, expense_total: 0, balance: 0 })
      return
    }
    setLoading(true)
    try {
      const min = Number(appliedFilter.amountMin)
      const max = Number(appliedFilter.amountMax)
      const result = await fetchWorkspaceTransactions(token, {
        ledgerId: activeLedgerId,
        q: appliedFilter.q || undefined,
        txType: appliedFilter.txType || undefined,
        accountSyncId: appliedFilter.accountSyncId.length ? appliedFilter.accountSyncId : undefined,
        categorySyncId: appliedFilter.categorySyncId.length ? appliedFilter.categorySyncId : undefined,
        amountMin: appliedFilter.amountMin && Number.isFinite(min) ? min : undefined,
        amountMax: appliedFilter.amountMax && Number.isFinite(max) ? max : undefined,
        dateFrom: dateToIso(appliedFilter.dateFrom),
        dateTo: dateToIso(appliedFilter.dateTo, true),
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      if (requestId !== transactionsRequestRef.current) return
      setRows(result.items)
      setTotal(result.total)
      setSummary(result.summary)
    } catch (error) {
      if (requestId !== transactionsRequestRef.current) return
      toast.error(localizeError(error, t), t('notice.failed'))
    } finally {
      if (requestId === transactionsRequestRef.current) setLoading(false)
    }
  }, [activeLedgerId, appliedFilter, page, pageSize, token, t, toast])

  const loadYear = useCallback(async () => {
    const requestId = ++yearRequestRef.current
    if (!token || !activeLedgerId) return
    try {
      const result = await fetchWorkspaceAnalytics(token, {
        scope: 'year',
        metric: 'expense',
        period: String(displayYear),
        ledgerId: activeLedgerId,
        tzOffsetMinutes: -new Date().getTimezoneOffset(),
        naturalMonth: true,
      })
      if (requestId !== yearRequestRef.current) return
      setYearData(result)
    } catch (error) {
      if (requestId !== yearRequestRef.current) return
      toast.error(localizeError(error, t), t('notice.failed'))
    }
  }, [activeLedgerId, displayYear, t, toast, token])

  useEffect(() => {
    setForm(txDefaults())
    setAccounts([])
    setCategories([])
    setTags([])
    setCurrencyRates({})
    setRows([])
    setTotal(0)
    setSummary({ income_total: 0, expense_total: 0, balance: 0 })
    setYearData(null)
    setLoading(false)
    if (!token || !activeLedgerId) return

    let cancelled = false
    void Promise.all([
      fetchWorkspaceAccounts(token, { ledgerId: activeLedgerId, limit: 500 }),
      fetchWorkspaceCategories(token, { ledgerId: activeLedgerId, limit: 500 }),
      fetchWorkspaceTags(token, { ledgerId: activeLedgerId, limit: 500 }),
    ]).then(([accountRows, categoryRows, tagRows]) => {
      if (cancelled) return
      setAccounts(accountRows)
      setCategories(categoryRows)
      setTags(tagRows)
    })
    return () => { cancelled = true }
  }, [activeLedgerId, token])

  useEffect(() => {
    setWriteLedgerId(activeWritableLedger?.ledger_id || '')
  }, [activeWritableLedger?.ledger_id])

  useEffect(() => { void loadTransactions() }, [loadTransactions])
  useEffect(() => { void loadYear() }, [loadYear])
  useSyncRefresh(() => {
    void loadTransactions()
    void loadYear()
  })

  useEffect(() => {
    if (!token) return
    let cancelled = false
    void loadRatesToBase(token, ledgerCurrency)
      .then((rates) => { if (!cancelled) setCurrencyRates(rates) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [ledgerCurrency, token])

  const updateFilter = <K extends keyof QuickAddFilter>(key: K, value: QuickAddFilter[K]) => {
    setFilter((current) => {
      if (key === 'txType' && value && current.categorySyncId.length) {
        return { ...current, txType: value as QuickAddFilter['txType'], categorySyncId: [], categoryName: [] }
      }
      return { ...current, [key]: value }
    })
  }

  const applyFilter = () => {
    setPage(1)
    setAppliedFilter(filter)
  }

  const resetFilter = () => {
    const next = defaultFilter()
    setFilter(next)
    setAppliedFilter(next)
    setPage(1)
    setSelectedMonth('')
  }

  const chooseMonth = (month: string) => {
    const range = naturalMonthDateRange(month)
    if (!range) return
    setSelectedMonth(month)
    const next = { ...filter, dateFrom: range.dateFrom, dateTo: range.dateTo }
    setFilter(next)
    setAppliedFilter(next)
    setPage(1)
  }

  const onSave = async (): Promise<boolean> => {
    if (!writeLedgerId.trim()) {
      toast.error(t('transactions.error.ledgerRequired'), t('notice.failed'))
      return false
    }
    const validationError = validateTxForm(form)
    if (validationError) {
      const messageByError = {
        amountInvalid: 'transactions.error.amountInvalid',
        categoryRequired: 'transactions.error.categoryRequired',
        transferAccountsRequired: 'transactions.error.transferAccountsRequired',
        transferAccountsDifferent: 'transactions.error.transferAccountsDifferent',
      } as const
      toast.error(t(messageByError[validationError]), t('notice.failed'))
      return false
    }
    setSaving(true)
    try {
      const accountByName = new Map(accounts.filter((row) => row.name.trim()).map((row) => [row.name.trim().toLowerCase(), row.id] as const))
      const categoryByKey = new Map(categories.filter((row) => row.name.trim()).map((row) => [`${row.kind}:${row.name.trim().toLowerCase()}`, row.id] as const))
      const tagByName = new Map(tags.filter((row) => row.name.trim()).map((row) => [row.name.trim().toLowerCase(), row.id] as const))
      let currencyFields: { currency_code?: string; native_amount?: number } = {}
      if (form.tx_type !== 'transfer') {
        const accountCurrency = accounts.find((row) => row.name.trim() === form.account_name.trim())?.currency
        const effectiveCurrency = (form.currency || accountCurrency || ledgerCurrency).toUpperCase()
        const resolved = await resolveCurrencyFields({
          token,
          ledgerBase: ledgerCurrency,
          currency: effectiveCurrency,
          amount: Number(form.amount.trim()),
          originalCurrency: form.editingId ? form.original_currency : undefined,
        })
        if (resolved) currencyFields = resolved
      }
      const payload = buildTxPayload(form, { accountByName, categoryByKey, tagByName }, currencyFields)
      await retryOnConflict(writeLedgerId, (base) => form.editingId
        ? updateTransaction(token, writeLedgerId, form.editingId, base, payload)
        : createTransaction(token, writeLedgerId, base, payload))
      const wasEditing = Boolean(form.editingId)
      setForm(quickAddFormAfterSave(form))
      await Promise.all([loadTransactions(), loadYear()])
      toast.success(wasEditing ? t('notice.txUpdated') : t('notice.txCreated'), t('notice.success'))
      return true
    } catch (error) {
      toast.error(localizeError(error, t), t('notice.failed'))
      return false
    } finally {
      setSaving(false)
    }
  }

  const onEdit = (row: ReadTransaction) => {
    const workspaceRow = rows.find((item) => item.id === row.id)
    if (!workspaceRow) return
    setWriteLedgerId(workspaceRow.ledger_id || writeLedgerId)
    setForm(rowToForm(workspaceRow, ledgerCurrency))
    // 表单面板已 sticky 钉在视口顶部,无需再自动回滚页面顶部。
  }

  const onCopy = (row: ReadTransaction) => {
    const workspaceRow = rows.find((item) => item.id === row.id)
    if (!workspaceRow) return
    setWriteLedgerId(workspaceRow.ledger_id || writeLedgerId)
    const next = rowToForm(workspaceRow, ledgerCurrency)
    setForm({ ...next, editingId: null, editingOwnerUserId: '' })
  }

  const onDelete = async (row: ReadTransaction) => {
    if (!row.ledger_id) return
    if (!window.confirm(t('dialog.delete.confirm'))) return
    try {
      await retryOnConflict(row.ledger_id, (base) => deleteTransaction(token, row.ledger_id!, row.id, base))
      await loadTransactions()
      toast.success(t('notice.txDeleted'), t('notice.success'))
    } catch (error) {
      toast.error(localizeError(error, t), t('notice.failed'))
    }
  }

  const monthSeries = new Map((yearData?.series || []).map((item) => [item.bucket, item]))

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[240px_minmax(0,1fr)]">
        <div className="space-y-4 xl:sticky xl:top-[84px] xl:self-start">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{t('quickAdd.title')}</h1>
            <p className="mt-0.5 text-xs text-muted-foreground">{t('quickAdd.description')}</p>
          </div>

          <Card className="h-fit">
            <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
              <CardTitle className="text-base">{displayYear}</CardTitle>
              <span className="flex gap-1">
                <Button variant="outline" size="sm" aria-label={t('quickAdd.previousYear')} onClick={() => setDisplayYear((year) => year - 1)}>‹</Button>
                <Button variant="outline" size="sm" aria-label={t('quickAdd.nextYear')} onClick={() => setDisplayYear((year) => year + 1)}>›</Button>
              </span>
            </CardHeader>
            <CardContent className="space-y-1">
              {Array.from({ length: 12 }, (_, i) => 11 - i).map((index) => {
                const month = `${displayYear}-${String(index + 1).padStart(2, '0')}`
                const item = monthSeries.get(month)
                const selected = selectedMonth === month && !filterIsCustomDate
                return (
                  <button
                    key={month}
                    type="button"
                    onClick={() => chooseMonth(month)}
                    className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm ${selected ? 'bg-primary/10 text-primary' : 'hover:bg-accent/50'}`}
                  >
                    <span className="shrink-0">{index + 1}{t('quickAdd.month')}</span>
                    <span className="flex min-w-0 shrink flex-col items-end text-[11px] leading-tight">
                      <span className="tabular-nums text-income">
                        {t('quickAdd.incomeShort')} {formatAmount(item?.income || 0)}
                      </span>
                      <span className="tabular-nums text-expense">
                        {t('quickAdd.expenseShort')} {formatAmount(item?.expense || 0)}
                      </span>
                    </span>
                  </button>
                )
              })}
            </CardContent>
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          {/* 快速记账面板钉在视口顶部:列表里点 编辑/复制 后表单始终可见,无需回滚。
              bg-card 为不透明背景 + z-10,下方筛选/汇总/列表滚动经过时不会透出。 */}
          <Card className="sticky top-[84px] z-10">
            <CardContent className="pt-5">
              <TransactionForm
                form={form}
                baseCurrency={ledgerCurrency}
                currencyRates={currencyRates}
                accounts={accounts}
                categories={categories}
                tags={tags}
                ledgerOptions={ledgerOptions}
                writeLedgerId={writeLedgerId}
                onWriteLedgerIdChange={setWriteLedgerId}
                canWrite={Boolean(activeWritableLedger) && !saving}
                dictionariesLoading={accounts.length === 0 && categories.length === 0 && tags.length === 0}
                compact
                showTags={false}
                onFormChange={setForm}
                onSave={onSave}
                onReset={() => setForm(txDefaults())}
              />
              {saving ? <p className="mt-2 text-xs text-muted-foreground">{t('txList.loading')}</p> : null}
            </CardContent>
          </Card>

        <Card>
          <CardHeader className="py-3"><CardTitle className="text-base">{t('shell.filter.title')}</CardTitle></CardHeader>
          <CardContent className="pb-3">
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">{t('transactions.table.type')}</span>
                <Select value={filter.txType || '__all__'} onValueChange={(value) => updateFilter('txType', value === '__all__' ? '' : value as QuickAddFilter['txType'])}>
                  <SelectTrigger className="h-9 w-[110px]"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__all__">{t('shell.filter.all')}</SelectItem>
                    <SelectItem value="expense">{t('enum.txType.expense')}</SelectItem>
                    <SelectItem value="income">{t('enum.txType.income')}</SelectItem>
                    <SelectItem value="transfer">{t('enum.txType.transfer')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {filter.txType !== 'transfer' ? (
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-medium text-muted-foreground">{t('shell.filter.category')}</span>
                  <CategoryMultiSelect
                    placeholder={t('shell.filter.all')}
                    kind={filterCategoryKind}
                    rows={categories}
                    selected={filter.categorySyncId}
                    onChange={(values) => setFilter((current) => ({
                      ...current,
                      categorySyncId: values,
                      categoryName: values.map((value) => categoryLabelById.get(value) || value),
                    }))}
                    allowClear
                    onClear={() => setFilter((current) => ({ ...current, categorySyncId: [], categoryName: [] }))}
                    triggerClassName="w-[200px]"
                    title={t('shell.filter.category')}
                    incomeLabel={t('enum.txType.income')}
                    expenseLabel={t('enum.txType.expense')}
                  />
                </div>
              ) : null}
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">{t('shell.accountFilter')}</span>
                <AccountMultiSelect
                  placeholder={t('shell.filter.all')}
                  groups={filterAccountGroups}
                  selected={filter.accountSyncId}
                  onChange={(values) => setFilter((current) => ({ ...current, accountSyncId: values }))}
                  allowClear
                  onClear={() => setFilter((current) => ({ ...current, accountSyncId: [] }))}
                  triggerClassName="w-[170px]"
                  title={t('shell.accountFilter')}
                />
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">{t('shell.filter.amount')}</span>
                <Input type="number" className="h-9 w-[78px]" value={filter.amountMin} onChange={(event) => updateFilter('amountMin', event.target.value)} />
                <span className="text-muted-foreground">-</span>
                <Input type="number" className="h-9 w-[78px]" value={filter.amountMax} onChange={(event) => updateFilter('amountMax', event.target.value)} />
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">{t('shell.filter.date')}</span>
                {/* 点击控件任意位置即弹出原生日期选择器(与记账表单时间控件一致) */}
                <Input type="date" className="h-9 w-[126px]" value={filter.dateFrom} onClick={openNativePicker} onChange={(event) => updateFilter('dateFrom', event.target.value)} />
                <span className="text-muted-foreground">~</span>
                <Input type="date" className="h-9 w-[126px]" value={filter.dateTo} onClick={openNativePicker} onChange={(event) => updateFilter('dateTo', event.target.value)} />
              </div>
              <Input placeholder={t('shell.placeholder.keyword')} className="h-9 w-[150px] min-w-[120px]" value={filter.q} onChange={(event) => updateFilter('q', event.target.value)} />
              <Button size="sm" onClick={applyFilter}>{t('shell.filter.apply')}</Button>
              <Button size="sm" variant="outline" onClick={resetFilter}>{t('shell.filter.reset')}</Button>
              {filterIsCustomDate ? <span className="text-xs text-muted-foreground">{t('quickAdd.customDate')}</span> : null}
            </div>
          </CardContent>
        </Card>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border border-border/60 bg-muted/20 px-4 py-2">
            <SummaryItem label={t('quickAdd.income')} value={summary.income_total} />
            <SummaryItem label={t('quickAdd.expense')} value={summary.expense_total} />
            <SummaryItem label={t('quickAdd.balance')} value={summary.balance} />
          </div>

          <Card>
            <CardHeader><CardTitle className="text-base">{t('quickAdd.list')}</CardTitle></CardHeader>
            <CardContent className="p-0">
              <TransactionTable
                items={rows}
                categories={categories}
                canManage={Boolean(activeWritableLedger)}
                onEdit={onEdit}
                onCopy={onCopy}
                onDelete={onDelete}
                loading={loading}
                onSelect={(row) => dispatchOpenDetailTx(row as WorkspaceTransaction)}
              />
              <Pagination
                page={page}
                pageSize={pageSize}
                total={total}
                onPageChange={setPage}
                onPageSizeChange={(size) => { setPageSize(size); setPage(1) }}
              />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function SummaryItem({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-base font-semibold tabular-nums">{formatAmount(value, true)}</span>
    </div>
  )
}
