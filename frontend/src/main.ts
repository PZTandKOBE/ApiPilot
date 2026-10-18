import { createPinia } from 'pinia'
import { createApp } from 'vue'

// Stylesheet order is load-bearing. Element Plus first, then its dark variable
// set, then our own layers — the console theme is expressed as overrides of
// Element Plus variables, so it has to come after them in the cascade.
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '@/styles/index.css'
import '@/styles/console.css'
import '@/styles/report.css'
import '@/styles/learn.css'
import '@/styles/auth.css'

import App from '@/App.vue'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// Load the deployment mode and the HttpOnly account cookie before the first
// view can issue a request. In official-cloud mode this prevents an anonymous
// guest session from being minted before the login redirect.
const auth = useAuthStore(pinia)
void auth.initialize().finally(() => {
  app.use(router)
  app.mount('#app')
})
