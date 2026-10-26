<script setup>
// 快速访问页：凭「用户名@访问码」进入后，列出该访问码下的云剪切板、文本与文件。
// 文本可以查看与修改（含标题），文件可以下载；不能新建、删除、上传，也看不到、改不了访问码。
// 属主或其他人改了这些内容时经 quickWs 实时刷新；访问码失效时提示并禁止编辑，未保存的内容留在页面上
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, onBeforeRouteLeave } from 'vue-router'
import {
  Save, Download, File, LoaderCircle, TriangleAlert, LogOut, RotateCw, Copy, Inbox,
} from '@lucide/vue'
import api from '../api'
import { useQuickStore } from '../stores'
import { quickWs } from '../stores/quick'
import { createTextDrafts } from '../utils/textDrafts'
import { formatSize, formatDateTime } from '../utils/format'
import { copyText } from '../utils/clipboard'
import { saveBlob } from '../utils/download'
import { confirmDialog } from '../utils/dialog'
import toast from '../utils/toast'
import BrandMark from '../components/BrandMark.vue'
import ThemeToggle from '../components/ThemeToggle.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'
import TextEditorCard from '../components/TextEditorCard.vue'

const router = useRouter()
const quickStore = useQuickStore()

const CLIP = 'clipboard'

const loading = ref(true)
const loadError = ref('')
const items = ref({ clipboard: null, texts: [], files: [] })
// 访问码失效前的完整访问码，失效后仍显示在页头
const fullCode = ref(quickStore.fullCode)

const { drafts, isDirty, hasDirty, sync, loadFull, save } = createTextDrafts({
  fetchFull: (key) => (key === CLIP ? api.quick.getClipboard() : api.quick.getText(key)),
  saveItem: (key, data) => (key === CLIP
    ? api.quick.updateClipboard(data.content, data.base_version)
    : api.quick.updateText(key, data)),
})

const lost = computed(() => quickStore.lost)
const isEmpty = computed(() => !items.value.clipboard && items.value.texts.length === 0 && items.value.files.length === 0)

// 递增序号：之前发出、尚未返回的刷新结果作废。
// 「加载中」由最新的一次刷新收尾：首次加载还没返回时，实时连接建立会触发一次静默刷新，
// 首次加载的结果随之作废，这时要靠静默刷新结束来关掉「加载中」
let seq = 0
const refresh = async ({ silent = false } = {}) => {
  if (!quickStore.token) return
  const mine = ++seq
  if (!silent) loading.value = true
  try {
    const data = await api.quick.items()
    if (mine !== seq) return
    items.value = data
    loadError.value = ''
    const list = data.texts.map((t) => ({ key: t.id, ...t }))
    if (data.clipboard) list.unshift({ key: CLIP, title: '', ...data.clipboard })
    sync(list)
  } catch (error) {
    if (mine !== seq) return
    // 还没加载出内容时失败才显示错误；已有内容时静默刷新失败不打扰。
    // 401 由请求拦截器处理（访问码失效），页面显示失效提示
    if (loading.value && error?.status !== 401) loadError.value = error.message || '加载失败'
  } finally {
    if (mine === seq) loading.value = false
  }
}

const onChanged = () => refresh({ silent: true })

