import { describe, expect, it, vi } from 'vitest'

import {
  isCustomDateFilter,
  naturalMonthDateRange,
  quickAddFormAfterAccountSelection,
  quickAddFormAfterSave,
  transactionTableAmount,
  txDefaults,
} from '@beecount/web-features'

describe('quick add helpers', () => {
  it('creates an inclusive natural month range including leap day', () => {
    expect(naturalMonthDateRange('2024-02')).toEqual({
      dateFrom: '2024-02-01',
      dateTo: '2024-02-29',
    })
  })

  it('rejects invalid month buckets', () => {
    expect(naturalMonthDateRange('2024-13')).toBeNull()
    expect(naturalMonthDateRange('2024-2')).toBeNull()
  })

  it('marks incomplete or non-month dates as custom, including without a selected month', () => {
    expect(isCustomDateFilter({ dateFrom: '2024-02-01', dateTo: '2024-02-29' }, '2024-02')).toBe(false)
    expect(isCustomDateFilter({ dateFrom: '', dateTo: '2024-02-29' }, '2024-02')).toBe(true)
    expect(isCustomDateFilter({ dateFrom: '2024-02-01', dateTo: '' }, '2024-02')).toBe(true)
    expect(isCustomDateFilter({ dateFrom: '2024-02-01', dateTo: '2024-02-29' }, '')).toBe(true)
    expect(isCustomDateFilter({ dateFrom: '', dateTo: '' }, '')).toBe(false)
  })

  it('follows a changed compact account while preserving edit currency baseline', () => {
    const form = {
      ...txDefaults(),
      editingId: 'tx-1',
      account_name: 'USD account',
      currency: 'USD',
      original_currency: 'USD',
    }
    const next = quickAddFormAfterAccountSelection(form, 'CNY account')
    expect(next.account_name).toBe('CNY account')
    expect(next.currency).toBe('')
    expect(next.original_currency).toBe('USD')
  })

  it('clears copied currency metadata on a changed account and leaves transfers alone', () => {
    const copied = quickAddFormAfterAccountSelection({
      ...txDefaults(),
      account_name: 'USD account',
      currency: 'USD',
      original_currency: 'USD',
    }, 'CNY account')
    expect(copied.currency).toBe('')
    expect(copied.original_currency).toBe('')

    const transfer = quickAddFormAfterAccountSelection({
      ...txDefaults(),
      tx_type: 'transfer',
      account_name: 'USD account',
      currency: 'USD',
      original_currency: 'USD',
    }, 'CNY account')
    expect(transfer.currency).toBe('USD')
    expect(transfer.original_currency).toBe('USD')
  })

  it('keeps normal entry selections and clears transient fields after save', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-30T12:00:01.000Z'))
    const form = {
      ...txDefaults(),
      tx_type: 'expense' as const,
      amount: '12.5',
      happened_at: '2026-08-30T11:00:00.000Z',
      note: 'lunch',
      category_name: '餐饮',
      category_kind: 'expense' as const,
      account_name: '现金',
      currency: 'USD',
      tags: ['工作'],
    }
    const next = quickAddFormAfterSave(form)
    expect(next.editingId).toBeNull()
    expect(next.amount).toBe('')
    expect(next.note).toBe('')
    expect(next.tx_type).toBe('expense')
    expect(next.category_name).toBe('餐饮')
    expect(next.account_name).toBe('现金')
    expect(next.currency).toBe('USD')
    expect(next.tags).toEqual(['工作'])
    expect(next.happened_at).toBe(form.happened_at)
    vi.useRealTimers()
  })

  it('keeps transfer accounts but clears transfer-only category and currency', () => {
    const form = {
      ...txDefaults(),
      tx_type: 'transfer' as const,
      amount: '100',
      note: 'move',
      from_account_name: '现金',
      to_account_name: '银行卡',
      category_name: '错误分类',
      currency: 'USD',
    }
    const next = quickAddFormAfterSave(form)
    expect(next.amount).toBe('')
    expect(next.note).toBe('')
    expect(next.from_account_name).toBe('现金')
    expect(next.to_account_name).toBe('银行卡')
    expect(next.category_name).toBe('')
    expect(next.currency).toBe('')
  })

  it('uses included native amounts for transaction table totals', () => {
    expect(transactionTableAmount({ amount: 100, native_amount: 86.4, exclude_from_stats: false })).toBe(86.4)
    expect(transactionTableAmount({ amount: 100, native_amount: 86.4, exclude_from_stats: true })).toBe(0)
    expect(transactionTableAmount({ amount: 100, native_amount: null, exclude_from_stats: false })).toBe(100)
  })
})
