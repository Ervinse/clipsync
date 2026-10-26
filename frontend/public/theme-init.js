// 渲染前先按本浏览器保存的主题（跟随系统时看系统深浅色）设好 data-theme，规则与 src/utils/theme.js 一致。
// 放在外部文件而不是 index.html 的内联脚本里：Nginx 的 Content-Security-Policy 只允许同源脚本（script-src 'self'）。
// 全局样式随脚本加载，在那之前由 index.html 里的 <style> 兜底底色，深色用户刷新时不会先闪一下白底。
(function () {
  var mode = 'system'
  try {
    mode = localStorage.getItem('theme') || 'system'
  } catch (e) {}
  var dark = mode === 'dark' || (mode !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
})()
