import { Sheet } from '../ui'
import { t } from '../i18n'

/** Plain-language privacy notice, shown at sign-up and from Settings › Account. */
export function PrivacyText() {
  const items: [string, string][] = [
    [t('What is stored'), t('Your account (username, name and a hash of your password), your training plan, the activities and health data you sync from Garmin or import, your races, settings and the chat with the coach.')],
    [t('Where'), t('On the server of whoever invited you, not on a company cloud. Each account only sees its own data. The person who runs the server could technically access the database, as with any self-hosted service.')],
    [t('Garmin'), t('Your Garmin password is only used once to sign in and is never stored: the server keeps a session token, like the Garmin Connect app does. You can disconnect it at any time.')],
    [t('AI coach'), t('When you use the coach, your message and the training data it needs are sent to the AI provider configured on this server to generate the answer. Nothing is sent if you don\'t use it.')],
    [t('Backups'), t('The database is copied every day. Copies stored outside the server are encrypted.')],
    [t('No ads, no tracking'), t('No analytics, no advertising, no data selling. Cookies are only used to keep you signed in.')],
    [t('Your rights'), t('In Settings › Account you can download all your data or delete your account and everything in it, at any time.')],
  ]
  return (
    <div className="stack" style={{ gap: 10 }}>
      {items.map(([h, p]) => (
        <div key={h}>
          <div style={{ fontWeight: 600 }}>{h}</div>
          <p className="small muted" style={{ margin: '2px 0 0' }}>{p}</p>
        </div>
      ))}
    </div>
  )
}

export default function PrivacySheet({ onClose }: { onClose: () => void }) {
  return (
    <Sheet title={t('Privacy')} onClose={onClose}>
      <PrivacyText />
      <button className="btn btn-primary btn-block" style={{ marginTop: 16 }} onClick={onClose}>{t('Got it')}</button>
    </Sheet>
  )
}
