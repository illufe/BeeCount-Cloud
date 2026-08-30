import type { TxPayload } from '@beecount/api-client'

import type { TxForm } from '../forms'

export type TxValidationError =
  | 'amountInvalid'
  | 'categoryRequired'
  | 'transferAccountsRequired'
  | 'transferAccountsDifferent'

export function validateTxForm(form: TxForm): TxValidationError | null {
  const amount = Number(form.amount.trim())
  if (!Number.isFinite(amount) || amount <= 0) return 'amountInvalid'
  if (form.tx_type !== 'transfer' && !form.category_name.trim()) {
    return 'categoryRequired'
  }
  if (form.tx_type === 'transfer') {
    if (!form.from_account_name.trim() || !form.to_account_name.trim()) {
      return 'transferAccountsRequired'
    }
    if (form.from_account_name.trim() === form.to_account_name.trim()) {
      return 'transferAccountsDifferent'
    }
  }
  return null
}

type TransactionIdMaps = {
  accountByName: ReadonlyMap<string, string>
  categoryByKey: ReadonlyMap<string, string>
  tagByName: ReadonlyMap<string, string>
}

export function buildTxPayload(
  form: TxForm,
  maps: TransactionIdMaps,
  currencyFields: Pick<TxPayload, 'currency_code' | 'native_amount'> = {},
): TxPayload {
  const isTransfer = form.tx_type === 'transfer'
  const accountName = form.account_name.trim()
  const fromAccountName = form.from_account_name.trim()
  const toAccountName = form.to_account_name.trim()
  const categoryName = form.category_name.trim()
  const categoryKind = form.category_kind
  const tagIds = form.tags
    .map((value) => maps.tagByName.get(value.trim().toLowerCase()))
    .filter((value): value is string => Boolean(value))

  return {
    tx_type: form.tx_type,
    amount: Number(form.amount.trim()),
    happened_at: form.happened_at || new Date().toISOString(),
    note: form.note.trim() || null,
    category_name: isTransfer ? null : categoryName || null,
    category_kind: isTransfer ? null : categoryKind,
    category_id: isTransfer
      ? null
      : maps.categoryByKey.get(`${categoryKind}:${categoryName.toLowerCase()}`) || null,
    account_name: isTransfer ? null : accountName || null,
    account_id: isTransfer
      ? null
      : maps.accountByName.get(accountName.toLowerCase()) || null,
    from_account_name: isTransfer ? fromAccountName || null : null,
    from_account_id: isTransfer
      ? maps.accountByName.get(fromAccountName.toLowerCase()) || null
      : null,
    to_account_name: isTransfer ? toAccountName || null : null,
    to_account_id: isTransfer
      ? maps.accountByName.get(toAccountName.toLowerCase()) || null
      : null,
    tags: form.tags.length > 0 ? form.tags : null,
    tag_ids: tagIds.length > 0 ? tagIds : null,
    attachments: form.attachments.length > 0 ? form.attachments : null,
    exclude_from_stats: isTransfer ? false : form.exclude_from_stats,
    exclude_from_budget: form.tx_type === 'expense' ? form.exclude_from_budget : false,
    ...currencyFields,
  }
}
