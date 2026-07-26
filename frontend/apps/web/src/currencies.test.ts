import { describe, expect, it } from 'vitest'

import {
  CURRENCY_CODES,
  currencyDisplayName,
  currencySymbol,
  gramsToXau,
  xauToGrams,
} from '@beecount/web-features'

describe('currencies', () => {
  it('CURRENCY_CODES 覆盖全部 + 含 issue#273 请求的 KES/XAF/XOF', () => {
    expect(CURRENCY_CODES.length).toBe(152)
    expect(CURRENCY_CODES).toEqual(
      expect.arrayContaining(['KES', 'XAF', 'XOF', 'XAU', 'CNY', 'USD', 'EUR', 'JPY']),
    )
  })

  it('code 无重复', () => {
    expect(new Set(CURRENCY_CODES).size).toBe(CURRENCY_CODES.length)
  })

  it('currencyDisplayName 用 Intl 本地化,大小写不敏感,未知 code 回退自身', () => {
    expect(currencyDisplayName('USD', 'en')).toBe('US Dollar')
    expect(currencyDisplayName('KES', 'en')).toBe('Kenyan Shilling')
    expect(currencyDisplayName('usd', 'en')).toBe('US Dollar')
    expect(currencyDisplayName('ZZZ', 'en')).toBe('ZZZ')
  })

  it('中文 locale 返回本地化名', () => {
    expect(currencyDisplayName('USD', 'zh-CN')).toBe('美元')
  })

  it('XAU has an explicit symbol and no country flag', () => {
    expect(currencySymbol('XAU')).toBe('XAU')
  })

  it('XAU uses troy-ounce native unit', () => {
    expect(xauToGrams(gramsToXau(80))).toBeCloseTo(80, 8)
    expect(xauToGrams(1)).toBeCloseTo(31.1034768, 8)
  })
})
