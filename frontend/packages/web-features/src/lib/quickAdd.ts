import type { TxForm } from '../forms'

export type DateRange = { dateFrom: string; dateTo: string }

function dateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function naturalMonthDateRange(bucket: string): DateRange | null {
  const match = /^(\d{4})-(\d{2})$/.exec(bucket)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  if (month < 1 || month > 12) return null
  return {
    dateFrom: dateKey(new Date(year, month - 1, 1)),
    dateTo: dateKey(new Date(year, month, 0)),
  }
}

export function quickAddFormAfterSave(form: TxForm): TxForm {
  const next = {
    ...form,
    editingId: null,
    editingOwnerUserId: '',
    amount: '',
    note: '',
    happened_at: form.happened_at,
    attachments: [],
  }
  if (form.tx_type === 'transfer') {
    return {
      ...next,
      category_name: '',
      category_kind: 'transfer',
      account_name: '',
      currency: '',
    }
  }
  return {
    ...next,
    from_account_name: '',
    to_account_name: '',
    category_kind: form.tx_type,
  }
}
