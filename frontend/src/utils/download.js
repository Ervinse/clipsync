/**
 * 把下载得到的 Blob 交给浏览器保存（登录下载与快速访问下载共用）
 */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || 'file'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  // 延迟释放，确保浏览器已开始下载
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}

/**
 * 带进度的 blob 下载（文件页、管理后台与快速访问页共用；下载要带凭证，不能用裸 <a href>）。
 * downloads 是 { [fileId]: { loaded, total } } 的响应式对象：下载期间写入进度，结束后删除；
 * 同一个文件正在下载时直接返回，不重复发起（大文件要收完才弹出保存，期间用户容易反复点）。
 * request(onProgress) 发出请求并返回 Blob；出错时向外抛出，由调用方提示
 */
export async function downloadWithProgress(downloads, file, request) {
  if (downloads[file.id]) return
  downloads[file.id] = { loaded: 0, total: file.size || 0 }
  try {
    const blob = await request((event) => {
      const current = downloads[file.id]
      if (!current) return
      current.loaded = event.loaded
      current.total = event.total || file.size || 0
    })
    saveBlob(blob, file.original_name)
  } finally {
    delete downloads[file.id]
  }
}
