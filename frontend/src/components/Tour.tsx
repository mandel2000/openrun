import { useState } from 'react'
import { canPromptInstall, isAndroid, isIOS, isStandalone, promptInstall } from '../device'
import { Icon, Sheet, type IconName } from '../ui'
import { t } from '../i18n'

/** How to put the app on the home screen, for the device in hand. */
export function InstallGuide() {
  const [installed, setInstalled] = useState(isStandalone())
  if (installed) return <p className="small muted" style={{ margin: 0 }}><Icon name="check" size={14} /> {t('The app is already installed on this device.')}</p>
  if (canPromptInstall()) {
    return (
      <button className="btn btn-primary" onClick={async () => setInstalled(await promptInstall())}>
        <Icon name="download" size={16} />{t('Install the app')}
      </button>
    )
  }
  const steps = isIOS()
    ? [t('Open this page in Safari.'), t('Tap the Share button (the square with an arrow).'), t('Choose “Add to Home Screen” and tap Add.')]
    : isAndroid()
      ? [t('Open this page in Chrome.'), t('Tap the menu ⋮ at the top right.'), t('Choose “Install app” or “Add to Home screen”.')]
      : [t('Open this same address on your phone and sign in.'), t('On iPhone: Share › Add to Home Screen. On Android: menu ⋮ › Install app.')]
  return (
    <ol className="small text-2" style={{ margin: 0, paddingLeft: 18 }}>
      {steps.map((s) => <li key={s}>{s}</li>)}
    </ol>
  )
}

type Slide = { icon: IconName; title: string; body: string; extra?: 'install' }

const SLIDES: Slide[] = [
  { icon: 'sparkles', title: t('Welcome to OpenRun'), body: t('Your training plan adapts every day to how you are. Here is the app in one minute.') },
  { icon: 'home', title: t('Today'), body: t('Your workout of the day with its paces. In the morning answer “How do you feel?”: if you slept badly or are tired, the session is adjusted.') },
  { icon: 'calendar', title: t('Plan'), body: t('All the weeks until your goal. Tap a workout to see its steps, or drag it to another day if you need to move it.') },
  { icon: 'activity', title: t('Activities and progress'), body: t('Each run is compared with what was planned. In Progress you see your fitness, records and race time predictions.') },
  { icon: 'message', title: t('Your coach'), body: t('Ask anything: “Can I race a 10K on Sunday?”, “My knee hurts”. It knows your data and can change the plan for you.') },
  { icon: 'watch', title: t('Garmin'), body: t('Connect your Garmin in Settings: your runs sync by themselves and each workout appears on your watch, with its paces.') },
  { icon: 'smartphone', title: t('On your phone'), body: t('Add OpenRun to your home screen: it opens like an app and can send you the workout every morning.'), extra: 'install' },
]

export default function Tour({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0)
  const s = SLIDES[i]
  const last = i === SLIDES.length - 1
  return (
    <Sheet onClose={onClose} labelledBy="tour-title">
      <div className="stack tour" style={{ textAlign: 'center', alignItems: 'center' }}>
        <div className="tour-icon"><Icon name={s.icon} size={34} /></div>
        <h2 id="tour-title" style={{ margin: 0 }}>{s.title}</h2>
        <p className="text-2" style={{ margin: 0, maxWidth: 420 }}>{s.body}</p>
        {s.extra === 'install' && <div style={{ textAlign: 'left', width: '100%', maxWidth: 420 }}><InstallGuide /></div>}
        <div className="tour-dots" role="tablist" aria-label={t('Steps')}>
          {SLIDES.map((x, k) => (
            <button key={x.title} role="tab" aria-selected={k === i} aria-label={x.title} className={k === i ? 'on' : ''} onClick={() => setI(k)} />
          ))}
        </div>
        <div className="row" style={{ width: '100%', justifyContent: 'space-between' }}>
          {i > 0
            ? <button className="btn btn-ghost" onClick={() => setI(i - 1)}>{t('Back')}</button>
            : <button className="btn btn-ghost" onClick={onClose}>{t('Skip')}</button>}
          <button className="btn btn-primary" autoFocus onClick={() => (last ? onClose() : setI(i + 1))}>
            {last ? t('Let\'s go') : t('Next')}{!last && <Icon name="chevronRight" size={16} />}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
