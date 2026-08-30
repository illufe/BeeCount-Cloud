import type { ReadAccount } from '@beecount/api-client'

export type AccountGroup = { type: string; label: string; accounts: ReadAccount[] }

/** 账户分组展示顺序:可交易/常用类型在前,估值类型靠后。与资产页分组心智一致。 */
export const ACCOUNT_PICKER_ORDER = [
  'cash', 'bank_card', 'credit_card', 'alipay', 'wechat',
  'investment', 'insurance', 'loan', 'real_estate', 'vehicle', 'other',
]

/** 账户类型 → 名称 i18n label。 */
export function accountTypeLabel(t: (k: string) => string, value?: string | null): string {
  if (!value) return '-'
  const key = `accountType.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}

/**
 * 按账户类型分组(现金/银行卡/信用卡/支付宝/微信/投资/保险/贷款/不动产/其他),
 * 供账户下拉(表单与筛选栏)统一使用,避免平铺成一长串难找。
 * - `pinned`:即使隐藏也保留的账户名(表单里"选中的当前账户")。
 * - `includeHidden`:是否包含隐藏账户(筛选栏需要能筛到历史交易引用的账户)。
 */
export function groupAccountPickerOptions(
  t: (k: string) => string,
  accounts: readonly ReadAccount[],
  opts?: { pinned?: Set<string>; includeHidden?: boolean },
): AccountGroup[] {
  const pinned = opts?.pinned ?? new Set<string>()
  const includeHidden = opts?.includeHidden ?? false
  const visible: ReadAccount[] = []
  const seenName = new Set<string>()
  for (const row of accounts) {
    if (!includeHidden && row.hidden && !pinned.has(row.name.trim())) continue
    const name = row.name.trim()
    if (!name || seenName.has(name)) continue
    seenName.add(name)
    visible.push(row)
  }
  const buckets: Record<string, ReadAccount[]> = {}
  for (const row of visible) {
    const key = row.account_type || 'other'
    buckets[key] = buckets[key] || []
    buckets[key].push(row)
  }
  const types = [...new Set([...ACCOUNT_PICKER_ORDER.filter((ty) => buckets[ty]), ...Object.keys(buckets)])]
  return types.map((type) => ({
    type,
    label: accountTypeLabel(t, type),
    accounts: buckets[type].slice().sort((a, b) => (a.name || '').localeCompare(b.name || '')),
  }))
}