const onBeforeUnload = (event) => {
  if (!hasDirty() || lost.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(async () => {
  if (!quickStore.token) {
    router.replace('/login')
    return
  }
  window.addEventListener('beforeunload', onBeforeUnload)
  // 先挂监听再拉数据：拉取期间的变更不会漏掉；连接（重新）建立时也补拉一次
  quickWs.on('access_items_changed', onChanged)
  quickWs.on('open', onChanged)
  quickStore.connect()
  await refresh()
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  quickWs.off('access_items_changed', onChanged)
  quickWs.off('open', onChanged)
  quickWs.disconnect()
})

// 有未保存的修改时离开（浏览器后退等）先确认；访问码已失效时修改本来也保存不了，不再拦
onBeforeRouteLeave(async () => {
  if (!hasDirty() || lost.value) return true
  return await confirmDialog({
    title: '放弃未保存的修改？',
    message: '有文本还没有保存，离开后会丢失。',
    confirmText: '放弃并离开',
    cancelText: '继续编辑',
    danger: true,
  })
})

// 访问码仍有效时退出先确认，防止误点；有未保存的修改时换成危险提示。
// 访问码已失效（「重新输入」按钮）时本来就用不了，直接回登录页
const handleExit = async () => {
  if (!lost.value) {
    const ok = await confirmDialog(hasDirty()
      ? {
          title: '退出并放弃未保存的修改？',
          message: '有文本还没有保存，退出后会丢失。',
          confirmText: '退出',
          cancelText: '继续编辑',
          danger: true,
        }
      : {
          title: '退出快速访问？',
          message: '退出后需要重新输入访问码才能进入。',
          confirmText: '退出',
        })
    if (!ok) return
  }
  // 先清掉草稿，离开页面时不再触发「未保存」确认
  for (const key of Object.keys(drafts)) delete drafts[key]
  quickStore.logout()
  quickStore.lost = false
  router.push('/login')
}

const copyDraft = (key) => copyText(drafts[key]?.content || '', '已复制')

// 下载：以 blob 方式取回（要带快速访问凭证），期间显示进度
const downloads = ref({})
const downloadText = (file) => {
  const state = downloads.value[file.id]
  if (!state) return ''
  return state.total > 0
    ? `下载中 ${Math.min(100, Math.round((state.loaded / state.total) * 100))}%`
    : '下载中…'
}
const handleDownload = async (file) => {
  if (downloads.value[file.id] || lost.value) return
  downloads.value[file.id] = { loaded: 0, total: file.size || 0 }
  try {
    const blob = await api.quick.downloadFile(file.id, (event) => {
      const current = downloads.value[file.id]
      if (!current) return
      current.loaded = event.loaded
      current.total = event.total || file.size || 0
    })
    saveBlob(blob, file.original_name)
  } catch (error) {
    if (error?.status !== 401) toast.error('下载失败：' + (error.message || '未知错误'))
  } finally {
    delete downloads.value[file.id]
  }
}
</script>

<template>
  <div class="quick">
    <header class="quick-header liquid">
      <BrandMark :size="24" />
      <span class="header-right">
        <ThemeToggle />
        <span class="mono header-code" :title="fullCode">{{ fullCode }}</span>
        <button class="btn btn-secondary btn-sm" @click="handleExit">
          <LogOut :size="14" />
          退出
        </button>
      </span>
    </header>

    <main class="quick-main page-enter">
      <div v-if="lost" class="alert alert-danger lost" role="alert">
        <TriangleAlert />
        <span>
          访问码已失效（被清除、修改、过期，或超过 2 小时），不能再保存或下载。
          页面上还没保存的内容可以先复制出来。
        </span>
        <button class="btn btn-secondary btn-sm" @click="handleExit">重新输入</button>
      </div>

      <LoadingSkeleton v-if="loading" variant="cards" :count="2" />

      <div v-else-if="loadError" class="empty" role="alert">
        <span class="empty-icon"><TriangleAlert :size="20" /></span>
        <p class="empty-title">加载失败</p>
        <p class="empty-text">{{ loadError }}</p>
        <button class="btn btn-secondary" @click="refresh()">
          <RotateCw />
          重试
        </button>
      </div>

      <div v-else-if="isEmpty && !lost" class="empty">
        <span class="empty-icon"><Inbox :size="20" /></span>
        <p class="empty-title">这个访问码下暂时没有内容</p>
      </div>

      <template v-else>
        <section v-if="drafts[CLIP] && items.clipboard" class="block">
          <TextEditorCard
            :draft="drafts[CLIP]"
            :preview="items.clipboard.preview"
            :size="items.clipboard.size"
            :updated-at="items.clipboard.version ? items.clipboard.updated_at : ''"
            heading="云剪切板"
            :readonly="lost"
            @save="save(CLIP)"
            @load-full="loadFull(CLIP)"
          >
            <template #actions>
              <button class="btn btn-secondary btn-sm" :disabled="!drafts[CLIP].loaded" @click="copyDraft(CLIP)">
                <Copy :size="14" />
                复制
              </button>
              <button
                class="btn btn-primary btn-sm"
                :disabled="lost || !drafts[CLIP].loaded || drafts[CLIP].saving || !isDirty(drafts[CLIP])"
                @click="save(CLIP)"
              >
                <LoaderCircle v-if="drafts[CLIP].saving" class="spin" />
                <Save v-else :size="14" />
                保存
              </button>
            </template>
          </TextEditorCard>
        </section>

        <section v-if="items.texts.length" class="block">
          <h2 class="block-title">文本 <span class="block-count">{{ items.texts.length }}</span></h2>
          <div class="stack">
            <template v-for="text in items.texts" :key="text.id">
              <TextEditorCard
                v-if="drafts[text.id]"
                :draft="drafts[text.id]"
                :preview="text.preview"
                :size="text.size"
                :updated-at="text.updated_at"
                :readonly="lost"
                @save="save(text.id)"
                @load-full="loadFull(text.id)"
              >
                <template #actions>
                  <button class="btn btn-secondary btn-sm" :disabled="!drafts[text.id].loaded" @click="copyDraft(text.id)">
                    <Copy :size="14" />
                    复制
                  </button>
                  <button
                    class="btn btn-primary btn-sm"
                    :disabled="lost || !drafts[text.id].loaded || drafts[text.id].saving || !isDirty(drafts[text.id])"
                    @click="save(text.id)"
                  >
                    <LoaderCircle v-if="drafts[text.id].saving" class="spin" />
                    <Save v-else :size="14" />
                    保存
                  </button>
                </template>
              </TextEditorCard>
            </template>
          </div>
        </section>

        <section v-if="items.files.length" class="block">
          <h2 class="block-title">文件 <span class="block-count">{{ items.files.length }}</span></h2>
          <ul class="file-list card">
            <li v-for="file in items.files" :key="file.id" class="file-row">
              <span class="file-icon"><File :size="18" /></span>
              <span class="file-main">
                <span class="file-name" :title="file.original_name">{{ file.original_name }}</span>
                <span class="file-sub">
                  {{ formatSize(file.size) }} · {{ formatDateTime(file.created_at) }}
                  <template v-if="downloads[file.id]"> · {{ downloadText(file) }}</template>
                </span>
              </span>
              <button
                class="btn btn-secondary btn-sm"
                :disabled="lost || !!downloads[file.id]"
                @click="handleDownload(file)"
              >
                <LoaderCircle v-if="downloads[file.id]" class="spin" />
                <Download v-else :size="14" />
                下载
              </button>
            </li>
          </ul>
        </section>
      </template>
    </main>

    <footer class="quick-footer">
      快速访问 · 内容属于 {{ quickStore.ownerUsername || fullCode.split('@')[0] }}，请勿在公共设备上长时间停留
    </footer>
  </div>
</template>

<style scoped>
.quick {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  /* 半透明浅灰：页面光斑从下面透出来 */
  background: var(--color-glass-subtle);
}

.quick-header {
  position: sticky;
  top: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  height: 60px;
  padding: 0 var(--space-6);
  /* 吸顶栏：半透明 + 模糊，往下滚时内容从顶栏下面隐约透出；支持时再加液态折射（style.css 的 .liquid） */
  background: var(--color-topbar-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border-bottom: 1px solid var(--color-border);
  box-shadow: inset 0 1px 0 var(--color-highlight), 0 1px 0 var(--color-glass-rim);
}

.header-right {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.header-code {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quick-main {
  flex: 1;
  width: 100%;
  max-width: 860px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-4);
}

.lost {
  margin-bottom: var(--space-5);
  align-items: center;
}

.lost span {
  flex: 1;
}

.block {
  margin-bottom: var(--space-8);
}

.block-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--color-text);
}

.block-count {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-tertiary);
}

.stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.file-list {
  list-style: none;
  overflow: hidden;
}

.file-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.file-row:last-child {
  border-bottom: none;
}

.file-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}

.file-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.file-name {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-sub {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.quick-footer {
  padding: var(--space-6) var(--space-4);
  text-align: center;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

@media (max-width: 640px) {
  .quick-header {
    padding: 0 var(--space-4);
  }

  .lost {
    flex-wrap: wrap;
  }
}
</style>
