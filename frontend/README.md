# ApiPilot Frontend

ApiPilot 控制台的 Vue 3 + TypeScript + Vite 前端。

页面覆盖项目列表、项目概览与编辑、环境管理、API Client、AI Test Lab、Agent 任务与五步分析审阅、测试计划与版本、Run 列表/详情、测试报告中心，以及中英文 Learn Us 文档中心。完整功能需要后端和 PostgreSQL。

## 技术栈

- Vue 3、TypeScript、Vue Router、Pinia
- Node.js 20.19+ 或 22.12+
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

Vite 默认使用 `http://localhost:5173`。后端默认允许 5173 来源；如果修改前端端口或后端地址，请同时配置：

~~~dotenv
# frontend/.env
VITE_API_BASE_URL=http://127.0.0.1:8000
~~~

并确保后端 `CORS_ALLOW_ORIGINS` 包含实际前端 origin。

## 产品页面

- 项目：列表、创建、概览、编辑、删除和项目切换。
- 环境：项目内多环境创建、编辑和切换；环境变量由后端保存。
- API 规格：导入/粘贴 OpenAPI 或 Swagger 文档，展示解析摘要和真实接口数据。
- AI Test Lab：Agent 任务列表与状态、五步分析审阅、依赖和风险展示。
- 测试计划：场景/步骤/断言、版本管理、名称/目标编辑、审批、拒绝和删除；删除计划保留历史 Run 与报告。审批/拒绝和名称/目标编辑当前是浏览器端状态，尚无独立 Plan Approval API。
- Run：列表、详情、步骤、证据、运行时变量、取消和历史。
- 报告：PDF 在线查看、下载和打印。
- 通知：顶部通知中心汇总当前项目的 Agent 任务、待审核计划和已生成报告。
- Learn Us：中英文文档、搜索、导航、代码复制、锚点和明暗主题。

## 登录

- `DEPLOYMENT_MODE=self_hosted`：使用 Guest Session，不要求登录。
- `DEPLOYMENT_MODE=official_cloud`：默认需要账号；后端开启 `AUTH_OFFICIAL_GUEST_ENABLED=true` 后，`/login` 同时提供 GitHub、Google 和“以游客身份体验”。
- 游客体验会调用真实的 `POST /api/guest-sessions`，成功后保存 Guest Session 并进入控制台；刷新会复用该会话，右上角显示游客菜单。
- 登录入口只把浏览器重定向到后端的 GitHub/Google 登录路由；provider secret 和 token 不进入前端构建或 localStorage。
- 账号 Cookie 由后端设置为 HttpOnly。本地 OAuth 验收请同时使用 `http://127.0.0.1:5173` 和 `http://127.0.0.1:8000`，避免跨站 Lax Cookie 不发送。
- 后端配置、callback URL 和 provider 控制台步骤见 [根 README](../README.md#身份认证与-oauth)。

## 常用命令

~~~powershell
npm test                 # Vitest
npx vue-tsc -b --pretty false
npm run build            # vue-tsc + Vite 生产构建
npm run preview          # 预览构建产物
~~~

测试结果以命令实际输出为准，不在文档中维护易过期数量。类型检查应与测试、生产构建一起作为发布前检查运行。

## 目录

~~~text
src/
├── components/       # 控制台、页面、Learn Us 和效果组件
│   ├── console/      # 项目、环境、Agent、计划、Run、报告、通知
│   ├── effects/      # Vue Bits 视觉效果组件
│   └── learn/        # Learn Us 顶栏、导航、搜索
├── content/docs/     # Learn Us 中英文 Markdown 与注册表
├── composables/      # 组合式函数
├── i18n/             # 中英文 key schema
├── locales/          # en-US / zh-CN 文案
├── router/           # 页面路由
├── services/         # HTTP、Guest Session、API 适配器
├── stores/           # Pinia stores
├── types/            # TypeScript 类型
├── utils/            # 时间、URL、报告投影等工具
└── views/            # 页面；console/ 是控制台
tests/                # Vitest
e2e/                  # 可选受控浏览器 E2E
~~~

## 测试

~~~powershell
npm test
~~~

浏览器 E2E 需要已迁移的隔离 PostgreSQL 库、后端和 Chrome；见 [e2e/README.md](e2e/README.md)。

## 相关文档

- [仓库根 README](../README.md)
- [效果组件说明](src/components/effects/README.md)
