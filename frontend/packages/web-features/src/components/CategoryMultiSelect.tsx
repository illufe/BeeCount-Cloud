import { useEffect, useMemo, useRef, useState } from 'react'

import type { WorkspaceCategory } from '@beecount/api-client'

type CategoryMultiSelectProps = {
  /** 分类方向:expense / income / all(筛选"不限类型"时收入+支出一起)。 */
  kind: 'expense' | 'income' | 'all'
  /** 全量分类(workspace dedup 后)。组件内部按 kind 过滤 + 按 parent 分组。 */
  rows: readonly WorkspaceCategory[]
  /** 未选中时的占位文案。 */
  placeholder: string
  /** 已选中的分类 syncId 列表。 */
  selected: string[]
  onChange: (values: string[]) => void
  /** 触发控件高度:md=表单用(h-10),sm=筛选栏用(h-9)。 */
  size?: 'md' | 'sm'
  /** 允许清空回到占位(用于筛选栏)。选中时触发控件内出现 "×" 按钮。 */
  allowClear?: boolean
  onClear?: () => void
  /** 触发控件宽度类。缺省 w-full;筛选栏可传固定宽如 w-[200px]。 */
  triggerClassName?: string
  /** 弹出层宽度类。缺省 w-[320px](两栏目录需要点宽度)。 */
  popoverClassName?: string
  /** 弹层主标题文案(如 "分类")。 */
  title?: string
  /** 方向组标题(kind='all' 时左栏分组用,通常传 i18n 的 enum.txType.income/expense)。 */
  incomeLabel?: string
  expenseLabel?: string
}

const key = (name: string) => (name || '').trim().toLowerCase()

/**
 * 记一笔筛选栏「分类」多选控件 —— 随手记式两级目录(左右两栏:左=一级分类,
 * 右=当前一级分类的二级)。左栏悬停/点击即切换右栏(无需额外点击展开二级),
 * 两级都带 checkbox 支持多选;勾选一级分类 = 选中整棵(服务端已做父级展开)。
 */
