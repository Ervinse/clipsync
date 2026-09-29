/**
 * 文件管理状态
 */
import { defineStore } from 'pinia'
import api from '../api'

export const useFilesStore = defineStore('files', {
  state: () => ({
    files: [],
    uploadProgress: {},
    isLoading: false,
  }),

  getters: {
    // 按时间倒序排列的文件列表
    sortedFiles(state) {
      return [...state.files].sort((a, b) =>
        new Date(b.created_at) - new Date(a.created_at)
      )
    },

    // 总文件数
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
     */
    async fetchFiles() {
      try {
        this.isLoading = true
        const data = await api.files.list()
        this.files = data || []
      } catch (error) {
        console.error('获取文件列表失败:', error)
        throw error
      } finally {
        this.isLoading = false
      }
    },

    /**
     * 分片上传文件
     */
    async uploadFile(file) {
      const CHUNK_SIZE = 1024 * 1024 // 1MB
      const totalChunks = Math.ceil(file.size / CHUNK_SIZE)

      try {
        // 1. 初始化上传
        const initData = await api.files.initUpload({
          filename: file.name,
          total_size: file.size,
          total_chunks: totalChunks,
        })
        const uploadId = initData.upload_id

        // 初始化进度
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

          // 更新进度
          this.uploadProgress[uploadId].current = i + 1
          this.uploadProgress[uploadId].percentage = Math.round(
            ((i + 1) / totalChunks) * 100
          )
        }

        // 3. 完成上传
        const result = await api.files.completeUpload(uploadId)

        // 清除进度
        delete this.uploadProgress[uploadId]

        // 刷新列表
        await this.fetchFiles()

        return result
      } catch (error) {
        console.error('文件上传失败:', error)
        throw error
      }
    },

    /**
     * 删除文件
     */
    async deleteFile(fileId) {
      try {
        await api.files.delete(fileId)
        this.files = this.files.filter(f => f.id !== fileId)
      } catch (error) {
        console.error('删除文件失败:', error)
        throw error
      }
    },

    /**
     * 下载文件
     */
    downloadFile(fileId) {
      const url = api.files.download(fileId)
      const link = document.createElement('a')
      link.href = url
      link.download = ''
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    },
  },
})
