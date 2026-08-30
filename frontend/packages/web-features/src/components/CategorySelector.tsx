import { useEffect, useMemo, useRef, useState } from 'react'

import type { WorkspaceCategory } from '@beecount/api-client'

import { CategoryIcon } from './CategoryIcon'

type CategorySelectorKind = 'expense' | 'income'

type CategorySelectorProps = {
  /** 分类类型,只有 expense / income 让选(transfer 是虚拟分类不参与选择)。
   *  `all` 用于筛选栏等"不限类型"场景:同时展示收入 + 支出两套分类。 */
  kind: CategorySelectorKind | 'all'
  /** 全量分类列表(workspace dedup 后),通常从 fetchWorkspaceCategories 拿。
   *  组件内部按 kind 过滤 + 按 parent_name 分组,父级展示在网格,点开后子级
   *  在父行下方原地展开。 */
  rows: readonly WorkspaceCategory[]
  /** 选中的分类 syncId(可选)。会高亮 + 自动展开父级 + 滚动到视口。 */
  selectedId?: string | null
  /** 自定义图标 cloud 文件预览 URL 表(从 useAttachmentCache 拿)。没传则
   *  custom 类型分类显示 sync 兜底字形。 */
  iconPreviewUrlByFileId?: Record<string, string>
  /** 选定回调。父级有子分类时点击只切换展开,不会触发 onSelect。 */
  onSelect: (category: WorkspaceCategory) => void
  /** 没有任何分类时显示的占位文案。 */
  emptyText?: string
  /** 网格列数,默认 4。windows 大点的可传 6/8 摆得密一些。 */
  columns?: number
  className?: string
  /**
   * 布局变体:
   *  - `grid`(默认):父级按网格平铺,点击父级原地展开子级 —— 对齐 mobile。
   *  - `pane`:左右两栏目录(左=一级分类,右=选中一级分类的子级),像随手记
   *    的二级目录。左侧悬停即切换右侧,子级一键选取,减少点击数。
   */
  variant?: 'grid' | 'pane'
}

/**
 * 通用分类选择器 —— 1:1 复刻 app `lib/widgets/category/category_selector.dart`
 * 的交互模型:
 *   - kind 切支出 / 收入,只展示对应方向的分类
 *   - 顶级分类按 4(默认)列网格平铺
 *   - 父级有子分类:点击切换展开/折叠,**不**触发 onSelect
 *   - 父级无子分类:点击直接 onSelect,同时折叠所有已展开的父级
 *   - 子级:点击直接 onSelect
 *   - 选中态用主题色 ring 高亮
 *   - 父级带子分类的右下角有"…"小徽章作为视觉提示
 *
 * 跟 mobile 的差异(纯 UI):
 *   - 用 ring + bg tint 替代纯 fill 圆形,跟 web 卡片风格一致
 *   - 图标走 web `CategoryIcon`(Material Symbols 字体子集 + custom 云文件)
 *   - 子级展开容器没有阴影,而是浅色背景 + border,跟 dialog 内嵌更协调
 */
