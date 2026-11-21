<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({
  html: false,
  breaks: true
}).disable('image')

const toolNames = {
  query_weather: '查询天气',
  save_note: '保存笔记',
  maps_geo: '查询地址坐标',
  maps_text_search: '搜索地点',
  maps_direction_walking: '查询步行路线',
  maps_direction_driving: '查询驾车路线',
  maps_direction_transit_integrated: '查询公交路线',
  maps_schema_navi: '生成高德导航链接'
}
const toolStatuses = { ok: '成功', error: '失败', unavailable: '不可用', blocked: '已拦截' }
const messages = ref([])
const health = ref(null)
const mapReady = computed(() => health.value?.services?.amap === 'ready')
const prompts = computed(() => {
  const examples = ['查北京天气并保存摘要', '查上海天气，不要保存', '保存：出门带伞']
  if (mapReady.value) examples.push('查北京市天安门到王府井的步行路线')
  return examples
})
const healthLabel = ref('连接后端中')
const threadId = ref(null)
const userInput = ref('')
const isLoading = ref(false)
const chatContainer = ref(null)

onMounted(async () => {
  try {
    const response = await fetch('/health')
    if (!response.ok) throw new Error()
    health.value = await response.json()
    healthLabel.value = health.value.mode === 'qwen' ? health.value.model : '本地演示'
  } catch {
    healthLabel.value = '后端连接失败'
  }
})

function newChat() {
  threadId.value = null
  messages.value = []
  userInput.value = ''
}

function navigationLink(trace) {
  const step = trace?.find(item => item.tool === 'maps_schema_navi' && item.status === 'ok')
  return step?.content.match(/(?:amapuri:\/\/navi\?|https:\/\/uri\.amap\.com\/navigation\?)[^\s"'<>]+/)?.[0]
}

const scrollToBottom = async () => {
  await nextTick()
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

const sendMessage = async (prompt = userInput.value) => {
  const content = prompt.trim()
  if (!content || isLoading.value) return

  messages.value.push({ role: 'user', content })
  userInput.value = ''
  isLoading.value = true
  await scrollToBottom()

  try {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: content, thread_id: threadId.value })
    })
    const data = await response.json()
    if (!response.ok) {
      if (response.status === 404) threadId.value = null
      throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请稍后重试。')
    }
    threadId.value = data.thread_id
    messages.value.push({ role: 'ai', content: data.content, trace: data.trace })
  } catch (error) {
    const content = error instanceof SyntaxError || error instanceof TypeError
      ? '请求失败，请确认后端已启动。'
      : error.message
    messages.value.push({ role: 'ai', content })
  } finally {
    isLoading.value = false
    scrollToBottom()
  }
}

const renderMarkdown = (text) => {
  return md.render(text || '')
}
</script>

<template>
  <div class="chat-wrapper">
    <div class="chat-container">
      <!-- 顶部栏 -->
      <div class="chat-header">
        <div class="header-content">
          <div class="status-dot" :class="{ offline: !health }"></div>
          <h2>MCP 多工具助手</h2>
        </div>
        <div class="header-actions">
          <span class="header-subtitle">{{ healthLabel }}</span>
          <button type="button" class="secondary-btn" @click="newChat" :disabled="isLoading">新会话</button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div class="messages" ref="chatContainer" role="log" aria-label="会话消息">
        <div v-if="!messages.length" class="intro">
          <h3>{{ mapReady ? '查询天气、保存笔记、规划路线' : '查询天气，保存笔记' }}</h3>
          <p v-if="health?.weather_mode === 'fixture'">当前使用演示天气数据。回复下方可查看每次工具调用的结果与耗时。</p>
          <p v-else>回复下方可查看每次工具调用的结果与耗时。</p>
        </div>
        <div v-for="(msg, index) in messages" :key="index" :class="['message-row', msg.role]">
          <div class="avatar">
            <span v-if="msg.role === 'ai'">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2 2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M4 11a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7z"/><path d="M9 16a2 2 0 1 0 4 0 2 2 0 1 0-4 0"/><path d="M15 7v2"/><path d="M9 7v2"/></svg>
            </span>
            <span v-else>
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </span>
          </div>
          <div class="message-bubble">
            <div v-if="msg.role === 'ai'" class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
            <div v-else>{{ msg.content }}</div>
            <a v-if="navigationLink(msg.trace)" :href="navigationLink(msg.trace)" class="navigation-link">
              在高德地图打开导航
            </a>
            <details v-if="msg.trace?.length" open class="trace">
              <summary>工具调用 · {{ msg.trace.length }} 次</summary>
              <ol>
                <li v-for="(item, callIndex) in msg.trace" :key="callIndex" class="trace-row">
                  <span>{{ toolNames[item.tool] || item.tool }}</span>
                  <code>{{ item.service }}</code>
                  <span class="trace-status" :class="item.status">{{ toolStatuses[item.status] || item.status }}</span>
                  <span class="duration">{{ item.elapsed_ms }} ms</span>
                </li>
              </ol>
            </details>
          </div>
        </div>

        <!-- 加载状态 -->
        <div v-if="isLoading" class="loading-indicator">
          <div class="dot"></div>
          <div class="dot"></div>
          <div class="dot"></div>
          <span>正在处理请求</span>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="input-area">
        <div class="examples" aria-label="示例指令">
          <button v-for="prompt in prompts" :key="prompt" type="button" class="secondary-btn"
            :disabled="isLoading" @click="sendMessage(prompt)">{{ prompt }}</button>
        </div>
        <div class="input-box">
          <input
            v-model="userInput"
            @keydown.enter="!$event.isComposing && sendMessage()"
            placeholder="输入消息"
            aria-label="输入消息"
            maxlength="4000"
            :disabled="isLoading"
          />
          <button type="button" @click="sendMessage()" :disabled="isLoading || !userInput.trim()"
            class="send-btn" aria-label="发送">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 整体容器 */
