/**
 * 文件管理状态
 */
import { defineStore } from 'pinia'
import api from '../api'
import ws from '../utils/websocket'
import { useUserStore } from './user'
import { downloadWithProgress } from '../utils/download'

export const useFilesStore = defineStore('files', {
  state: () => ({
    files: [],
    uploadProgress: {},
    isLoading: false,
    // 放在 store 而不是页面里：上传期间离开文件页再回来，按钮仍是禁用状态，不会并发开第二个上传
    isUploading: false,
    // 最近一次（非静默）拉取列表失败的原因；任何一次拉取成功都会清空。页面据此区分「没有文件」和「没加载出来」
    loadError: '',
    // 正在下载的文件：{ [fileId]: { loaded, total } }，用于禁用重复点击并显示进度
    downloads: {},
  }),

  getters: {
    // 按时间倒序排列的文件列表
    sortedFiles(state) {
      // created_at 精度只到秒，同一秒上传的文件按 id 倒序兜底，与后端排序一致
      return [...state.files].sort((a, b) =>
        (new Date(b.created_at) - new Date(a.created_at)) || (b.id - a.id)
      )
    },

    totalFiles(state) {
      return state.files.length
    },

    // 总存储使用量
    totalSize(state) {
      return state.files.reduce((sum, file) => sum + (file.size || 0), 0)
    },
  },

  actions: {
    /**
     * 获取文件列表
     * silent：WS 推送触发的后台刷新不切 isLoading，避免列表闪成加载状态
     */
    async fetchFiles({ silent = false } = {}) {
      // 请求序号：期间又发出了更新的请求（或本地刚删除了文件）时，这次的结果（成功或失败）都作废，
      // 「加载中」由最新的一次收尾；否则晚到的旧列表会让刚删除的文件短暂回到列表里
      const seq = (this._seq = (this._seq || 0) + 1)
      try {
        if (!silent) this.isLoading = true
        // 后端返回 { items, total, used_bytes, reserved_bytes, quota_bytes }
        const data = await api.files.list()
        if (seq !== this._seq) return
        this.files = data?.items || []
        this.loadError = ''
        // 同步配额到用户状态：侧栏与文件页都读 userStore.quota，上传/删除后需要刷新
        const userStore = useUserStore()
        if (userStore.userInfo && data) {
          userStore.userInfo.used_bytes = data.used_bytes
          userStore.userInfo.reserved_bytes = data.reserved_bytes
          userStore.userInfo.quota_bytes = data.quota_bytes
        }
      } catch (error) {
        console.error('获取文件列表失败:', error)
        if (seq !== this._seq) return
        if (!silent) this.loadError = error?.message || '加载失败'
        throw error
      } finally {
        if (seq === this._seq) this.isLoading = false
      }
    },

    /**
     * 分片上传文件
     */
    async uploadFile(file) {
      // 空文件后端会以 422 拒绝（total_size 必须 > 0），提示是英文校验信息：前端先拦下
      if (file.size === 0) {
        throw { message: '不能上传空文件' }
      }
      if (this.isUploading) {
        throw { message: '已有文件正在上传，请等待完成' }
      }
      this.isUploading = true
      // 本次上传的运行标记：退出登录时置为 cancelled（见 abortUploads），循环据此停下，
      // 不再带着已清掉的 token 发请求，也不碰已被重置的 store
      const run = { cancelled: false }
      this._run = run
      const ensureActive = () => {
        if (run.cancelled) throw { message: '上传已取消', cancelled: true }
      }
      let uploadId = null
      try {
        // 1. 初始化上传（分片大小以服务端确认的 chunk_size 为准）
        const initData = await api.files.initUpload({
          original_name: file.name,
          total_size: file.size,
          chunk_size: 1024 * 1024, // 期望 1MB，服务端会按上限裁剪
        })
        uploadId = initData.upload_id
        ensureActive()
        const CHUNK_SIZE = initData.chunk_size
        const totalChunks = initData.total_chunks

        this.uploadProgress[uploadId] = {
          filename: file.name,
          current: 0,
          total: totalChunks,
          percentage: 0,
        }

        // 2. 分片上传
        for (let i = 0; i < totalChunks; i++) {
          const start = i * CHUNK_SIZE
          const end = Math.min(start + CHUNK_SIZE, file.size)
          const chunk = file.slice(start, end)

          await api.files.uploadChunk(uploadId, i, chunk)
          ensureActive()

          this.uploadProgress[uploadId].current = i + 1
          this.uploadProgress[uploadId].percentage = Math.round(
            ((i + 1) / totalChunks) * 100
          )
        }

        // 3. 完成上传（服务端正在合并：此后页面被关闭也不再发取消，见文件末尾的 pagehide 处理）
        this.uploadProgress[uploadId].completing = true
        const result = await api.files.completeUpload(uploadId)
        // 合并期间退出了登录：文件已入库，但没有 token 可用，不刷新列表
        if (run.cancelled) return result

        // 文件已入库：刷新列表失败不能算上传失败（否则会取消会话并提示失败，用户重试得到重复文件）。
        // 失败时列表由随后到达的 file_added 推送或手动刷新补上
        await this.fetchFiles().catch(() => {})

        return result
      } catch (error) {
        console.error('文件上传失败:', error)
        // 退出登录导致的中断：会话已在退出前取消（或没有 token 可用），不再发请求
        if (run.cancelled) throw error
        // 中途失败：取消会话，立即释放其占用的配额；取消本身失败（如会话已不存在）忽略
        if (uploadId) {
          await api.files.cancelUpload(uploadId).catch(() => {})
          this.fetchFiles({ silent: true }).catch(() => {})
        }
        throw error
      } finally {
        // 成功或失败都清除进度，避免失败后进度条残留
        if (uploadId) delete this.uploadProgress[uploadId]
        // 只收尾自己这一次：退出登录后重新登录开始的新上传不能被旧循环的 finally 重置
        if (this._run === run) {
          this._run = null
          this.isUploading = false
        }
      }
    },

    /** 停止进行中的上传循环（退出登录时调用）；不发请求，会话的取消见 cancelActiveUploads */
    abortUploads() {
      if (this._run) this._run.cancelled = true
    },

    /**
     * 退出登录前调用（此时 token 还在）：取消进行中的上传会话，立即释放配额，并停止上传循环。
     * 已进入「完成上传」阶段的不取消：服务端可能正在合并，取消会让这个文件丢失
     */
    async cancelActiveUploads() {
      const ids = Object.entries(this.uploadProgress)
        .filter(([, progress]) => !progress.completing)
        .map(([id]) => id)
      this.abortUploads()
      await Promise.all(ids.map((id) => api.files.cancelUpload(id).catch(() => {})))
    },

    /** 设置访问码后就地更新列表项，不必等推送 */
    patchFile(id, fields) {
      const item = this.files.find((f) => f.id === id)
      if (item) Object.assign(item, fields)
    },

    /**
     * 删除文件
     */
    async deleteFile(fileId) {
      try {
        await api.files.delete(fileId)
        this._seq = (this._seq || 0) + 1 // 删除之前发出的列表请求作废
        this.files = this.files.filter(f => f.id !== fileId)
      } catch (error) {
        console.error('删除文件失败:', error)
        throw error
      }
      // 删除已成功：再静默拉一次，同步配额；刷新失败不影响删除结果
      await this.fetchFiles({ silent: true }).catch(() => {})
    },

    /**
     * 监听 WebSocket：其他终端上传、删除文件或改了访问码后刷新列表
     * 后端推送只带 id 等轻量信号，收到后重新拉取列表，保证与服务端一致；
     * 连接（重新）建立时也补拉一次，断线期间的变更不会漏掉
     */
    setupWebSocket() {
      if (this._onFilesChanged) return
      this._onFilesChanged = () => {
        this.fetchFiles({ silent: true }).catch(() => {})
      }
      ws.on('file_added', this._onFilesChanged)
      ws.on('file_deleted', this._onFilesChanged)
      ws.on('access_codes_changed', this._onFilesChanged)
      ws.on('open', this._onFilesChanged)
    },

    /**
     * 清理监听器
     */
    cleanupWebSocket() {
      if (this._onFilesChanged) {
        ws.off('file_added', this._onFilesChanged)
        ws.off('file_deleted', this._onFilesChanged)
        ws.off('access_codes_changed', this._onFilesChanged)
        ws.off('open', this._onFilesChanged)
        this._onFilesChanged = null
      }
    },

    /**
     * 下载文件
     */
    async downloadFile(file) {
      await downloadWithProgress(this.downloads, file, (onProgress) => api.files.download(file.id, onProgress))
    },
  },
})

// 上传中刷新或关闭页面：服务器上的上传会话会一直占着配额，直到过期（默认 24 小时）。
// beforeunload 先让用户确认；确认离开后 pagehide 里用 keepalive 请求（页面销毁后浏览器仍会发出）尽力取消会话。
// 已进入「完成上传」阶段的不取消：服务端可能正在合并，取消会让这个文件丢失。
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', (event) => {
    if (!useFilesStore().isUploading) return
    event.preventDefault()
    event.returnValue = ''
  })

  window.addEventListener('pagehide', (event) => {
    // persisted 为 true 表示页面进了往返缓存、之后可能原样恢复，上传还在继续
    if (event.persisted) return
    const filesStore = useFilesStore()
    const token = useUserStore().token
    if (!filesStore.isUploading || !token) return
    for (const [uploadId, progress] of Object.entries(filesStore.uploadProgress)) {
      if (progress.completing) continue
      fetch(`/api/files/upload/${encodeURIComponent(uploadId)}`, {
        method: 'DELETE',
        keepalive: true,
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {})
    }
  })
}
