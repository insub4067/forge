<script setup>
// 파일·폴더 종류별 좌측 아이콘 — 파일 브라우저와 워크스페이스 피커가 공용.
// entry: { name, is_dir } (fs/list 항목)
const props = defineProps({ entry: { type: Object, required: true } })

function kind(e) {
  if (e.is_dir) return 'dir'
  const n = (e.name || '').toLowerCase()
  const ext = n.includes('.') ? n.slice(n.lastIndexOf('.') + 1) : ''
  if (['py', 'js', 'ts', 'jsx', 'tsx', 'vue', 'go', 'rs', 'java', 'c', 'cpp', 'h', 'rb', 'php', 'swift', 'sh', 'html', 'css', 'sql'].includes(ext)) return 'code'
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'bmp'].includes(ext)) return 'image'
  if (['md', 'txt', 'log', 'rst', 'pdf'].includes(ext)) return 'doc'
  if (['json', 'yml', 'yaml', 'toml', 'env', 'ini', 'conf', 'lock', 'cfg'].includes(ext)) return 'config'
  return 'file'
}
</script>

<template>
  <span class="fs-icon" :class="'kind-' + kind(entry)">
    <svg v-if="kind(entry) === 'dir'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
    <svg v-else-if="kind(entry) === 'code'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/></svg>
    <svg v-else-if="kind(entry) === 'image'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
    <svg v-else-if="kind(entry) === 'config'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h2M16 3h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-2"/></svg>
    <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
  </span>
</template>
