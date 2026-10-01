<script setup>
import { ref, onMounted, computed } from 'vue'
import { useAdminStore, useUserStore } from '../stores'
import { formatDateTime, formatSize } from '../utils/format'
import { copyToClipboard } from '../utils/clipboard'

// 访问权限由路由守卫（meta.requiresAdmin）拦截，后端接口再做最终校验
const adminStore = useAdminStore()
const userStore = useUserStore()

const activeTab = ref('stats')
const showCreateInviteModal = ref(false)
// 邀请码一次性使用，后端只接收 expires_at
const inviteForm = ref({
  expires_in_days: 7,
})

onMounted(async () => {
  // 并行加载，互不影响：任何一个失败都不会阻断其余数据的显示
  // 文件元数据 admin 及以上均可查看（后端 /api/admin/files 同此权限），不含下载入口
  const tasks = [
    ['统计', adminStore.fetchStats()],
    ['用户', adminStore.fetchUsers()],
    ['邀请码', adminStore.fetchInviteCodes()],
    ['文件', adminStore.fetchFiles()],
    ['设置', adminStore.fetchSettings()],
  ]
  const results = await Promise.allSettled(tasks.map(([, p]) => p))
  syncSettingsForm()

  const failed = tasks.filter((_, i) => results[i].status === 'rejected').map(([name]) => name)
  if (failed.length > 0) {
    alert(`部分数据加载失败：${failed.join('、')}`)
  }
})

const stats = computed(() => adminStore.stats || {})

// 系统设置：后端 GET 对 admin 及以上开放，PATCH 仅 superadmin；目前只有这两项存库
const settingsForm = ref({
  registration_enabled: true,
  default_quota_mb: 100,
})
const isSavingSettings = ref(false)

const syncSettingsForm = () => {
  const s = adminStore.settings
  if (!s) return
  settingsForm.value = {
    registration_enabled: s.registration_enabled,
    default_quota_mb: Math.round(s.default_quota_bytes / 1024 / 1024),
  }
}

const handleSaveSettings = async () => {
  if (!userStore.isSuperAdmin) {
    alert('仅超级管理员可修改系统设置')
    return
  }
  const quotaMB = Number(settingsForm.value.default_quota_mb)
  if (!Number.isInteger(quotaMB) || quotaMB < 0) {
    alert('默认配额必须是非负整数（MB）')
    return
  }
  try {
    isSavingSettings.value = true
    await adminStore.updateSettings({
      registration_enabled: settingsForm.value.registration_enabled,
      default_quota_bytes: quotaMB * 1024 * 1024,
    })
    syncSettingsForm()
    alert('系统设置已保存')
  } catch (error) {
    alert('保存失败：' + error.message)
  } finally {
    isSavingSettings.value = false
  }
}

const openCreateInviteModal = () => {
  inviteForm.value = {
    expires_in_days: 7,
  }
  showCreateInviteModal.value = true
}

const handleCreateInvite = async () => {
  try {
    // 0 或空表示永久有效；其余换算为带时区的 ISO 时间
    const days = Number(inviteForm.value.expires_in_days)
    await adminStore.createInviteCode({
      expires_at: days > 0
        ? new Date(Date.now() + days * 86400 * 1000).toISOString()
        : null,
    })
    showCreateInviteModal.value = false
    alert('邀请码创建成功')
  } catch (error) {
    alert('创建失败：' + error.message)
  }
}

const handleDeleteInvite = async (id) => {
  if (!confirm('确定删除此邀请码吗？')) return

  try {
    await adminStore.deleteInviteCode(id)
  } catch (error) {
    alert('删除失败：' + error.message)
  }
}

const handleToggleUserStatus = async (user) => {
  if (!userStore.isSuperAdmin) {
    alert('仅超级管理员可执行此操作')
    return
  }

  try {
    await adminStore.updateUserStatus(user.id, !user.is_active)
  } catch (error) {
    alert('操作失败：' + error.message)
  }
}

const handleUpdateQuota = async (user) => {
  if (!userStore.isSuperAdmin) {
    alert('仅超级管理员可执行此操作')
    return
  }

  const quotaMB = prompt('请输入新配额（MB）', user.quota_bytes / 1024 / 1024)
  if (!quotaMB) return

  try {
    const quotaBytes = parseInt(quotaMB) * 1024 * 1024
    await adminStore.updateUserQuota(user.id, quotaBytes)
  } catch (error) {
    alert('更新失败：' + error.message)
  }
}

