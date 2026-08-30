import { useEffect, useRef, useState } from 'react'

import type { AccountGroup } from '../lib/accountGroups'

type AccountMultiSelectProps = {
  /** 账户分组(account_type → 账户),来自 groupAccountPickerOptions。 */
  groups: AccountGroup[]
  /** 未选中时的占位文案。 */
  placeholder: string
  /** 已选中的账户名列表。 */
  selected: string[]
  onChange: (names: string[]) => void
  /** 允许清空回到占位(用于筛选栏)。选中时触发控件内出现 "×" 按钮。 */
  allowClear?: boolean
  onClear?: () => void
  /** 触发控件宽度类。缺省 w-full;筛选栏可传固定宽如 w-[170px]。 */
  triggerClassName?: string
  /** 弹出层宽度类。缺省 w-[320px](两栏目录需要点宽度)。 */
  popoverClassName?: string
  /** 弹层主标题文案(如 "账户")。 */
  title?: string
}

/**
 * 记一笔筛选栏「账户」多选控件 —— 随手记式两级目录(左右两栏:左=账户类型,
 * 右=当前类型的账户)。左栏点击/悬停即切换右栏(无需额外点击展开),账户用 checkbox
 * 多选;一级"类型"本身不是可筛维度,仅作目录导航。
 */
export function AccountMultiSelect({
  groups,
  placeholder,
  selected,
  onChange,
  allowClear = false,
  onClear,
  triggerClassName,
  popoverClassName = 'w-[320px]',
  title,
}: AccountMultiSelectProps) {
  const [open, setOpen] = useState(false)
  const [activeGroupIdx, setActiveGroupIdx] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)

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

  // 打开面板时,把右栏切到含已选账户的类型分组(否则看第一个类型分组)。
  useEffect(() => {
    if (!open) return
    setActiveGroupIdx((prev) => {
      if (groups.length === 0) return prev
      const selectedIdx = groups.findIndex((g) => g.accounts.some((a) => selected.includes(a.name.trim())))
      return selectedIdx >= 0 ? selectedIdx : Math.min(prev, groups.length - 1)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const activeGroup = groups[activeGroupIdx] || null

  const toggle = (name: string) => {
    onChange(selected.includes(name) ? selected.filter((v) => v !== name) : [...selected, name])
  }

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

  const hasSelection = selected.length > 0

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`flex h-9 items-center gap-2 rounded-md border border-input bg-muted px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent/40 ${triggerClassName || 'w-full'}`}
      >
        <span className={`flex-1 truncate ${hasSelection ? '' : 'text-muted-foreground'}`}>
          {hasSelection ? selected.join('、') : placeholder}
        </span>
        {hasSelection ? (
          <span className="shrink-0 rounded-full bg-primary/15 px-1.5 text-[11px] leading-4 text-primary">
            {selected.length}
          </span>
        ) : null}
        {allowClear && hasSelection ? (
          <span
            role="button"
            tabIndex={-1}
            aria-label={placeholder}
            onClick={(event) => {
              event.stopPropagation()
              onClear?.()
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
        <div
          className={`absolute left-0 top-full z-50 mt-1 rounded-xl border border-border/60 bg-background p-1 shadow-lg ${popoverClassName}`}
        >
          {title ? (
            <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">{title}</p>
          ) : null}
          {groups.length === 0 ? (
            <p className="px-2 py-3 text-center text-sm text-muted-foreground">{placeholder}</p>
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
                      const checked = selected.includes(name)
                      return (
                        <label
                          key={name}
                          className={`flex w-full cursor-pointer items-center gap-1.5 rounded-md px-2 py-2 text-left text-sm transition-colors ${checked ? 'bg-accent/20 text-primary' : 'text-foreground hover:bg-accent/50'}`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggle(name)}
                            className="h-4 w-4 shrink-0 accent-primary"
                          />
                          <span className="flex-1 truncate">{name}</span>
                        </label>
                      )
                    })
                  ) : (
                    <p className="px-2 py-2 text-[11px] text-muted-foreground">该类型暂无账户</p>
                  )
                ) : null}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
