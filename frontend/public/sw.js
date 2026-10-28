// OpenRun no longer uses a service worker (installing the app only needs the manifest).
// This file stays as a kill switch: browsers that still have an older OpenRun worker fetch it on
// their next update check, and it removes its caches and unregisters itself.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) await caches.delete(k)
    await self.registration.unregister()
    for (const c of await self.clients.matchAll({ type: 'window' })) c.navigate(c.url)
  })())
})
