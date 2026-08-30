import { useEffect, useMemo, useRef, useState } from 'react'

export type FilterMultiSelectGroup = {
  /** 分组小标题。null = 不显示(如顶级分类直接平铺)。 */
  header: string | null
  options: Array<{ value: string; label: string }>
}

type FilterMultiSelectProps = {
  /** 未选中时的占位文案。 */
  placeholder: string
  /** 分组选项。同组多选 = "任一命中";跨组仍叠加收窄(维度内 OR、维度间 AND)。 */
  groups: FilterMultiSelectGroup[]
  /** 已选中的 value 列表。 */
  selected: string[]
  onChange: (values: string[]) => void
  /** 触发控件高度:md=表单用(h-10),sm=筛选栏用(h-9)。 */
  size?: 'md' | 'sm'
  /** 允许清空回到占位(用于筛选栏)。选中时触发控件内出现 "×" 按钮。 */
  allowClear?: boolean
  onClear?: () => void
  /** 触发控件宽度类。缺省 w-full;筛选栏可传固定宽如 w-[150px]。 */
  triggerClassName?: string
  /** 弹出层宽度类。缺省 w-[260px]。 */
  popoverClassName?: string
  /** 弹层主标题文案(如 "账户")。 */
  title?: string
}

/**
 * 筛选栏多选控件 —— 分组复选框弹层。点字段展开,勾选即实时更新(不自动收起,
 * 方便连续勾选),点击面板外 / Esc 关闭。缺省 value 语义 = "全部"(空数组)。
 */
export function FilterMultiSelect({
  placeholder,
  groups,
  selected,
  onChange,
  size = 'sm',
  allowClear = false,
  onClear,
  triggerClassName,
  popoverClassName,
  title,
}: FilterMultiSelectProps) {
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

  const labelByValue = useMemo(() => {
    const map = new Map<string, string>()
    for (const group of groups) {
      for (const option of group.options) map.set(option.value, option.label)
    }
    return map
  }, [groups])

  const joined = selected.map((value) => labelByValue.get(value) || value).join('、')

  const toggle = (value: string) => {
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value])
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
          className={`absolute left-0 top-full z-50 mt-1 rounded-xl border border-border/60 bg-background p-1 shadow-lg ${popoverClassName || 'w-[260px]'}`}
        >
          {title ? (
            <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">{title}</p>
          ) : null}
          <div className="max-h-72 overflow-y-auto">
            {groups.map((group) => (
              <div key={group.header ?? '__root__'}>
                {group.header ? (
                  <p className="px-2 pt-2 pb-1 text-xs font-medium text-muted-foreground">{group.header}</p>
                ) : null}
                {group.options.map((option) => {
                  const checked = selected.includes(option.value)
                  return (
                    <label
                      key={option.value}
                      className={`flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent/40 ${checked ? 'bg-accent/20' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(option.value)}
                        className="h-4 w-4 shrink-0 accent-primary"
                      />
                      <span className="truncate">{option.label}</span>
                    </label>
                  )
                })}
              </div>
            ))}
            {groups.length === 0 ? (
              <p className="px-2 py-3 text-center text-sm text-muted-foreground">{placeholder}</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
