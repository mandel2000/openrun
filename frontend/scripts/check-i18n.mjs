// Every t('…') string in src/ must have a Spanish entry in src/locales/es.ts (and no stale entries).
// Run: npm run i18n:check
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const SRC = new URL('../src/', import.meta.url).pathname
const files = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? files(join(d, f)) : [join(d, f)]))
const unquote = (q) => q.slice(1, -1).replace(/\\n/g, '\n').replace(/\\(['"\\])/g, '$1')
const STR = String.raw`'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"`

const used = new Set()
for (const f of files(SRC).filter((x) => /\.tsx?$/.test(x) && !x.includes('/locales/') && !x.endsWith('i18n.ts'))) {
  for (const m of readFileSync(f, 'utf8').matchAll(new RegExp(String.raw`\bt\((${STR})`, 'g'))) used.add(unquote(m[1]))
}
const es = new Set([...readFileSync(join(SRC, 'locales/es.ts'), 'utf8').matchAll(new RegExp(String.raw`^\s*(${STR}):`, 'gm'))].map((m) => unquote(m[1])))

const missing = [...used].filter((k) => !es.has(k))
const stale = [...es].filter((k) => !used.has(k))
if (missing.length) console.error(`Missing Spanish translations (${missing.length}):\n  ` + missing.join('\n  '))
if (stale.length) console.error(`Unused entries in locales/es.ts (${stale.length}):\n  ` + stale.join('\n  '))
process.exit(missing.length || stale.length ? 1 : 0)