export function CategorySelector({
  kind,
  rows,
  selectedId,
  iconPreviewUrlByFileId,
  onSelect,
  emptyText,
  columns = 4,
  className,
  variant = 'grid',
}: CategorySelectorProps) {
  // 内部展开状态 —— 只有点击的父级允许同时展开 1 个,跟 mobile 一致。
  const [expandedParentId, setExpandedParentId] = useState<string | null>(null)

  // 选中的分类如果是 level=2,自动展开它的父级,否则保持当前展开状态。仅在
  // selectedId 变化(外部 set)时跑一次,内部点击后用户可能手动折叠。
  const lastSelectedRef = useRef<string | null | undefined>(null)

  // 按 kind 过滤 + parent_name 分组(parent_name 空 = 顶级)。sort_order 升序,
  // 同 sort 再按 name。跟 app `getTopLevelCategories` / `getSubCategories` 行为
  // 对齐。
  const { topLevels, childrenByParentName } = useMemo(() => {
    // kind='all'(筛选栏"不限类型")只展示真实收入/支出分类,排除虚拟的 transfer。
    const inKind = kind === 'all'
      ? rows.filter((row) => row.kind === 'expense' || row.kind === 'income')
      : rows.filter((row) => row.kind === kind)
    const tops: WorkspaceCategory[] = []
    const children: Record<string, WorkspaceCategory[]> = {}
    for (const row of inKind) {
      const parent = (row.parent_name || '').trim()
      if (parent) {
        const key = parent.toLowerCase()
        children[key] = children[key] || []
        children[key].push(row)
      } else {
        tops.push(row)
      }
    }
    const sorter = (a: WorkspaceCategory, b: WorkspaceCategory) =>
      (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
      (a.name || '').localeCompare(b.name || '')
    tops.sort(sorter)
    for (const k of Object.keys(children)) children[k].sort(sorter)
    return { topLevels: tops, childrenByParentName: children }
  }, [rows, kind])

  // 找到 selectedId 对应的行,用来决定是否要自动展开父级
  const selectedRow = useMemo(
    () => (selectedId ? rows.find((r) => r.id === selectedId) : null),
    [rows, selectedId]
  )

  useEffect(() => {
    if (lastSelectedRef.current === selectedId) return
    lastSelectedRef.current = selectedId
    if (!selectedRow) return
    const parent = (selectedRow.parent_name || '').trim()
    if (!parent) return
    // 找到父级的 syncId(rows 里 name+kind 唯一的 level=1)
    const parentRow = rows.find(
      (r) =>
        (kind === 'all' || r.kind === kind) &&
        Number(r.level) === 1 &&
        (r.name || '').trim().toLowerCase() === parent.toLowerCase()
    )
    if (parentRow?.id) setExpandedParentId(parentRow.id)
  }, [selectedRow, selectedId, rows, kind])

  // 左右两栏模式:当前突出的一级分类,决定右侧显示哪些子级。
  const [activeParentId, setActiveParentId] = useState<string | null>(() => {
    const parent = (selectedRow?.parent_name || '').trim()
    if (parent) {
      const p = topLevels.find((t) => (t.name || '').trim().toLowerCase() === parent.toLowerCase())
      return p?.id ?? (topLevels[0]?.id ?? null)
    }
    return topLevels[0]?.id ?? null
  })
  const activeParent =
    activeParentId ? topLevels.find((t) => t.id === activeParentId) || null : null
  const activeChildren = activeParent
    ? (childrenByParentName[(activeParent.name || '').trim().toLowerCase()] || [])
    : []

  // 选中态变化时,把右栏切到所选分类的父级(保证当前选中可见)。
  useEffect(() => {
    if (!selectedRow) return
    const parent = (selectedRow.parent_name || '').trim()
    const p = parent
      ? topLevels.find((t) => (t.name || '').trim().toLowerCase() === parent.toLowerCase())
      : topLevels[0]
    if (p?.id) setActiveParentId(p.id)
  }, [selectedRow, topLevels])

  // 左侧"悬停意图"延时:鼠标在某一级分类上停留后才切换右栏,避免鼠标横穿时
  // 快速扫过其它一级分类导致右栏被误切。不再需要时取消。
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

  if (topLevels.length === 0) {
    return (
      <div className={`py-8 text-center text-sm text-muted-foreground ${className || ''}`.trim()}>
        {emptyText ?? '暂无分类'}
      </div>
    )
  }

  // 左右两栏目录(随手记风格):左侧悬停/点击切一级分类,右侧一键选子级。
  if (variant === 'pane') {
    return (
      <div className={`flex max-h-[60vh] overflow-hidden ${className || ''}`.trim()}>
        <div className="w-[45%] shrink-0 overflow-y-auto border-r border-border/60 pr-1" onMouseLeave={cancelHoverIntent}>
          {topLevels.map((top) => {
            const hasChildren = (childrenByParentName[(top.name || '').trim().toLowerCase()]?.length ?? 0) > 0
            const isActive = activeParentId === top.id
            const isSelected = selectedId === top.id
            return (
              <button
                key={top.id}
                type="button"
                onMouseEnter={() => scheduleParent(top.id)}
                onClick={() => (hasChildren ? setActiveParentId(top.id) : onSelect(top))}
                className={`flex w-full items-center justify-between gap-1 rounded-md px-2 py-2 text-left text-sm transition-colors ${
                  isActive ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-accent/50'
                } ${isSelected ? 'font-medium text-primary' : ''}`}
              >
                <span className="truncate">{top.name}</span>
                {hasChildren ? <span className="shrink-0 text-muted-foreground opacity-60">›</span> : null}
              </button>
            )
          })}
        </div>
        <div className="min-w-0 flex-1 overflow-y-auto pl-2">
          {activeParent ? (
            activeChildren.length > 0 ? (
              activeChildren.map((child) => {
                const isSelected = selectedId === child.id
                return (
                  <button
                    key={child.id}
                    type="button"
                    onClick={() => onSelect(child)}
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors ${
                      isSelected ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-accent/50'
                    }`}
                  >
                    <CategoryIcon
                      icon={child.icon}
                      iconType={child.icon_type}
                      iconCloudFileId={child.icon_cloud_file_id}
                      iconPreviewUrlByFileId={iconPreviewUrlByFileId}
                      size={16}
                      className={isSelected ? 'text-primary' : 'text-muted-foreground'}
                    />
                    <span className="truncate">{child.name}</span>
                  </button>
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
    )
  }

  // 把 topLevels 切成 columns 列一组的"行",每行检查是否有展开,有则在行下
  // 紧跟一个 sub-grid 容器(跟 mobile 同样的"原地展开"视觉)。
  const rowsOfTops: WorkspaceCategory[][] = []
  for (let i = 0; i < topLevels.length; i += columns) {
    rowsOfTops.push(topLevels.slice(i, i + columns))
  }

  // CSS grid template:用 `--cols` CSS 变量驱动 grid-template-columns,避免 tailwind
  // 任意值生成器在生产构建时不被 purge 误删。
  const gridStyle = { ['--cols' as string]: String(columns) }
  const gridClass =
    'grid gap-3 [grid-template-columns:repeat(var(--cols),minmax(0,1fr))]'

  const handleParentTap = (top: WorkspaceCategory) => {
    const childList = childrenByParentName[(top.name || '').toLowerCase()]
    const hasChildren = (childList?.length ?? 0) > 0
    if (hasChildren) {
      setExpandedParentId((prev) => (prev === top.id ? null : top.id))
    } else {
      // 父无子 → 直接选;同时折叠任何已展开的父级,跟 app 行为对齐
      setExpandedParentId(null)
      onSelect(top)
    }
  }

  return (
    <div className={`space-y-3 ${className || ''}`.trim()}>
      {rowsOfTops.map((row, rowIdx) => {
        const expandedInRow = row.find((c) => c.id === expandedParentId)
        const expandedChildren = expandedInRow
          ? childrenByParentName[(expandedInRow.name || '').toLowerCase()] ?? []
          : []

        return (
          <div key={`row-${rowIdx}`} className="space-y-3">
            <div className={gridClass} style={gridStyle}>
              {row.map((top) => {
                const childList = childrenByParentName[(top.name || '').toLowerCase()]
                const hasChildren = (childList?.length ?? 0) > 0
                const isExpanded = expandedParentId === top.id
                const isSelected = selectedId === top.id
                return (
                  <CategoryCell
                    key={top.id}
                    category={top}
                    iconPreviewUrlByFileId={iconPreviewUrlByFileId}
                    selected={isSelected}
                    expanded={isExpanded}
                    hasChildren={hasChildren}
                    onTap={() => handleParentTap(top)}
                  />
                )
              })}
            </div>

            {/* 行内有展开父级 → 紧跟一个子级容器。用 muted 浅卡片框起来,跟
                "页面背景色"和"父级网格"区分开,视觉上明确从属关系。 */}
            {expandedInRow && expandedChildren.length > 0 ? (
              <div
                className="rounded-xl border border-border/50 bg-muted/30 p-3 ring-1 ring-primary/15"
                style={{
                  // 让子容器与父级 cell 视觉对齐,左侧不要硬贴边
                }}
              >
                <div className={gridClass} style={gridStyle}>
                  {expandedChildren.map((child) => {
                    const isSelected = selectedId === child.id
                    return (
                      <CategoryCell
                        key={child.id}
                        category={child}
                        iconPreviewUrlByFileId={iconPreviewUrlByFileId}
                        selected={isSelected}
                        compact
                        onTap={() => onSelect(child)}
                      />
                    )
                  })}
                </div>
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

/**
 * 单个分类格子。父级 / 子级 / 选中态共用,差异靠 `compact` + `selected` 切换。
 * `hasChildren` 控制右下角小三点徽章。
 */
function CategoryCell({
  category,
  iconPreviewUrlByFileId,
  selected,
  expanded,
  hasChildren,
  compact,
  onTap,
}: {
  category: WorkspaceCategory
  iconPreviewUrlByFileId?: Record<string, string>
  selected: boolean
  expanded?: boolean
  hasChildren?: boolean
  compact?: boolean
  onTap: () => void
}) {
  const iconSize = compact ? 22 : 26
  const circleSize = compact ? 'h-12 w-12' : 'h-14 w-14'
  const labelSize = compact ? 'text-[11px]' : 'text-xs'

  return (
    <button
      type="button"
      onClick={onTap}
      className="group flex flex-col items-center gap-1.5 outline-none"
      aria-pressed={selected}
    >
      <div className="relative">
        <div
          className={`flex ${circleSize} items-center justify-center rounded-full transition-all ${
            selected
              ? 'bg-primary/15 text-primary ring-2 ring-primary/60'
              : 'bg-muted/60 text-foreground group-hover:bg-accent/60'
          } ${expanded ? 'ring-1 ring-primary/40' : ''}`}
        >
          <CategoryIcon
            icon={category.icon}
            iconType={category.icon_type}
            iconCloudFileId={category.icon_cloud_file_id}
            iconPreviewUrlByFileId={iconPreviewUrlByFileId}
            size={iconSize}
          />
        </div>

        {/* 父级带子分类的右下角"…"徽章 —— 跟 app category_selector 一致的视觉
            提示:点击会展开。compact(子级)不显示。 */}
        {hasChildren && !compact ? (
          <span
            aria-hidden
            className={`absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full border-2 border-background text-[10px] leading-none ${
              selected ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
            }`}
          >
            ⋯
          </span>
        ) : null}
      </div>

      <span
        className={`max-w-full truncate ${labelSize} ${
          selected ? 'font-medium text-primary' : 'text-foreground'
        }`}
        title={category.name}
      >
        {category.name}
      </span>
    </button>
  )
}
