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

## 常用命令

~~~powershell
npm test                 # Vitest
npm run build            # vue-tsc + Vite 生产构建
npm run preview          # 预览构建产物
npx vue-tsc -b --pretty false
~~~

当前类型检查有一个既有错误：

~~~text
src/layouts/ConsoleLayout.vue(114,10): error TS18047:
'projectStore.activeProject' is possibly 'null'.
~~~

因此 `npm run build` / `npm run verify` 目前会在类型检查阶段失败；这不代表业务测试失败。该问题尚未修复。

## 目录

~~~text
src/
├── components/   # 控制台和页面组件
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

最近一次完整前端结果为 **27 个测试文件、338 项测试通过、0 失败**。

浏览器 E2E 需要已迁移的隔离 PostgreSQL 库和后端；见 [e2e/README.md](e2e/README.md)。

## 相关文档

- [仓库根 README](../README.md)
- [前端架构](docs/phase-6-architecture.md)
- [前端后端 REST 契约](docs/phase-6.2-backend-rest-contract.md)
- [项目进度](../docs/PROJECT_PROGRESS.md)
