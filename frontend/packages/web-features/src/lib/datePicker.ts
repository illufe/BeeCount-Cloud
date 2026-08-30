/**
 * 打开原生日期/时间选择器(native picker)。
 *
 * 浏览器对 `type="date"` / `type="datetime-local"` 输入只会在点击右侧日历图标时
 * 弹出选择器,点击输入框其它区域只聚焦不弹。记账表单时间控件和快速记账筛选栏的
 * 日期控件都希望在「点击控件任意位置」时直接弹出选择器,这里统一封装:
 *  - `showPicker()` 需要用户手势触发,因此必须在 onClick 里同步调用;
 *  - 无 `showPicker` 的环境(Safari 旧版等)静默跳过,保持原生聚焦行为;
 *  - 选择器已在打开状态时调用会抛错,吞掉即可。
 */
export function openNativePicker(event: React.MouseEvent<HTMLInputElement>): void {
  const el = event.currentTarget
  if (typeof el.showPicker !== 'function') return
  try {
    el.showPicker()
  } catch {
    // picker already open, or the browser/context disallows showPicker()
  }
}
