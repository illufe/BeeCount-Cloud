import { useEffect, useRef, useState } from 'react'

import type { WorkspaceCategory } from '@beecount/api-client'

import { CategoryIcon } from './CategoryIcon'
import { CategorySelector } from './CategorySelector'

type CategoryDropdownProps = {
  /** 分类方向:expense / income 参与选择;`all` 用于筛选栏"不限类型"(收入+支出)。 */
  kind: 'expense' | 'income' | 'all'
  /** 全量分类(workspace dedup 后),交给 CategorySelector 按 kind 过滤 + 按 parent 分组。 */
  rows: readonly WorkspaceCategory[]
  /** 当前选中的分类,决定字段文案和图标。 */
  selected: WorkspaceCategory | null
  dictionariesLoading?: boolean
  iconPreviewUrlByFileId?: Record<string, string>
  /** 未选中时的占位文案。 */
  placeholder: string
  onSelect: (category: WorkspaceCategory) => void
  /** 触发控件高度:md=表单用(h-10),sm=筛选栏用(h-9)。 */
  size?: 'md' | 'sm'
  /** 允许清空回到占位(用于筛选栏)。选中时触发控件内出现 "×" 按钮。 */
  allowClear?: boolean
  onClear?: () => void
  /** 触发控件宽度类。缺省 w-full(撑满父容器);筛选栏可传固定宽如 w-[130px]。 */
  triggerClassName?: string
}

/**
 * 记一笔 / 筛选栏分类控件 —— 不用额外 dialog,点字段就直接在下方展开左右两栏二级
 * 目录(随手记风格)。选中即收起。点击面板外 / Esc 关闭。
 */
export function CategoryDropdown({
  kind,
  rows,
  selected,
  dictionariesLoading = false,
  iconPreviewUrlByFileId,
  placeholder,
  onSelect,
  size = 'md',
  allowClear = false,
  onClear,
  triggerClassName,
}: CategoryDropdownProps) {
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

  const value = (selected?.name || '').trim()

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={dictionariesLoading}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`flex ${size === 'sm' ? 'h-9' : 'h-10'} items-center gap-2 rounded-md border border-input bg-muted px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-50 ${triggerClassName || 'w-full'}`}
      >
        {selected ? (
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15">
            <CategoryIcon
              icon={selected.icon}
              iconType={selected.icon_type}
              iconCloudFileId={selected.icon_cloud_file_id}
              iconPreviewUrlByFileId={iconPreviewUrlByFileId}
              size={16}
              className="text-primary"
            />
          </span>
        ) : null}
        <span className={`flex-1 truncate ${value ? '' : 'text-muted-foreground'}`}>
          {selected?.parent_name
            ? `${selected.parent_name} / ${value}`
            : (value || placeholder)}
        </span>
        {allowClear && selected ? (
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
        <div className="absolute left-0 top-full z-50 mt-1 w-[300px] rounded-xl border border-border/60 bg-background p-1 shadow-lg">
          <CategorySelector
            kind={kind}
            rows={rows}
            selectedId={selected?.id}
            iconPreviewUrlByFileId={iconPreviewUrlByFileId}
            variant="pane"
            onSelect={(cat) => {
              onSelect(cat)
              setOpen(false)
            }}
          />
        </div>
      ) : null}
    </div>
  )
}
