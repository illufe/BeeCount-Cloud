import { describe, expect, it, vi } from 'vitest'

import { naturalMonthDateRange, quickAddFormAfterSave, txDefaults } from '@beecount/web-features'

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
})