.chat-wrapper {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  width: 100%;
  padding: 20px;
  box-sizing: border-box;
  /* 浅色网格背景 */
  background-image:
    linear-gradient(rgba(14, 165, 233, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(14, 165, 233, 0.05) 1px, transparent 1px);
  background-size: 40px 40px;
  background-position: center center;
}

.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 850px;
  width: 100%;
  max-width: 950px;
  /* 浅色玻璃拟态：高亮白底 + 模糊 */
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 24px;
  box-shadow:
    0 20px 40px rgba(0, 0, 0, 0.08), /* 柔和的阴影 */
    0 0 0 1px rgba(255, 255, 255, 0.5) inset; /* 内发光增强质感 */
  overflow: hidden;
  transition: all 0.3s ease;
  position: relative;
}

/* 顶部装饰线 - 保留但变浅 */
.chat-container::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #38bdf8, #818cf8);
  opacity: 1;
}

/* 头部样式 */
.chat-header {
  padding: 20px 28px;
  background: rgba(255, 255, 255, 0.9);
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
  display: flex;
  justify-content: space-between;
  align-items: center;
  z-index: 10;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-dot {
  width: 8px;
  height: 8px;
  background: #10b981; /* 绿色代表在线，更友好 */
  border-radius: 50%;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { opacity: 0.6; transform: scale(0.95); }
  50% { opacity: 1; transform: scale(1.05); }
  100% { opacity: 0.6; transform: scale(0.95); }
}

.chat-header h2 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: #1e293b; /* 深灰黑 */
  letter-spacing: -0.5px;
  font-family: 'Inter', sans-serif;
}

.header-subtitle {
  font-size: 0.75rem;
  color: #64748b;
  font-weight: 600;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 20px; /* 圆润标签 */
  border: 1px solid #e2e8f0;
}

