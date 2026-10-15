/**
 * WebSocket 连接管理器
 *
 * 功能：
 * - 自动重连（指数退避，不封顶次数；网络恢复 / 页面回到前台时立即重试）
 * - 心跳保活
 * - 事件监听
 *
 * 心跳只在连接打开时发送，不入队：离线期间积压的 ping 没有意义。
 */
const BASE_RECONNECT_DELAY = 1000
const MAX_RECONNECT_DELAY = 30000
const HEARTBEAT_INTERVAL = 30000
// 服务端以 1008（policy violation）关闭：token 无效、用户被禁用或删除，重连没有意义
const POLICY_VIOLATION = 1008
// 发出 ping 后这么久没收到任何消息，就认为连接已半断（休眠、切网络后 TCP 没有报错）并重建
const PONG_TIMEOUT = 10000

export class WebSocketManager {
  constructor() {
    this.ws = null
    this.url = ''
    this.reconnectTimer = null
    this.heartbeatTimer = null
    this.pongTimer = null
    this.reconnectCount = 0
    this.listeners = {}
    this.isConnected = false
    // 主动断开（登出）后不再自动重连
    this.manualClose = false
    // 本标签页的 token：重连只用它，不读 localStorage（其他标签页换账号会改写 localStorage）
    this.token = null
    // 服务端判定凭证失效（1008）后不再重连，直到下一次 connect（重新登录）
    this.authFailed = false

    // 网络恢复或页面回到前台时，跳过退避立即重连
    if (typeof window !== 'undefined') {
      const retryNow = () => {
        if (this.manualClose || this.authFailed || !this.token) return
        if (!this.ws) {
          this.reconnectCount = 0
          this.scheduleReconnect(0)
        } else if (this.isConnected) {
          // 连接看起来正常：休眠、切网络后它可能已半断（浏览器还没察觉），探测一次，
          // 收不到回应就重建。连接正在建立（CONNECTING）时不处理，不要把它拆掉重来
          this.probe()
        }
      }
      window.addEventListener('online', retryNow)
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') retryNow()
      })
    }
  }

  /**
   * 连接 WebSocket
   */
  connect(token) {
    // 已有连接先彻底断开，避免同时存在两条连接、旧连接的 onclose 误停新连接的心跳
    this.teardown()
    this.manualClose = false
    this.authFailed = false
    this.token = token

    // 根据当前协议选择 ws:// 或 wss://
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    // token 不放 URL（会进 access log），通过子协议传递；服务端只回选 clipsync.v1
    this.url = `${protocol}//${host}/ws`

    let ws
    try {
      ws = new WebSocket(this.url, ['clipsync.v1', `bearer.${token}`])
    } catch (error) {
      console.error('[WS] 连接失败:', error)
      this.scheduleReconnect()
      return
    }
    this.ws = ws
    let opened = false

    ws.onopen = () => {
      opened = true
      this.isConnected = true
      this.reconnectCount = 0
      this.startHeartbeat()
      this.emit('open')
    }

    ws.onmessage = (event) => {
      // 收到任何消息都说明连接还活着
      this.clearPongTimer()
      let data
      try {
        data = JSON.parse(event.data)
      } catch (error) {
        console.error('[WS] 消息解析失败:', error)
        return
      }
      if (data.type === 'pong') return

      this.emit('message', data)
      if (data.type) {
        this.emit(data.type, data.data)
      }
    }

    ws.onerror = (error) => {
      this.emit('error', error)
    }

    ws.onclose = (event) => {
      // 只处理当前连接的关闭事件；被替换掉的旧连接晚到的 onclose 直接忽略
      if (this.ws !== ws) return
      this.ws = null
      this.isConnected = false
      this.stopHeartbeat()
      this.emit('close', event)

      if (this.manualClose) return
      if (event.code === POLICY_VIOLATION) {
        // 凭证失效或账号被禁用：停止重连，交给上层处理（如跳转登录）
        this.authFailed = true
        this.emit('auth_failed', event)
        return
      }
      // 握手阶段被服务端拒绝时浏览器只给 1006，与服务器不可达无法区分：
      // 通知上层去确认会话（失效则登出，从而停止重连），这里照常退避重连
      if (!opened) this.emit('handshake_failed', event)
      this.scheduleReconnect()
    }
  }

  /**
   * 发送消息（仅在连接打开时发送，离线时丢弃并返回 false）
   */
  send(data) {
    if (this.isConnected && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
      return true
    }
    return false
  }

  /**
   * 开始心跳
   */
  startHeartbeat() {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => this.probe(), HEARTBEAT_INTERVAL)
  }

  /**
   * 停止心跳
   */
  stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
    this.clearPongTimer()
  }

  /**
   * 发一个 ping 并等回应：PONG_TIMEOUT 内没有收到任何消息，说明连接已半断，重建它。
   * 已经有等待中的探测时不重置计时，保留最早的截止时间
   */
  probe() {
    if (!this.send({ type: 'ping' }) || this.pongTimer) return
    this.pongTimer = setTimeout(() => {
      this.pongTimer = null
      this.rebuild()
    }, PONG_TIMEOUT)
  }

  clearPongTimer() {
    if (this.pongTimer) {
      clearTimeout(this.pongTimer)
      this.pongTimer = null
    }
  }

  /**
   * 拆掉当前连接并立即重连（重连成功后各页面订阅的 open 事件会补拉数据）
   */
  rebuild() {
    if (this.manualClose || this.authFailed || !this.token) return
    this.teardown()
    this.reconnectCount = 0
    this.scheduleReconnect(0)
  }

  /**
   * 安排重连：指数退避（1s、2s、4s…，最长 30s），不封顶次数
   */
  scheduleReconnect(delay) {
    if (this.manualClose || this.authFailed) return
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)

    const wait = delay ?? Math.min(BASE_RECONNECT_DELAY * 2 ** this.reconnectCount, MAX_RECONNECT_DELAY)
    this.reconnectCount++

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (this.token && !this.manualClose && !this.authFailed) {
        this.connect(this.token)
      }
    }, wait)
  }

  /**
   * 关闭当前连接并清理定时器，不改变 manualClose
   */
  teardown() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.stopHeartbeat()

    if (this.ws) {
      const ws = this.ws
      this.ws = null
      // 先解绑回调，旧连接关闭时不会再触发重连或停掉新连接的心跳
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      try {
        ws.close()
      } catch {
        // 已关闭的连接忽略
      }
    }
    this.isConnected = false
  }

  /**
   * 主动断开（登出时调用），不再自动重连
   */
  disconnect() {
    this.manualClose = true
    this.teardown()
    this.reconnectCount = 0
    this.token = null
  }

  /**
   * 监听事件
   */
  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = []
    }
    this.listeners[event].push(callback)
  }

  /**
   * 移除事件监听
   */
  off(event, callback) {
    if (!this.listeners[event]) return

    if (callback) {
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback)
    } else {
      delete this.listeners[event]
    }
  }

  /**
   * 触发事件
   */
  emit(event, data) {
    if (!this.listeners[event]) return

    this.listeners[event].forEach(callback => {
      try {
        callback(data)
      } catch (error) {
        console.error(`[WS] 事件 ${event} 处理失败:`, error)
      }
    })
  }
}

// 登录用户共用的单例；快速访问页另建一个实例（stores/quick.js），两者互不影响
export default new WebSocketManager()
