import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  onSave: null as null | (() => Promise<boolean>),
  onSync: null as null | (() => void),
  success: vi.fn(),
  fetchTransactions: vi.fn(),
  fetchAnalytics: vi.fn(),
}))

vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  return {
    ...actual,
    useState: (initial: unknown) => initial === ''
      ? ['ledger', vi.fn()]
      : Reflect.apply(actual.useState, actual, [initial]),
  }
})

vi.mock('@beecount/api-client', () => ({
  createTransaction: vi.fn(async () => undefined),
  deleteTransaction: vi.fn(async () => undefined),
  fetchWorkspaceAccounts: vi.fn(async () => []),
  fetchWorkspaceAnalytics: state.fetchAnalytics,
  fetchWorkspaceCategories: vi.fn(async () => []),
  fetchWorkspaceTags: vi.fn(async () => []),
  fetchWorkspaceTransactions: state.fetchTransactions,
  updateTransaction: vi.fn(async () => undefined),
}))

vi.mock('@beecount/ui', () => {
  const Wrapper = ({ children }: { children?: React.ReactNode }) => children ?? null
  return {
    Button: Wrapper,
    Card: Wrapper,
    CardContent: Wrapper,
    CardHeader: Wrapper,
    CardTitle: Wrapper,
    Input: Wrapper,
    Pagination: Wrapper,
    Select: Wrapper,
    SelectContent: Wrapper,
    SelectItem: Wrapper,
    SelectTrigger: Wrapper,
    SelectValue: Wrapper,
    useT: () => (key: string) => key,
    useToast: () => ({ error: vi.fn(), success: state.success }),
  }
})

vi.mock('@beecount/web-features', () => ({
  AccountMultiSelect: () => null,
  CategoryMultiSelect: () => null,
  TransactionForm: (props: { onSave: () => Promise<boolean> }) => {
    state.onSave = props.onSave
    return null
  },
  TransactionTable: () => null,
  buildTxPayload: () => ({}),
  canWriteTransactions: () => true,
  groupAccountPickerOptions: () => [],
  isCustomDateFilter: () => false,
  loadRatesToBase: vi.fn(async () => ({})),
  naturalMonthDateRange: () => ({ dateFrom: '2026-09-01', dateTo: '2026-09-30' }),
  openNativePicker: vi.fn(),
  quickAddFormAfterSave: (form: unknown) => form,
  resolveCurrencyFields: vi.fn(async () => null),
  txDefaults: () => ({
    editingId: null,
    tx_type: 'expense',
    amount: '1',
    account_name: 'Cash',
    category_name: 'Food',
  }),
  validateTxForm: () => null,
}))

vi.mock('./app/useLedgerWrite', () => ({
  useLedgerWrite: () => ({ retryOnConflict: async (_ledgerId: string, write: (base: number) => Promise<unknown>) => write(0) }),
}))
vi.mock('./context/AuthContext', () => ({ useAuth: () => ({ token: 'token' }) }))
vi.mock('./context/LedgersContext', () => ({
  useLedgers: () => ({
    activeLedgerId: 'ledger',
    ledgers: [{ ledger_id: 'ledger', ledger_name: 'Ledger', currency: 'CNY', role: 'owner' }],
  }),
}))
vi.mock('./context/SyncSocketContext', () => ({
  useSyncRefresh: (handler: () => void) => { state.onSync = handler },
}))
vi.mock('./i18n/errors', () => ({ localizeError: () => 'error' }))
vi.mock('./lib/txDialogEvents', () => ({ dispatchOpenDetailTx: vi.fn() }))

import { QuickAddPage } from './pages/sections/QuickAddPage'

describe('QuickAddPage write refresh', () => {
  beforeEach(() => {
    state.onSave = null
    state.onSync = null
    state.success.mockClear()
    state.fetchTransactions.mockReset()
    state.fetchAnalytics.mockReset()
    state.fetchAnalytics.mockResolvedValue({ series: [] })
    state.fetchTransactions.mockResolvedValue({
      items: [],
      total: 0,
      summary: { income_total: 0, expense_total: 0, balance: 0 },
    })
  })

  it('does not let a sync refresh cancel and finish a save refresh early', async () => {
    let resolveTransactions!: (value: unknown) => void
    state.fetchTransactions.mockImplementation((_token: string, options: { signal?: AbortSignal }) => new Promise((resolve, reject) => {
      resolveTransactions = resolve
      options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    renderToStaticMarkup(<QuickAddPage />)

    const save = state.onSave!()
    await vi.waitFor(() => expect(state.fetchTransactions).toHaveBeenCalledTimes(1))
    state.onSync!()
    await Promise.resolve()

    expect(state.fetchTransactions).toHaveBeenCalledTimes(1)
    expect(state.success).not.toHaveBeenCalled()

    resolveTransactions({
      items: [],
      total: 0,
      summary: { income_total: 0, expense_total: 0, balance: 0 },
    })
    await expect(save).resolves.toBe(true)
    expect(state.success).toHaveBeenCalledTimes(1)
  })

  it('passes the default transfer inclusion option to year analytics', async () => {
    renderToStaticMarkup(<QuickAddPage />)
    state.onSync!()
    await vi.waitFor(() => expect(state.fetchAnalytics).toHaveBeenCalledTimes(1))
    // SSR covers request-option forwarding; it does not simulate a live checkbox interaction.
    expect(state.fetchAnalytics.mock.calls[0][1]).toMatchObject({ includeTransfers: false })
  })
})
