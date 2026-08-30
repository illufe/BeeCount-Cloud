import { afterEach, describe, expect, it, vi } from 'vitest'

import { clearDevelopmentServiceWorker, DEV_SERVICE_WORKER_CACHE } from './pwa-sw-update'

describe('development service worker cleanup', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('unregisters current-origin workers and deletes only the dev cache', async () => {
    const unregister = vi.fn().mockResolvedValue(true)
    const getRegistrations = vi.fn().mockResolvedValue([{ unregister }, { unregister }])
    const deleteCache = vi.fn().mockResolvedValue(true)
    vi.stubGlobal('navigator', { serviceWorker: { getRegistrations } })
    vi.stubGlobal('window', { caches: { delete: deleteCache } })

    await clearDevelopmentServiceWorker()

    expect(getRegistrations).toHaveBeenCalledOnce()
    expect(unregister).toHaveBeenCalledTimes(2)
    expect(deleteCache).toHaveBeenCalledOnce()
    expect(deleteCache).toHaveBeenCalledWith(DEV_SERVICE_WORKER_CACHE)
  })
})