const handleDeleteUser = async (user) => {
  if (!userStore.isSuperAdmin) {
    alert('仅超级管理员可执行此操作')
    return
  }

  if (!confirm(`确定删除用户 "${user.username}" 吗？此操作不可撤销。`)) return

  try {
    await adminStore.deleteUser(user.id)
  } catch (error) {
    alert('删除失败：' + error.message)
  }
}

// 后端时间为 naive UTC，formatDateTime 内部按 UTC 解析；空值（如永久有效的邀请码）显示「永久有效」
const formatDate = (value) => formatDateTime(value, '永久有效', false)

// HTTP 部署下 navigator.clipboard 不可用，copyToClipboard 会降级
const copyInviteCode = async (code) => {
  if (await copyToClipboard(code)) {
    alert('邀请码已复制')
  } else {
    prompt('复制失败，请手动复制：', code)
  }
}
</script>

<template>
  <div class="admin-page">
    <div class="page-header">
      <div>
        <h2>管理后台</h2>
        <p>系统管理与监控</p>
      </div>
    </div>

    <div class="tabs">
      <button
        class="tab"
        :class="{ active: activeTab === 'stats' }"
        @click="activeTab = 'stats'"
      >
        📊 统计
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'users' }"
        @click="activeTab = 'users'"
      >
        👥 用户
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'invites' }"
        @click="activeTab = 'invites'"
      >
        🎫 邀请码
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'files' }"
        @click="activeTab = 'files'"
      >
        📁 文件
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'settings' }"
        @click="activeTab = 'settings'"
      >
        ⚙️ 设置
      </button>
    </div>

    <!-- 统计面板 -->
    <div v-if="activeTab === 'stats'" class="tab-content">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon">👥</div>
          <div class="stat-value">{{ stats.total_users || 0 }}</div>
          <div class="stat-label">总用户数</div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">✅</div>
          <div class="stat-value">{{ stats.active_users || 0 }}</div>
          <div class="stat-label">活跃用户</div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">📁</div>
          <div class="stat-value">{{ stats.total_files || 0 }}</div>
          <div class="stat-label">文件总数</div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">💾</div>
          <div class="stat-value">{{ formatSize(stats.total_storage_bytes || 0) }}</div>
          <div class="stat-label">总存储</div>
        </div>
      </div>
    </div>

    <!-- 用户管理 -->
    <div v-if="activeTab === 'users'" class="tab-content">
      <div class="users-table">
        <table>
          <thead>
            <tr>
              <th>用户名</th>
              <th>角色</th>
              <th>配额</th>
              <th>使用</th>
              <th>状态</th>
              <th>注册时间</th>
              <th v-if="userStore.isSuperAdmin">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in adminStore.users" :key="user.id">
              <td>{{ user.username }}</td>
              <td>
                <span class="role-badge" :class="user.role">
                  {{ user.role === 'superadmin' ? '超管' : user.role === 'admin' ? '管理' : '普通' }}
                </span>
              </td>
              <td>{{ formatSize(user.quota_bytes) }}</td>
              <td>{{ formatSize(user.used_bytes || 0) }}</td>
              <td>
                <span class="status-badge" :class="{ active: user.is_active }">
                  {{ user.is_active ? '正常' : '禁用' }}
                </span>
              </td>
              <td>{{ formatDate(user.created_at) }}</td>
              <td v-if="userStore.isSuperAdmin">
                <div class="action-buttons">
                  <button class="btn-icon" title="修改配额" @click="handleUpdateQuota(user)">
                    💾
                  </button>
                  <button
                    class="btn-icon"
                    :title="user.is_active ? '禁用' : '启用'"
                    @click="handleToggleUserStatus(user)"
                  >
                    {{ user.is_active ? '🚫' : '✅' }}
                  </button>
                  <button
                    v-if="user.role !== 'superadmin'"
                    class="btn-icon btn-danger"
                    title="删除"
                    @click="handleDeleteUser(user)"
                  >
                    🗑️
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 邀请码管理 -->
    <div v-if="activeTab === 'invites'" class="tab-content">
      <div class="invite-header">
        <button class="btn-primary" @click="openCreateInviteModal">
          + 创建邀请码
        </button>
      </div>

      <div class="invites-grid">
        <div
          v-for="invite in adminStore.inviteCodes"
          :key="invite.id"
          class="invite-card"
        >
          <div class="invite-code">{{ invite.code }}</div>
          <div class="invite-info">
            <div class="info-row">
              <span>状态</span>
              <span>{{ invite.used_at ? '已使用' : '未使用' }}</span>
            </div>
            <div class="info-row">
              <span>过期时间</span>
              <span>{{ formatDate(invite.expires_at) }}</span>
            </div>
            <div v-if="invite.used_by" class="info-row">
              <span>使用者</span>
              <span>{{ invite.used_by_username || invite.used_by }}</span>
            </div>
          </div>
          <div class="invite-actions">
            <button class="btn-secondary" @click="copyInviteCode(invite.code)">
              复制
            </button>
            <button class="btn-danger" @click="handleDeleteInvite(invite.id)">
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 文件元数据（admin 及以上；安全红线：只展示元数据，无下载入口） -->
    <div v-if="activeTab === 'files'" class="tab-content">
      <div class="files-table">
        <table>
          <thead>
            <tr>
              <th>文件名</th>
              <th>大小</th>
              <th>用户</th>
              <th>上传时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="file in adminStore.files" :key="file.id">
              <td>{{ file.original_name }}</td>
              <td>{{ formatSize(file.size) }}</td>
              <td>{{ file.username }}</td>
              <td>{{ formatDate(file.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 系统设置（admin 只读，superadmin 可修改；后端为最终防线） -->
    <div v-if="activeTab === 'settings'" class="tab-content">
      <div class="settings-panel">
        <div v-if="!userStore.isSuperAdmin" class="settings-hint">
          仅超级管理员可修改系统设置，当前为只读。
        </div>

        <div class="form-group">
          <label class="checkbox-label">
            <input
              v-model="settingsForm.registration_enabled"
              type="checkbox"
              :disabled="!userStore.isSuperAdmin"
            />
            开放注册（关闭后即使持有有效邀请码也无法注册）
          </label>
        </div>

        <div class="form-group">
          <label>新用户默认配额（MB）</label>
          <input
            v-model.number="settingsForm.default_quota_mb"
            type="number"
            min="0"
            :disabled="!userStore.isSuperAdmin"
          />
          <div class="form-hint">只影响之后注册的用户；已有用户的配额在「用户」页单独修改</div>
        </div>

        <div class="form-hint">
          单文件上限、分片大小、历史保留条数等由 backend/.env 配置，需重启后端生效，不在此修改。
        </div>

        <div v-if="userStore.isSuperAdmin" class="modal-actions">
          <button class="btn-primary" :disabled="isSavingSettings" @click="handleSaveSettings">
            {{ isSavingSettings ? '保存中...' : '保存设置' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 创建邀请码弹窗 -->
    <div v-if="showCreateInviteModal" class="modal-overlay" @click="showCreateInviteModal = false">
      <div class="modal-content" @click.stop>
        <h3>创建邀请码</h3>

        <div class="form-group">
          <label>有效期（天）</label>
          <input
            v-model.number="inviteForm.expires_in_days"
            type="number"
            min="0"
            placeholder="7"
          />
          <div class="form-hint">0 表示永久有效</div>
        </div>

        <div class="modal-actions">
          <button class="btn-secondary" @click="showCreateInviteModal = false">
            取消
          </button>
          <button class="btn-primary" @click="handleCreateInvite">
            创建
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-page {
  padding: 2rem;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 2rem;
}

.page-header h2 {
  font-size: 1.75rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 0.5rem;
}

.page-header p {
  font-size: 0.95rem;
  color: #94A3B8;
}

.tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 2rem;
  border-bottom: 1px solid #334155;
}

.tab {
  padding: 0.875rem 1.5rem;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #94A3B8;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.tab:hover {
  color: #CBD5E1;
}

.tab.active {
  color: #38BDF8;
  border-bottom-color: #38BDF8;
}

.tab-content {
  animation: fadeIn 0.3s;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1.5rem;
}

.stat-card {
  padding: 2rem;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  text-align: center;
}

.stat-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.stat-value {
  font-size: 2rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 0.5rem;
}

.stat-label {
  font-size: 0.9rem;
  color: #94A3B8;
}

.users-table,
.files-table {
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  overflow: hidden;
}

table {
  width: 100%;
  border-collapse: collapse;
}

thead {
  background: #0F172A;
}

th {
  padding: 1rem;
  text-align: left;
  font-size: 0.85rem;
  font-weight: 600;
  color: #94A3B8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

td {
  padding: 1rem;
  border-top: 1px solid #334155;
  color: #CBD5E1;
  font-size: 0.9rem;
}

.role-badge,
.status-badge {
  padding: 0.25rem 0.625rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 600;
}

.role-badge.superadmin {
  background: rgba(249, 115, 22, 0.15);
  color: #F97316;
  border: 1px solid rgba(249, 115, 22, 0.3);
}

.role-badge.admin {
  background: rgba(56, 189, 248, 0.15);
  color: #38BDF8;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.role-badge.user {
  background: rgba(148, 163, 184, 0.15);
  color: #94A3B8;
  border: 1px solid #475569;
}

.status-badge {
  background: rgba(239, 68, 68, 0.15);
  color: #FCA5A5;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.status-badge.active {
  background: rgba(34, 211, 238, 0.15);
  color: #22D3EE;
  border: 1px solid rgba(34, 211, 238, 0.3);
}

.action-buttons {
  display: flex;
  gap: 0.5rem;
}

.btn-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(148, 163, 184, 0.1);
  border: 1px solid #334155;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 1rem;
}

.btn-icon:hover {
  background: rgba(56, 189, 248, 0.15);
  border-color: #38BDF8;
}

.btn-icon.btn-danger:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.5);
}

.invite-header {
  margin-bottom: 1.5rem;
}

.invites-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1.5rem;
}

.invite-card {
  padding: 1.5rem;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
}

.invite-code {
  padding: 0.75rem;
  background: #0F172A;
  border: 1px solid #334155;
  border-radius: 8px;
  font-family: 'IBM Plex Sans', monospace;
  font-size: 1.1rem;
  font-weight: 600;
  color: #38BDF8;
  text-align: center;
  margin-bottom: 1rem;
}

.invite-info {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  margin-bottom: 1rem;
}

.info-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
}

