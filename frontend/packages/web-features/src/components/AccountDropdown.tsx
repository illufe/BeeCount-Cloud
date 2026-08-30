import { useEffect, useRef, useState } from 'react'

import { Label, useT } from '@beecount/ui'

import type { AccountGroup } from '../lib/accountGroups'

type AccountDropdownProps = {
  /** 字段标签。 */
  label: string
  /** 账户分组(account_type → 账户),来自 groupAccountPickerOptions。 */
  groups: AccountGroup[]
  /** 当前选中的账户名('' = 未选)。 */
  value: string
  disabled?: boolean
  /** 允许选"无"(清空),触发控件出现 "×"。 */
  allowNone?: boolean
  /** 未选中时的占位文案(如 "不选择账户")。 */
  placeholder?: string
  onSelect: (name: string) => void
  /** 触发控件高度:md=表单用(h-10),sm=筛选栏用(h-9)。 */
  size?: 'md' | 'sm'
  /** 横向布局:label 在左、控件在右(compact 记账表单用);默认 label 在上。 */
  inline?: boolean
}

/**
 * 记一笔表单「账户」控件 —— 随手记式两级目录(左右两栏:左=账户类型,右=当前类型
 * 的账户)。左栏点击/悬停即切换右栏(无需额外点击展开),右栏点击账户即选定并收起。
 */
export function AccountDropdown({
  label,
  groups,
  value,
  disabled = false,
  allowNone = false,
  placeholder,
  onSelect,
  size = 'md',
  inline = false,
}: AccountDropdownProps) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [activeGroupIdx, setActiveGroupIdx] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)

  const activeGroup = groups[activeGroupIdx] || null

  useEffect(() => {
    if (!open) return
    const onDocMouseDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocMouseDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  // 打开面板时,把右栏切到含所选账户的类型分组(否则看第一个类型分组)。
  useEffect(() => {
    if (!open) return
    setActiveGroupIdx((prev) => {
      if (groups.length === 0) return prev
      const selectedIdx = groups.findIndex((g) => g.accounts.some((a) => a.name.trim() === value.trim()))
      return selectedIdx >= 0 ? selectedIdx : Math.min(prev, groups.length - 1)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // 左栏"悬停意图"延时切换右栏,避免鼠标横穿时误切。
  const hoverTimerRef = useRef<number | null>(null)
  const scheduleGroup = (idx: number) => {
    if (hoverTimerRef.current) window.clearTimeout(hoverTimerRef.current)
    hoverTimerRef.current = window.setTimeout(() => setActiveGroupIdx(idx), 150)
  }
  const cancelHoverIntent = () => {
    if (hoverTimerRef.current) {
      window.clearTimeout(hoverTimerRef.current)
      hoverTimerRef.current = null
    }
  }

  const display = value.trim() || placeholder || label
  const hasValue = Boolean(value.trim())

  return (
    <div className={inline ? 'flex items-center gap-2' : 'space-y-1'}>
      <Label className={inline ? 'shrink-0 whitespace-nowrap text-xs font-medium text-muted-foreground' : undefined}>{label}</Label>
      <div ref={rootRef} className={inline ? 'relative min-w-0 flex-1' : 'relative'}>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className={`flex ${size === 'sm' ? 'h-9' : 'h-10'} w-full items-center gap-2 rounded-md border border-input bg-muted px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-50`}
        >
          <span className={`flex-1 truncate ${hasValue ? '' : 'text-muted-foreground'}`}>
            {display}
          </span>
          {allowNone && hasValue ? (
            <span
              role="button"
              tabIndex={-1}
              aria-label={label}
              onClick={(event) => {
                event.stopPropagation()
                onSelect('')
                setOpen(false)
              }}
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted-foreground/15 hover:text-foreground"
            >
              ×
            </span>
          ) : null}
          <span className="text-xs text-muted-foreground opacity-60">▾</span>
        </button>

        {open ? (
          <div className="absolute left-0 top-full z-50 mt-1 w-[320px] rounded-xl border border-border/60 bg-background p-1 shadow-lg">
            {groups.length === 0 ? (
              <p className="px-2 py-3 text-center text-sm text-muted-foreground">{placeholder || label}</p>
            ) : (
              <div className="flex max-h-72 overflow-hidden">
                <div
                  className="w-[45%] shrink-0 overflow-y-auto border-r border-border/60 pr-1"
                  onMouseLeave={cancelHoverIntent}
                >
                  {groups.map((group, idx) => {
                    const isActive = idx === activeGroupIdx
                    const hasAccounts = group.accounts.length > 0
                    return (
                      <button
                        key={group.type}
                        type="button"
                        onMouseEnter={() => scheduleGroup(idx)}
                        onClick={() => setActiveGroupIdx(idx)}
                        className={`flex w-full items-center justify-between gap-1.5 rounded-md px-2 py-2 text-left text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-accent/50'}`}
                      >
                        <span className="truncate">{group.label}</span>
                        {hasAccounts ? (
                          <span className="shrink-0 text-muted-foreground opacity-60">›</span>
                        ) : null}
                      </button>
                    )
                  })}
                </div>
                <div className="min-w-0 flex-1 overflow-y-auto pl-2">
                  {activeGroup ? (
                    activeGroup.accounts.length > 0 ? (
                      activeGroup.accounts.map((account) => {
                        const name = account.name.trim()
                        const isSelected = value.trim() === name
                        return (
                          <button
                            key={name}
                            type="button"
                            onClick={() => {
                              onSelect(name)
                              setOpen(false)
                            }}
                            className={`flex w-full items-center gap-1.5 rounded-md px-2 py-2 text-left text-sm transition-colors ${isSelected ? 'bg-accent/20 text-primary' : 'text-foreground hover:bg-accent/50'}`}
                          >
                            <span className="flex-1 truncate">{name}</span>
                            {isSelected ? <span className="text-primary">✓</span> : null}
                          </button>
                        )
                      })
                    ) : (
                      <p className="px-2 py-2 text-[11px] text-muted-foreground">{t('accounts.empty.byType')}</p>
                    )
                  ) : null}
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}
