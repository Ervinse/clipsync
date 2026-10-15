/**
 * 多段文本的编辑草稿：文本栏目页（Texts.vue）与快速访问页（QuickAccess.vue）共用。
 *
 * 每段文本一份草稿 { title, content, syncedTitle, syncedContent, version, loaded, loading, saving, remoteChanged }：
 * - 列表里较长的文本没有全文（content 为 null），loaded 为 false，要先 loadFull 才能编辑
 * - 列表刷新时，没有未保存修改的草稿跟着更新；有未保存修改的只标记 remoteChanged，不覆盖正在输入的内容
 * - 保存带上草稿的版本号，内容已在别处改过（409）时让用户选择载入最新内容或仍然覆盖
 *
 * fetchFull(key) → { title, content, version }
 * saveItem(key, { title, content, base_version }) → { title, content, version, ... }
 * onSaved(key, 响应)：保存成功后的回调（如就地更新列表）
 */
import { reactive } from 'vue'
import toast from './toast'
import { askConflict } from './conflict'

export function createTextDrafts({ fetchFull, saveItem, onSaved }) {
  const drafts = reactive({})

  const isDirty = (d) => !!d && d.loaded && (d.title !== d.syncedTitle || d.content !== d.syncedContent)

  const hasDirty = () => Object.values(drafts).some(isDirty)

  function apply(d, data) {
    d.title = data.title ?? ''
    d.content = data.content ?? ''
    d.syncedTitle = d.title
    d.syncedContent = d.content
    d.version = data.version
    d.loaded = true
    d.remoteChanged = false
  }

  async function loadFull(key) {
    const d = drafts[key]
    if (!d || d.loading) return false
    d.loading = true
    try {
      const data = await fetchFull(key)
      if (drafts[key]) apply(drafts[key], data)
      return true
    } catch (error) {
      toast.error('载入失败：' + error.message)
      return false
    } finally {
      if (drafts[key]) drafts[key].loading = false
    }
  }

  /** 用最新列表更新草稿；items 为 [{ key, title, content（可能为 null）, version }] */
  function sync(items) {
    const present = new Set()
    for (const item of items) {
      const key = String(item.key)
      present.add(key)
      const d = drafts[key]
      if (!d) {
        const loaded = item.content !== null && item.content !== undefined
        drafts[key] = {
          title: item.title ?? '',
          content: loaded ? item.content : '',
          syncedTitle: item.title ?? '',
          syncedContent: loaded ? item.content : '',
          version: item.version,
          loaded,
          loading: false,
          saving: false,
          remoteChanged: false,
        }
        continue
      }
      // 版本没变，或正在保存（保存结果会带回新版本）：不动草稿
      if (item.version === d.version || d.saving) continue
      if (isDirty(d)) {
        d.remoteChanged = true
      } else if (item.content !== null && item.content !== undefined) {
        apply(d, item)
      } else if (d.loaded) {
        // 长文本已经展开过：重新取全文
        loadFull(key)
      } else {
        d.title = item.title ?? ''
        d.syncedTitle = d.title
        d.version = item.version
      }
    }
    for (const key of Object.keys(drafts)) {
      if (present.has(key)) continue
      if (isDirty(drafts[key])) toast.error('有一段正在编辑的文本已在别处删除或移出，未保存的修改无法保存')
      delete drafts[key]
    }
  }

  /** 主动删除时先丢掉草稿，不触发「已在别处删除」的提示 */
  function forget(key) {
    delete drafts[String(key)]
  }

  /** overwrite：冲突后用户选了「仍然覆盖」，不带版本号直接保存 */
  async function save(key, { overwrite = false } = {}) {
    key = String(key)
    const d = drafts[key]
    if (!d || d.saving || !d.loaded) return false
    d.saving = true
    // 保存的是点击时的内容：请求期间继续输入的字不在其中，保存后仍算未保存
    const title = d.title
    const content = d.content
    let conflict = false
    try {
      const result = await saveItem(key, { title, content, base_version: overwrite ? null : d.version })
      const current = drafts[key]
      if (!current) return true
      current.syncedTitle = result.title ?? ''
      current.syncedContent = result.content ?? ''
      // 后端会去掉标题首尾空白：没有继续改过的标题直接用后端的结果
      if (current.title === title) current.title = current.syncedTitle
      current.version = result.version
      current.remoteChanged = false
      onSaved?.(key, result)
      toast.success('已保存')
      return true
    } catch (error) {
      if (error?.status === 409) conflict = true
      // 401 由请求拦截器处理（登录失效 / 访问码失效），这里不重复提示
      else if (error?.status !== 401) toast.error('保存失败：' + error.message)
    } finally {
      if (drafts[key]) drafts[key].saving = false
    }
    if (conflict) {
      const choice = await askConflict()
      if (choice === 'overwrite') return save(key, { overwrite: true })
      if (choice === 'load') await loadFull(key)
    }
    return false
  }

  return { drafts, isDirty, hasDirty, sync, loadFull, save, forget }
}
