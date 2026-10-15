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
