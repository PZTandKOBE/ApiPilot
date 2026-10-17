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

import App from '@/App.vue'
import router from '@/router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.mount('#app')
