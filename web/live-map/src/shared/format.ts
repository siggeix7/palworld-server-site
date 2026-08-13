export function number(value: unknown, digits = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString('it-IT', { maximumFractionDigits: digits }) : '--'
}

export function duration(seconds: unknown) {
  let value = Math.max(0, Number(seconds) || 0)
  const days = Math.floor(value / 86_400)
  value %= 86_400
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  if (days) return `${days}g ${hours}h`
  if (hours) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

export function minutes(value: unknown) {
  return duration((Number(value) || 0) * 60)
}

export function date(value: unknown, includeSeconds = false, timeZone?: string) {
  if (!value) return 'mai'
  const parsed = new Date(String(value))
  if (Number.isNaN(parsed.getTime())) return '--'
  return new Intl.DateTimeFormat('it-IT', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: includeSeconds ? '2-digit' : undefined,
    timeZone
  }).format(parsed)
}

export function setting(value: unknown): string {
  if (Array.isArray(value)) return value.map(setting).join(', ')
  if (value === true) return 'Attivo'
  if (value === false) return 'Disattivo'
  if (value === null || value === undefined || value === '') return '--'
  if (typeof value === 'number') return number(value, 4)
  return String(value)
}

export function settingLabel(key: string) {
  const special: Record<string, string> = {
    AllowConnectPlatform: 'Piattaforme consentite',
    CrossplayPlatforms: 'Piattaforme crossplay',
    ServerDescription: 'Descrizione server',
    ServerName: 'Nome server',
    bExistPlayerAfterLogout: 'Giocatore persistente dopo il logout',
    bIsUseBackupSaveData: 'Backup dei salvataggi'
  }
  if (special[key]) return special[key]
  return key
    .replace(/^b(?=[A-Z])/, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replaceAll('_', ' ')
}
