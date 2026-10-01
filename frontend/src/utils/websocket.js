/**
 * WebSocket 连接管理器
 *
 * 功能：
 * - 自动重连
 * - 心跳保活
 * - 消息队列
 * - 事件监听
 */
class WebSocketManager {
  constructor() {
    this.ws = null
    this.url = ''
    this.reconnectTimer = null
    this.heartbeatTimer = null
    this.reconnectCount = 0
    this.maxReconnectCount = 5
    this.reconnectDelay = 3000
    this.heartbeatInterval = 30000
    this.listeners = {}
    this.messageQueue = []
    this.isConnected = false
  }

  /**
   * 连接 WebSocket
   */
  connect(token) {
    // 根据当前协议选择 ws:// 或 wss://
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    // token 不放 URL（会进 access log），通过子协议传递；服务端只回选 clipsync.v1
    this.url = `${protocol}//${host}/ws`

    try {
      this.ws = new WebSocket(this.url, ['clipsync.v1', `bearer.${token}`])

      this.ws.onopen = () => {
        console.log('[WS] 已连接')
        this.isConnected = true
        this.reconnectCount = 0
        this.startHeartbeat()
        this.flushMessageQueue()
        this.emit('open')
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          console.log('[WS] 收到消息:', data)

          // 心跳响应
          if (data.type === 'pong') {
            return
          }

          // 分发事件
          this.emit('message', data)
          if (data.type) {
            this.emit(data.type, data.data)
          }
        } catch (error) {
          console.error('[WS] 消息解析失败:', error)
        }
      }

      this.ws.onerror = (error) => {
        console.error('[WS] 连接错误:', error)
        this.emit('error', error)
      }

      this.ws.onclose = () => {
        console.log('[WS] 连接关闭')
        this.isConnected = false
        this.stopHeartbeat()
        this.emit('close')
        this.attemptReconnect()
      }
    } catch (error) {
      console.error('[WS] 连接失败:', error)
      this.attemptReconnect()
    }
  }

  /**
   * 发送消息
   */
  send(data) {
    if (this.isConnected && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    } else {
      // 离线时加入队列
      this.messageQueue.push(data)
    }
  }

  /**
   * 刷新消息队列
   */
  flushMessageQueue() {
    while (this.messageQueue.length > 0) {
      const data = this.messageQueue.shift()
      this.send(data)
    }
  }

  /**
   * 开始心跳
   */
  startHeartbeat() {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: 'ping' })
    }, this.heartbeatInterval)
  }

  /**
   * 停止心跳
   */
  stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  /**
   * 尝试重连
   */
  attemptReconnect() {
    if (this.reconnectCount >= this.maxReconnectCount) {
      console.log('[WS] 达到最大重连次数，停止重连')
      this.emit('reconnect_failed')
      return
    }

    this.reconnectCount++
    console.log(`[WS] ${this.reconnectDelay}ms 后尝试第 ${this.reconnectCount} 次重连...`)

    this.reconnectTimer = setTimeout(() => {
      const token = localStorage.getItem('access_token')
      if (token) {
        this.connect(token)
      }
    }, this.reconnectDelay)
  }

  /**
   * 断开连接
   */
  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    this.stopHeartbeat()

    if (this.ws) {
      this.ws.close()
      this.ws = null
    }

    this.isConnected = false
    this.reconnectCount = 0
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

// 单例导出
export default new WebSocketManager()
