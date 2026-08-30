import React from 'react'
import { createRoot } from 'react-dom/client'
import {
  LocaleProvider,
  PrimaryColorProvider,
  ThemeProvider,
  ToastProvider,
  applyDocumentLocale,
  applyPrimaryColor,
  applyTheme,
  initialLocale,
  initialPrimaryColor,
  initialThemeMode
} from '@beecount/ui'

import { App } from './App'
import { dictionaries } from './i18n'
import { setupInstallPrompt } from './lib/pwa-install'
import { setupLaunchQueue } from './lib/pwa-launch'
import { clearDevelopmentServiceWorker, setupServiceWorkerUpdates } from './lib/pwa-sw-update'
import './styles.css'

applyTheme(initialThemeMode())
applyDocumentLocale(initialLocale())
// 启动时立刻 apply primary color，避免 React hydration 前首屏闪烁默认金色。
applyPrimaryColor(initialPrimaryColor())

// File Handler:订阅 launchQueue,接住「双击 .csv 用蜜蜂记账打开」的文件
setupLaunchQueue()

// PWA install prompt:接住 beforeinstallprompt,延后到 engagement 达标再弹
setupInstallPrompt()

// 生产注册 PWA service worker；dev 不注册 cache-first worker，并清掉本 origin
// 上次遗留的 registration / 精确静态缓存，避免 Vite 模块被旧 SW 截获。
if ('serviceWorker' in navigator) {
  if (import.meta.env.DEV) {
    void clearDevelopmentServiceWorker().catch((err) => {
      // eslint-disable-next-line no-console
      console.warn('[pwa] dev sw cleanup failed', err)
    })
  } else {
    window.addEventListener('load', () => {
      navigator.serviceWorker
        .register('/sw.js', { scope: '/' })
        .then((registration) => {
          setupServiceWorkerUpdates(registration)
        })
        .catch((err) => {
          // 不影响主流程，只在生产控制台留个记录。
          // eslint-disable-next-line no-console
          console.warn('[pwa] sw register failed', err)
        })
    })
  }
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <LocaleProvider dictionaries={dictionaries}>
      <ThemeProvider>
        <PrimaryColorProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </PrimaryColorProvider>
      </ThemeProvider>
    </LocaleProvider>
  </React.StrictMode>
)
