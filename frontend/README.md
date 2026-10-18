# ApiPilot Frontend

ApiPilot 控制台的 Vue 3 + TypeScript + Vite 前端。

页面覆盖项目/API Client、AI Test Lab、测试计划与版本、Run 列表/详情，以及测试报告中心（PDF 查看/下载/打印入口）。前端需要后端和 PostgreSQL 才能使用完整功能。

## 技术栈

- Vue 3、TypeScript、Vue Router、Pinia
- Vite 8
- Element Plus、Tailwind CSS
- Vitest、Vue SSR renderToString

依赖版本以 [package.json](package.json) 为准。

## 本地开发

先启动后端（默认 `http://127.0.0.1:8000`），然后在本目录执行：

~~~powershell
npm install
npm run dev
~~~

Vite 默认使用 `http://localhost:5173`。

后端默认允许 5173 来源；如果修改前端端口或后端地址，请同时配置：

~~~dotenv
# frontend/.env
VITE_API_BASE_URL=http://127.0.0.1:8000
~~~

并确保后端 `CORS_ALLOW_ORIGINS` 包含实际前端 origin。

## 登录

- `DEPLOYMENT_MODE=self_hosted`：继续使用 Guest Session，不要求登录。
- `DEPLOYMENT_MODE=official_cloud`：默认需要账号；后端开启 `AUTH_OFFICIAL_GUEST_ENABLED=true` 后，`/login` 同时提供 GitHub、Google 和“以游客身份体验”。
- 游客体验会调用真实的 `POST /api/guest-sessions`，成功后保存 Guest Session 并进入控制台；刷新会复用该会话，右上角显示游客菜单，而不是账号邮箱/设置/退出。
- 登录入口只把浏览器重定向到后端的 GitHub/Google 登录路由；provider secret 和 token 不进入前端构建或 localStorage。
- 账号 Cookie 由后端设置为 HttpOnly。本地 OAuth 验收请同时使用 `http://127.0.0.1:5173` 和 `http://127.0.0.1:8000`，避免跨站 Lax Cookie 不发送。
- 后端配置、callback URL 和 provider 控制台步骤见 [根 README](../README.md#身份认证与-oauth)。

## 常用命令

~~~powershell
npm test                 # Vitest
npm run build            # vue-tsc + Vite 生产构建
npm run preview          # 预览构建产物
npx vue-tsc -b --pretty false
~~~

当前类型检查有一个既有错误：

~~~text
src/layouts/ConsoleLayout.vue(117,10): error TS18047:
'projectStore.activeProject' is possibly 'null'.
~~~

因此 `npm run build` / `npm run verify` 目前会在类型检查阶段失败；这不代表业务测试失败。该问题尚未修复。

## 目录

~~~text
src/
├── components/   # 控制台和页面组件
│   └── learn/    # Learn Us 顶栏、导航、搜索
├── content/docs/ # Learn Us 中英文 Markdown 与注册表
├── composables/  # 组合式函数
├── i18n/         # 中英文 key schema
├── locales/      # en-US / zh-CN 文案
├── router/       # 控制台路由
├── services/     # HTTP、guest session、API 适配器
├── stores/       # Pinia stores
├── types/        # TypeScript 类型
├── utils/        # 报告投影/脱敏等工具
└── views/        # 页面；console/ 是控制台
tests/            # Vitest
e2e/              # 可选受控浏览器 E2E
~~~

## 测试

~~~powershell
npm test
~~~

最近一次完整前端结果为 **37 个测试文件、379 项测试通过、0 失败**。

浏览器 E2E 需要已迁移的隔离 PostgreSQL 库和后端；见 [e2e/README.md](e2e/README.md)。

## 相关文档

- [仓库根 README](../README.md)
- [前端架构](docs/phase-6-architecture.md)
- [前端后端 REST 契约](docs/phase-6.2-backend-rest-contract.md)
- [项目进度](../docs/PROJECT_PROGRESS.md)