export function CategoryMultiSelect({
  kind,
  rows,
  placeholder,
  selected,
  onChange,
  size = 'sm',
  allowClear = false,
  onClear,
  triggerClassName,
  popoverClassName = 'w-[320px]',
  title,
  incomeLabel = '收入',
  expenseLabel = '支出',
}: CategoryMultiSelectProps) {
  const [open, setOpen] = useState(false)
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

  // 按 kind 过滤 + parent_name 分组。parent_name 空 = 一级。sort_order 升序,同序再按 name。
  // kind='all' 时按方向分组(支出/收入两组,同名父级互不共享)。
  // labelById / childParentTopId 与树一起产出(子级 id 可能跨方向同名,须在方向内查)。
  const dirOrder: Array<'expense' | 'income'> =
    kind === 'all' ? ['expense', 'income'] : [kind as 'expense' | 'income']

  const { groups, childrenByKindParent, topLevels, labelById, childParentTopId } = useMemo(() => {
    const groups: Array<{ kind: 'expense' | 'income'; label: string; tops: WorkspaceCategory[] }> = []
    const childrenByKindParent: Record<'expense' | 'income', Record<string, WorkspaceCategory[]>> = { expense: {}, income: {} }
    const labelById = new Map<string, string>()
    const childParentTopId = new Map<string, string>()
    const sorter = (a: WorkspaceCategory, b: WorkspaceCategory) =>
      (a.sort_order ?? 0) - (b.sort_order ?? 0) || (a.name || '').localeCompare(b.name || '')
    for (const d of dirOrder) {
      const inKind = rows.filter((row) => row.kind === d)
      const tops: WorkspaceCategory[] = []
      const children: Record<string, WorkspaceCategory[]> = {}
      for (const row of inKind) {
        const parent = (row.parent_name || '').trim()
        if (parent) {
          const k = key(parent)
          children[k] = children[k] || []
          children[k].push(row)
        } else {
          tops.push(row)
        }
      }
      tops.sort(sorter)
      for (const k of Object.keys(children)) children[k].sort(sorter)
      const label = d === 'expense' ? expenseLabel : incomeLabel
      groups.push({ kind: d, label, tops })
      childrenByKindParent[d] = children
      for (const top of tops) {
        const name = (top.name || '').trim()
        labelById.set(top.id, name)
        for (const child of children[key(name)] || []) {
          labelById.set(child.id, `${name} / ${child.name}`)
          childParentTopId.set(child.id, top.id)
        }
      }
    }
    const topLevels = groups.flatMap((g) => g.tops)
    return { groups, childrenByKindParent, topLevels, labelById, childParentTopId }
  }, [rows, kind, incomeLabel, expenseLabel])

  // 右侧栏当前突出的一级分类。
  const [activeParentId, setActiveParentId] = useState<string | null>(null)
  const activeParent = activeParentId ? topLevels.find((t) => t.id === activeParentId) || null : null
  const activeChildren = activeParent
    ? (childrenByKindParent[activeParent.kind as 'expense' | 'income'][key(activeParent.name)] || [])
    : []

  const selectedChildParentId = () => {
    for (const id of selected) {
      const p = childParentTopId.get(id)
      if (p) return p
    }
    return null
  }

  // 打开面板时,把右栏切到某个已选子级的父级(否则看第一个一级分类)。
  useEffect(() => {
    if (!open) return
    setActiveParentId(selectedChildParentId() ?? topLevels[0]?.id ?? null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, topLevels])

  // kind / rows 变化后,若当前激活的一级已不存在则回退(并保留已选子级可见)。
  useEffect(() => {
    if (!topLevels.length) {
      setActiveParentId(null)
      return
    }
    setActiveParentId((prev) => {
      if (prev && topLevels.some((t) => t.id === prev)) return prev
      return selectedChildParentId() ?? topLevels[0].id
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topLevels])

  // 触发文案:一级已选则省略其子级(避免 "食品酒水、食品酒水 / 早午晚餐" 冗余)。
  const joined = selected
    .filter((id) => {
      const p = childParentTopId.get(id)
      return !(p && selected.includes(p))
    })
    .map((id) => labelById.get(id) || id)
    .join('、')

  const toggle = (id: string) => {
    onChange(selected.includes(id) ? selected.filter((v) => v !== id) : [...selected, id])
  }

  // 左栏"悬停意图"延时切换右栏,避免鼠标横穿时误切。
  const hoverTimerRef = useRef<number | null>(null)
  const scheduleParent = (id: string) => {
    if (hoverTimerRef.current) window.clearTimeout(hoverTimerRef.current)
    hoverTimerRef.current = window.setTimeout(() => setActiveParentId(id), 150)
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
        className={`flex ${size === 'sm' ? 'h-9' : 'h-10'} items-center gap-2 rounded-md border border-input bg-muted px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent/40 ${triggerClassName || 'w-full'}`}
      >
        <span className={`flex-1 truncate ${hasSelection ? '' : 'text-muted-foreground'}`}>
          {hasSelection ? joined : placeholder}
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
          {topLevels.length === 0 ? (
            <p className="px-2 py-3 text-center text-sm text-muted-foreground">{placeholder}</p>
          ) : (
            <div className="flex max-h-72 overflow-hidden">
              <div
                className="w-[45%] shrink-0 overflow-y-auto border-r border-border/60 pr-1"
                onMouseLeave={cancelHoverIntent}
              >
                {groups.map((group) => (
                  <div key={group.kind}>
                    {kind === 'all' ? (
                      <p className="px-2 pb-0.5 pt-1.5 text-[11px] font-medium text-muted-foreground">{group.label}</p>
                    ) : null}
                    {group.tops.length === 0 ? (
                      <p className="px-2 py-1 text-[11px] text-muted-foreground/70">暂无分类</p>
                    ) : (
                      group.tops.map((top) => {
                        const hasChildren = (childrenByKindParent[top.kind as 'expense' | 'income'][key(top.name)]?.length ?? 0) > 0
                        const isActive = activeParentId === top.id
                        const checked = selected.includes(top.id)
                        return (
                          <div key={top.id} onMouseLeave={cancelHoverIntent} className="flex w-full items-center gap-1 rounded-md px-1 py-1">
                            <input type="checkbox" checked={checked} onChange={() => toggle(top.id)} className="h-4 w-4 shrink-0 accent-primary" />
                            <button type="button" onMouseEnter={() => scheduleParent(top.id)} onClick={() => setActiveParentId(top.id)}
                              className={`flex flex-1 items-center gap-1.5 rounded-md px-1.5 py-1.5 text-left text-sm transition-colors ${isActive ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-accent/50'}`}>
                              <span className="flex-1 truncate">{top.name}</span>
                              {hasChildren ? <span className="shrink-0 text-muted-foreground opacity-60">›</span> : null}
                            </button>
                          </div>
                        )
                      })
                    )}
                  </div>
                ))}
              </div>
              <div className="min-w-0 flex-1 overflow-y-auto pl-2">
                {activeParent ? (
                  activeChildren.length > 0 ? (
                    activeChildren.map((child) => {
                      const checked = selected.includes(child.id)
                      return (
                        <label
                          key={child.id}
                          className={`flex w-full cursor-pointer items-center gap-1.5 rounded-md px-2 py-2 text-left text-sm transition-colors ${checked ? 'bg-accent/20 text-primary' : 'text-foreground hover:bg-accent/50'}`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggle(child.id)}
                            className="h-4 w-4 shrink-0 accent-primary"
                          />
                          <span className="flex-1 truncate">{child.name}</span>
                        </label>
                      )
                    })
                  ) : (
                    <p className="px-2 py-2 text-[11px] text-muted-foreground">选择「{activeParent.name}」</p>
                  )
                ) : (
                  <p className="px-2 py-2 text-[11px] text-muted-foreground">请选择左侧分类</p>
                )}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