.header-actions, .examples {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.examples { margin-bottom: 12px; }
.navigation-link { display: inline-block; margin-top: 8px; color: #075985; }
.status-dot.offline { background: #94a3b8; box-shadow: none; }
.secondary-btn {
  color: #075985;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 0.8rem;
  cursor: pointer;
}
.secondary-btn:hover:not(:disabled) { background: #e0f2fe; }
.secondary-btn:disabled { opacity: 0.55; cursor: default; }
.intro h3 { color: #1e293b; font-size: 1.45rem; margin: 0; }
.intro p { color: #475569; margin: 6px 0 0; }
.trace { margin-top: 12px; border-top: 1px solid #e2e8f0; padding-top: 8px; font-size: 0.82rem; }
.trace summary { color: #475569; cursor: pointer; }
.trace ol { list-style: none; margin: 6px 0 0; padding: 0; }
.trace-row { display: grid; grid-template-columns: 1fr auto auto auto; align-items: center; gap: 10px; padding: 4px 0; }
.trace-row code, .duration { color: #475569; font-size: 0.76rem; }
.trace-status { color: #9a3412; }
.trace-status.ok { color: #047857; }

/* 消息列表区域 */
.messages {
  flex: 1;
  padding: 32px;
  overflow-y: auto;
  background: transparent;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* 滚动条样式 - 浅色适配 */
.messages::-webkit-scrollbar {
  width: 6px;
}
.messages::-webkit-scrollbar-track {
  background: transparent;
}
.messages::-webkit-scrollbar-thumb {
  background: rgba(203, 213, 225, 0.8);
  border-radius: 3px;
}
.messages::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.8);
}

.message-row {
  display: flex;
  gap: 16px;
  max-width: 85%;
  animation: fadeIn 0.4s cubic-bezier(0.2, 0.8, 0.2, 1);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.message-row.user {
  flex-direction: row-reverse;
  align-self: flex-end;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: #fff;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}

.message-row.ai .avatar {
  background: #fff;
  color: #0ea5e9;
  border: 1px solid #e0f2fe;
}

.message-row.user .avatar {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: #fff;
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.2);
}

.message-bubble {
  padding: 16px 20px;
  border-radius: 16px;
  font-size: 1rem;
  line-height: 1.65;
  position: relative;
  word-break: break-word;
  box-shadow: 0 2px 4px rgba(0,0,0,0.04);
}

.message-row.ai .message-bubble {
  background: #ffffff;
  border: 1px solid #f1f5f9;
  color: #334155;
  border-top-left-radius: 4px;
}

.message-row.user .message-bubble {
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  color: #ffffff;
  border-top-right-radius: 4px;
  box-shadow: 0 8px 16px -4px rgba(14, 165, 233, 0.3); /* 更柔和的彩色阴影 */
}

/* Loading 状态 */
.loading-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  margin-left: 56px;
  color: #64748b;
  font-size: 0.85rem;
  font-family: monospace;
  background: rgba(255,255,255,0.5);
  border-radius: 20px;
  width: fit-content;
}

.dot {
  width: 6px;
  height: 6px;
  background: #38bdf8;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out both;
}

/* 输入区域 */
.input-area {
  padding: 24px 32px;
  background: rgba(255, 255, 255, 0.9);
  border-top: 1px solid rgba(226, 232, 240, 0.6);
}

.input-box {
  display: flex;
  gap: 12px;
  background: #f8fafc;
  padding: 8px;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  transition: all 0.3s ease;
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.03);
}

.input-box:focus-within {
  background: #fff;
  border-color: #38bdf8;
  box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.15), 0 4px 12px rgba(0,0,0,0.05);
}

input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  padding: 12px 16px;
  color: #1e293b;
  font-size: 1rem;
  outline: none;
}

input::placeholder {
  color: #94a3b8;
}

.send-btn {
  background: #0ea5e9;
  flex-shrink: 0;
  border: none;
  color: white;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.2);
}

.send-btn:hover:not(:disabled) {
  background: #0284c7;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
}

.send-btn:disabled {
  background: #e2e8f0;
  color: #94a3b8;
  cursor: not-allowed;
  box-shadow: none;
}

/* Markdown 样式适配浅色模式 */
:deep(.markdown-body) {
  color: #334155;
  font-size: 1rem;
  line-height: 1.7;
}

:deep(.markdown-body p) {
  margin: 0 0 0.65em;
}
:deep(.markdown-body p:last-child) { margin-bottom: 0; }

:deep(.markdown-body a) {
  color: #0284c7;
  text-decoration: none;
  font-weight: 500;
}

:deep(.markdown-body code) {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85em;
  color: #0f172a;
  border: 1px solid #e2e8f0;
}

:deep(.markdown-body pre) {
  background: #1e293b; /* 代码块保持深色，对比度高 */
  padding: 20px;
  border-radius: 12px;
  overflow-x: auto;
  border: 1px solid #334155;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

:deep(.markdown-body pre code) {
  background: transparent;
  color: #e2e8f0;
  border: none;
  padding: 0;
}

@media (max-width: 600px) {
  .chat-wrapper { height: 100dvh; padding: 8px; }
  .chat-header, .messages, .input-area { padding: 12px; }
  .chat-header h2 { font-size: 1rem; }
  .message-row { gap: 6px; max-width: 96%; }
  .message-bubble { padding: 9px 12px; }
  .avatar { width: 28px; height: 28px; }
  .trace-row { gap: 6px; }
}
</style>
