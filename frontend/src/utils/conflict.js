/**
 * 保存冲突（后端返回 409）时让用户选择：载入最新内容 / 仍然覆盖 / 继续编辑
 */
import { choiceDialog } from './dialog'

/** 返回 'load' | 'overwrite' | null（继续编辑） */
export function askConflict() {
  return choiceDialog({
    title: '内容已在别处更新',
    message: '你编辑期间，这段内容在别的设备上被修改过。载入最新内容会丢掉你这次的修改；仍然覆盖会用你的内容替换别处的修改。',
    choices: [
      { value: 'load', label: '载入最新内容' },
      { value: 'overwrite', label: '仍然覆盖', danger: true },
    ],
    cancelText: '继续编辑',
  })
}
