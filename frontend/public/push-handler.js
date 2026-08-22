// workbox SW가 importScripts로 불러오는 push 핸들러. 알림 표시 + 클릭 시 앱 포커스.
self.addEventListener('push', (event) => {
  let data = { title: 'FORGE', body: '', url: '/' }
  try {
    data = { ...data, ...event.data.json() }
  } catch (e) {
    if (event.data) data.body = event.data.text()
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/logo.png',
      badge: '/logo.png',
      data: { url: data.url || '/' },
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if ('focus' in c) return c.focus()
      }
      if (self.clients.openWindow) return self.clients.openWindow(url)
    })
  )
})
