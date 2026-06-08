import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router/index.ts'
import { createModstoreI18n } from './i18n'
import './style.css'
import { bootstrapHostConfig } from './stores/hostConfig'
import { bootstrapWorkbenchThemeFromStorage } from './utils/personalSettings'

bootstrapWorkbenchThemeFromStorage()
void bootstrapHostConfig()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(createModstoreI18n())
app.mount('#app')
