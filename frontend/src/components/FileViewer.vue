<script setup>
// 파일 뷰어 — 텍스트/이미지/비디오/오디오/PDF를 종류에 맞게 표시한다.
// 텍스트는 직접 fetch해 문법 하이라이팅, PDF는 PdfViewer로 위임.
import { ref, computed, watch } from 'vue'
import hljs from 'highlight.js/lib/common'
import PdfViewer from './PdfViewer.vue'

const props = defineProps({
  path: { type: String, required: true },
  sessionId: { type: String, default: '' },
})

const _MEDIA = {
  image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'],
  video: ['mp4', 'webm', 'mov', 'm4v'],
  audio: ['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac'],
  doc: ['md', 'txt', 'log', 'rst', 'pdf'],
  pdf: ['pdf'],
}
const kind = computed(() => {
  const ext = (props.path.split('.').pop() || '').toLowerCase()
  for (const [k, exts] of Object.entries(_MEDIA)) if (exts.includes(ext)) return k === 'doc' && ext === 'pdf' ? 'pdf' : k === 'doc' ? 'text' : k
  return 'text'
})

const content = ref('')

const emit = defineEmits(['image-click']) // 이미지 탭 → 상위 라이트박스

const mediaUrl = computed(
  () => `/api/fs/raw?path=${encodeURIComponent(props.path)}&session_id=${encodeURIComponent(props.sessionId)}`
)

watch(
  () => props.path,
  async (p) => {
    content.value = ''
    if (!p || kind.value !== 'text') return
    try {
      const res = await fetch(`/api/fs/read?path=${encodeURIComponent(p)}&session_id=${props.sessionId}`)
      if (res.ok) content.value = (await res.json()).content || ''
    } catch {}
  },
  { immediate: true }
)

const _EXT_LANG = {
  ts: 'typescript', tsx: 'typescript', vue: 'xml', html: 'xml', xml: 'xml',
  py: 'python', rb: 'ruby', go: 'go', rs: 'rust', java: 'java', kt: 'kotlin',
  c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', cs: 'csharp', php: 'php', swift: 'swift',
  css: 'css', scss: 'scss', json: 'json', yml: 'yaml', yaml: 'yaml', toml: 'ini',
  sh: 'bash', bash: 'bash', zsh: 'bash', sql: 'sql', md: 'markdown', dockerfile: 'dockerfile',
}
// 소스코드를 IDE처럼 문법 하이라이팅. 실패하면 이스케이프만.
const highlightedContent = computed(() => {
  const code = content.value || ''
  const ext = (props.path.split('.').pop() || '').toLowerCase()
  const lang = _EXT_LANG[ext]
  try {
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value
    return hljs.highlightAuto(code).value
  } catch {
    return code.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
  }
})
const fileLineCount = computed(() => (content.value ? content.value.split('\n').length : 0))

</script>

<template>
  <div v-if="kind === 'image'" class="media-view">
    <img :src="mediaUrl" :alt="path" @click="emit('image-click', mediaUrl)" />
  </div>
  <div v-else-if="kind === 'video'" class="media-view">
    <video :src="mediaUrl" controls playsinline />
  </div>
  <div v-else-if="kind === 'audio'" class="media-view">
    <audio :src="mediaUrl" controls />
  </div>
  <PdfViewer v-else-if="kind === 'pdf'" :url="mediaUrl" />
  <div v-else class="code-view">
    <div class="code-gutter"><span v-for="n in fileLineCount" :key="n">{{ n }}</span></div>
    <pre class="code-body"><code v-html="highlightedContent"></code></pre>
  </div>
</template>