.info-row span:first-child {
  color: #94A3B8;
}

.info-row span:last-child {
  color: #CBD5E1;
  font-weight: 500;
}

.invite-actions {
  display: flex;
  gap: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid #334155;
}

.btn-primary,
.btn-secondary,
.btn-danger {
  padding: 0.625rem 1.25rem;
  border: none;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: #38BDF8;
  color: #0F172A;
}

.btn-primary:hover {
  background: #22D3EE;
}

.btn-secondary {
  flex: 1;
  background: rgba(148, 163, 184, 0.1);
  color: #CBD5E1;
  border: 1px solid #334155;
}

.btn-secondary:hover {
  background: rgba(148, 163, 184, 0.15);
}

.btn-danger {
  flex: 1;
  background: rgba(239, 68, 68, 0.1);
  color: #FCA5A5;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.2);
}

/* 弹窗样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  width: 90%;
  max-width: 420px;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 2rem;
}

.modal-content h3 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 1.5rem;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  font-size: 0.9rem;
  font-weight: 500;
  color: #CBD5E1;
  margin-bottom: 0.5rem;
}

.form-group input {
  width: 100%;
  padding: 0.75rem 1rem;
  background: #0F172A;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #F8FAFC;
  font-size: 0.95rem;
}

.form-group input:focus {
  outline: none;
  border-color: #38BDF8;
}

.form-hint {
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: #64748B;
}

.modal-actions {
  display: flex;
  gap: 1rem;
  justify-content: flex-end;
  margin-top: 2rem;
}

.settings-panel {
  max-width: 560px;
  padding: 1.5rem;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.settings-hint {
  padding: 0.75rem 1rem;
  background: rgba(250, 204, 21, 0.1);
  border: 1px solid rgba(250, 204, 21, 0.4);
  border-radius: 8px;
  color: #FACC15;
  font-size: 0.9rem;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}
</style>