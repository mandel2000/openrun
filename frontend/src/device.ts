// Device helpers: platform detection and the PWA install prompt (Chrome/Edge/Android).
export const isAndroid = () => /android/i.test(navigator.userAgent)
// iPadOS reports itself as a Mac: tell it apart by the touch screen
export const isIOS = () => !isAndroid() && (/iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1))
export const isMobile = () => isIOS() || isAndroid()
export const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> }
let deferred: InstallEvent | null = null
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferred = e as InstallEvent })
window.addEventListener('appinstalled', () => { deferred = null })

export const canPromptInstall = () => deferred !== null
export async function promptInstall(): Promise<boolean> {
  if (!deferred) return false
  await deferred.prompt()
  const { outcome } = await deferred.userChoice
  deferred = null
  return outcome === 'accepted'
}
