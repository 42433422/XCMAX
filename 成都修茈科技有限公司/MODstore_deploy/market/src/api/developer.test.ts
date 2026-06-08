import { describe, expect, it, vi } from 'vitest'
import { developer, templates, notifications } from './developer'

vi.mock('./shared', () => ({
  req: vi.fn(() => Promise.resolve({})),
}))

import { req } from './shared'

const m = vi.mocked(req)

describe('developer API', () => {
  beforeEach(() => { m.mockClear() })

  it('developerListTokens', async () => {
    await developer.developerListTokens()
    expect(m).toHaveBeenCalledWith('/api/developer/tokens')
  })

  it('developerCreateToken', async () => {
    await developer.developerCreateToken('my-token', ['read'], 30)
    expect(m).toHaveBeenCalledWith('/api/developer/tokens', expect.objectContaining({ method: 'POST' }))
  })

  it('developerRevokeToken', async () => {
    await developer.developerRevokeToken(42)
    expect(m).toHaveBeenCalledWith('/api/developer/tokens/42', expect.objectContaining({ method: 'DELETE' }))
  })

  it('developerExportKeyBundle', async () => {
    await developer.developerExportKeyBundle({
      recipient_public_key_spki_b64: 'key',
      current_password: 'pass',
      token_ids: [1],
      rotate_source_tokens: true,
    })
    expect(m).toHaveBeenCalledWith('/api/developer/key-export/bundle', expect.objectContaining({ method: 'POST' }))
  })

  it('developerListKeyExportAudit', async () => {
    await developer.developerListKeyExportAudit(20)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('key-export/audit'))
  })

  it('developerWebhookEventCatalog', async () => {
    await developer.developerWebhookEventCatalog()
    expect(m).toHaveBeenCalledWith('/api/developer/webhooks/event-catalog')
  })

  it('developerListWebhooks', async () => {
    await developer.developerListWebhooks()
    expect(m).toHaveBeenCalledWith('/api/developer/webhooks')
  })

  it('developerCreateWebhook', async () => {
    await developer.developerCreateWebhook({ name: 'wh', target_url: 'http://x' })
    expect(m).toHaveBeenCalledWith('/api/developer/webhooks', expect.objectContaining({ method: 'POST' }))
  })

  it('developerUpdateWebhook', async () => {
    await developer.developerUpdateWebhook(1, { name: 'new' })
    expect(m).toHaveBeenCalledWith('/api/developer/webhooks/1', expect.objectContaining({ method: 'PUT' }))
  })

  it('developerDeleteWebhook', async () => {
    await developer.developerDeleteWebhook(1)
    expect(m).toHaveBeenCalledWith('/api/developer/webhooks/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('developerListWebhookDeliveries with opts', async () => {
    await developer.developerListWebhookDeliveries(1, { limit: 10, status: 'failed' })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('deliveries'))
  })

  it('developerRetryWebhookDelivery', async () => {
    await developer.developerRetryWebhookDelivery(99)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('deliveries/99/retry'), expect.objectContaining({ method: 'POST' }))
  })

  it('developerTestWebhook', async () => {
    await developer.developerTestWebhook(1)
    expect(m).toHaveBeenCalledWith('/api/developer/webhooks/1/test', expect.objectContaining({ method: 'POST' }))
  })
})

describe('templates API', () => {
  beforeEach(() => { m.mockClear() })

  it('templatesList with no opts', async () => {
    await templates.templatesList()
    expect(m).toHaveBeenCalledWith('/api/templates')
  })

  it('templatesList with query params', async () => {
    await templates.templatesList({ q: 'test', category: 'cat', limit: 10 })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('q=test'))
  })

  it('templatesCategories', async () => {
    await templates.templatesCategories()
    expect(m).toHaveBeenCalledWith('/api/templates/categories')
  })

  it('templateDetail', async () => {
    await templates.templateDetail(42)
    expect(m).toHaveBeenCalledWith('/api/templates/42')
  })

  it('templateInstall', async () => {
    await templates.templateInstall(42)
    expect(m).toHaveBeenCalledWith('/api/templates/42/install', expect.objectContaining({ method: 'POST' }))
  })

  it('saveWorkflowAsTemplate', async () => {
    await templates.saveWorkflowAsTemplate(1, { name: 'tmpl' })
    expect(m).toHaveBeenCalledWith('/api/templates/from-workflow/1', expect.objectContaining({ method: 'POST' }))
  })
})

describe('notifications API', () => {
  beforeEach(() => { m.mockClear() })

  it('notificationsList with defaults', async () => {
    await notifications.notificationsList()
    expect(m).toHaveBeenCalledWith(expect.stringContaining('notifications'))
  })

  it('notificationsList with kind', async () => {
    await notifications.notificationsList(true, 10, 'order')
    expect(m).toHaveBeenCalledWith(expect.stringContaining('kind=order'))
  })

  it('notificationMarkRead', async () => {
    await notifications.notificationMarkRead(1)
    expect(m).toHaveBeenCalledWith('/api/notifications/1/read', expect.objectContaining({ method: 'POST' }))
  })

  it('notificationsMarkAllRead', async () => {
    await notifications.notificationsMarkAllRead()
    expect(m).toHaveBeenCalledWith('/api/notifications/read-all', expect.objectContaining({ method: 'POST' }))
  })

  it('analyticsDashboard', async () => {
    await notifications.analyticsDashboard()
    expect(m).toHaveBeenCalledWith('/api/analytics/dashboard')
  })
})
