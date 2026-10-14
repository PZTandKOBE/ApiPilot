# AI API Testing Agent 数据库设计文档

**版本：** v1.1  
**状态：** 第一批 17 张表的 SQLAlchemy Model 已实现并通过验证  
**技术栈：** PostgreSQL + SQLAlchemy 2.0 + Alembic  
**适用项目：** AI API Testing Agent  
**最后更新：** 2026-09-21

---

## 0. 文档与实现的对应关系

本文档描述的表结构，与 `src/backend/db/models/` 下的 SQLAlchemy Model **逐字段一致**。
两者不存在第二套版本：本文件即 Model 的规格说明。

### 列类型的书写约定

文档中的类型是 **PostgreSQL 类型**。Model 中一律显式声明，不依赖 SQLAlchemy 的类型推导：

| 文档中写作 | Model 中写作 | 为什么必须显式 |
|---|---|---|
| `TIMESTAMPTZ` | `DateTime(timezone=True)` | `Mapped[datetime]` 会推导出 `TIMESTAMP WITHOUT TIME ZONE`，静默丢时区 |
| `JSONB` | `postgresql.JSONB` | `sa.JSON` 在 PG 上渲染为 `JSON` 而非 `JSONB` |
| `VARCHAR(n)` | `String(n)` | `Mapped[str]` 会推导出**无长度**的 `VARCHAR` |

### 枚举

数据库**不使用** PostgreSQL ENUM，也不加 CHECK 约束。所有状态列都是 `VARCHAR(n)` 存字面量，
取值集合由应用层的 Python `StrEnum` 与 Pydantic 负责。

原因：这些取值集合确定会变（例如 `environment_auths.auth_type` 以后要扩展 OAuth2/JWT），
每加一个值都将变成一次迁移。原生 ENUM 更差——`ALTER TYPE ... ADD VALUE` 有事务限制，删值几乎不可能。

### 双 ID 约定

数据库内部主键一律是 UUID，**不因为前端用字符串 ID 而改动**。

面向外部的、前端已经在使用的稳定字符串 ID 单独放在 `public_id` 列：

```text
id          UUID PRIMARY KEY     数据库内部主键，不外露
public_id   VARCHAR(255)         前端 / API 使用的稳定 ID
```

| 表 | public_id 示例 | 唯一性范围 |
|---|---|---|
| `projects` | `prj_orders` | 全局 UNIQUE（项目本身没有父级） |
| `environments` | `env_orders_staging` | `UNIQUE(project_id, public_id)` |
| `test_plans` | `plan_orders_1a2b3c4d` | `UNIQUE(project_id, public_id)` |
| `api_endpoints` | `ep_post_api_orders` | `UNIQUE(spec_id, public_id)` |

**为什么大多是项目范围而非全局 UNIQUE**：这些 ID 由文档内容、路径和方法派生，
派生规则本身不含项目信息。两个项目上传同一份文档、或都定义了 `GET /api/orders`，
是正常情况，不是冲突。只有 `projects` 没有父级，因此只有它是全局唯一。

`api_endpoints` 的作用域是 `spec_id` 而不是 `project_id`：它自身没有 `project_id`，
而它编码的规则（"一份文档里 method + path 唯一"）是 OpenAPI 对文档的不变量。

**长度约定**：`public_id` 一律 `VARCHAR(255)`。它是外部标识符的宽度上限，
写入方（解析服务）负责保证生成的 ID 落在该宽度内；不要为了迁就病态输入把列放宽到 1000+。

### 不增加 `public_id` 的表

以下表已经有承担同样职责的列，**不重复增加 `public_id`**：

| 表 | 已有的等价列 |
|---|---|
| `test_scenarios` | `scenario_key` |
| `test_steps` | `step_key` |
| `test_assertions` | `assertion_key` |
| `api_specs` | `slug` |

`api_specs` 曾有 `public_id`（= `'spec_' + slug`），**已删除**：它是同源冗余，
会让数据库里有两个代表同一个外部 ID 的列。前端/API 需要 spec 的对外 ID 时，
由 API 层按现有前端规则拼出：

```text
spec_${slug}
```

前端 `ApiSpec.id` 的生成逻辑（`spec_${slug}`，其中 slug 由内容哈希派生）**不受影响**，
数据库这一侧只是不再重复存储它。

### 实现状态

| 批次 | 表 | 状态 |
|---|---|---|
| 第一批 | 17 张（见 §12） | 已实现 |
| 第二批 | `test_workflows` + 5 张 `run_*` | 未实现；见 §6.3 与 §7.3–§7.7 中已标注的结构修正 |

---

## 1. 文档目标

本文档定义 AI API Testing Agent 当前版本的数据库业务结构。

数据库按照产品的四大业务体系组织，而不是简单按照“4 张表”组织：

1. 用户体系
2. 项目体系
3. Agent 测试体系
4. 结果体系

其中一个核心产品原则是：

> **Agent 不是所有 API 测试的必经步骤。**

用户可以直接使用 API 客户端进行手动测试，也可以使用 Agent 分析 API、生成测试计划并执行自动化测试。

因此系统存在两条测试路线：

```text
手动测试：
Project → Environment → Saved Request → API Client → Request History

Agent 测试：
Project → API Spec → Agent Task → Test Plan → Workflow/Scenario
                                     ↓
                                  Test Run
                                     ↓
                              Run Results / Evidence
```

---

# 2. 四大业务体系

## 2.1 用户体系

```text
用户体系
├── users
└── guest_sessions
```

负责用户身份、游客身份以及项目归属。

## 2.2 项目体系

```text
项目体系
├── projects
├── api_specs
├── api_endpoints
├── environments
├── environment_variables
├── environment_auths
├── request_collections
└── saved_requests
```

负责项目本身、API 文档、接口、环境、认证信息以及 API Client 中保存的数据。

## 2.3 Agent 测试体系

```text
Agent 测试体系
├── agent_tasks
├── test_plans
├── test_workflows
├── test_scenarios
├── test_steps
└── test_assertions
```

负责 Agent 测试任务、测试计划、工作流、测试场景、测试步骤和断言定义。

## 2.4 结果体系

```text
结果体系
├── api_request_history
├── test_runs
├── run_scenarios
├── run_steps
├── run_assertions
├── run_evidence
└── run_events
```

负责用户手动请求历史和 Agent 自动化测试的执行结果、证据及事件。

---

# 3. 数据库关系总览

```text
users
  │
  ├──────────────┐
  │              │
  ↓              ↓
guest_sessions  projects
                   │
       ┌───────────┼───────────────┬────────────────┐
       │           │               │                │
       ↓           ↓               ↓                ↓
   api_specs   environments   request_collections  agent_tasks
       │           │               │                │
       ↓           ├── environment  └── saved_requests
 api_endpoints     │     variables
                   │
                   └── environment_auths

agent_tasks
    ↓
test_plans
    ├── test_workflows
    └── test_scenarios
            ↓
        test_steps
            ↓
        test_assertions

projects ──→ api_request_history

 test_plans
     ↓
  test_runs
     ├── run_scenarios
     │       ↓
     │   run_steps
     │       ↓
     │   run_assertions
     │
     ├── run_evidence
     └── run_events
```

---

# 4. 用户体系

## 4.1 users

### 作用

保存注册用户的基本账户信息。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| username | VARCHAR(100) | 否 | 用户名 |
| email | VARCHAR(255) | 否 | 邮箱 |
| password_hash | VARCHAR(255) | **是** | 密码哈希，不保存明文密码 |
| status | VARCHAR(20) | 否 | `active` / `disabled` |
| provider | VARCHAR(30) | 否 | `github` / `google` / `email` |
| avatar_url | VARCHAR(1000) | 是 | 头像地址；为 NULL 时前端渲染首字母 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 约束

- `id` 为 Primary Key
- `username` UNIQUE
- `email` UNIQUE
- `status` 默认 `active`
- `provider` 默认 `email`
- `password_hash` **可空**

### 为什么 password_hash 可空

`provider` 支持 GitHub / Google 登录，而 OAuth 用户没有密码。
若 `password_hash` 保持 NOT NULL，`provider != 'email'` 的行**根本无法插入**，
新增的 `provider` 字段也就失去意义。可空是让这个字段有意义的前提。

---

## 4.2 guest_sessions

### 作用

保存游客身份。

游客的数据不直接放在浏览器中；浏览器只需要保存一个会话身份凭证，真正的项目数据仍然保存在 PostgreSQL 中。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| session_token | VARCHAR(255) | 否 | 游客身份凭证 |
| expires_at | TIMESTAMPTZ | 是 | 会话过期时间 |
| last_seen_at | TIMESTAMPTZ | 否 | 最近访问时间 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |

### 约束

- `id` 为 Primary Key
- `session_token` Unique

### 项目归属逻辑

游客项目：

```text
projects.user_id = NULL
projects.guest_session_id = 当前游客 session
```

正式用户项目：

```text
projects.user_id = 当前用户
projects.guest_session_id = NULL
```

项目不能同时属于用户和游客，也不能两者都没有归属。

---

# 5. 项目体系

## 5.1 projects

### 作用

项目主表，是整个产品的核心业务容器。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| public_id | VARCHAR(255) | 否 | 外部稳定 ID，如 `prj_orders`，全局 UNIQUE |
| user_id | UUID | 是 | 所属正式用户 |
| guest_session_id | UUID | 是 | 所属游客 |
| name | VARCHAR(200) | 否 | 项目名称 |
| description | TEXT | 是 | 项目描述 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `user_id` | `users.id` | `CASCADE` |
| `guest_session_id` | `guest_sessions.id` | `NO ACTION` |

`user_id` 用 `CASCADE`：项目属于用户，删除用户即删除其项目。

`guest_session_id` 用 `NO ACTION` 而非 `CASCADE`：**游客会话过期不应静默销毁其项目**。
两者都**不能**用 `SET NULL`——见下面的 XOR 约束。

### 约束

```text
CONSTRAINT ck_projects_owner_xor CHECK (
  (user_id IS NOT NULL AND guest_session_id IS NULL)
  OR
  (user_id IS NULL AND guest_session_id IS NOT NULL)
)
```

即项目必须且只能属于一个用户身份。

### XOR 约束带来的两条硬限制

**一、两个归属列都不能用 `SET NULL`。**
把 `user_id` 置空会留下 `(NULL, NULL)`，直接违约。所以 `projects.user_id`
与 `projects.guest_session_id` 的 `ON DELETE` 只能是 `CASCADE` 或 `NO ACTION`/`RESTRICT`。

**二、游客转正式用户必须是单条 UPDATE。**

```sql
UPDATE projects SET user_id = :u, guest_session_id = NULL WHERE id = :p;
```

PostgreSQL 的 CHECK 按 UPDATE **之后**的行像求值，不关心中间状态，所以这是合法的。
但**绝不能拆成两条 UPDATE**（或在 ORM 里分两次 flush）——中间态 `(NULL, NULL)` 必然违约。
CHECK 也**不可延迟**：PostgreSQL 只允许 FK / UNIQUE / EXCLUDE 声明 `DEFERRABLE`。

---

## 5.2 api_specs

### 作用

保存用户上传的 OpenAPI / API 文档原始内容。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| project_id | UUID | 否 | 所属项目 |
| name | VARCHAR(200) | 否 | 文档名称 |
| slug | VARCHAR(255) | 否 | 内容派生标识：`<标题或文件名>_<内容哈希>` |
| spec_type | VARCHAR(30) | 否 | 规范方言：`openapi-3` / `swagger-2` |
| content_format | VARCHAR(20) | 否 | 序列化格式：`json` / `yaml` |
| version | VARCHAR(50) | 是 | 文档中声明的 API 版本 |
| source | VARCHAR(30) | 否 | 来源：`demo` / `upload` / `paste` / `handoff` |
| filename | VARCHAR(500) | 是 | 上传时的原始文件名 |
| server_url | VARCHAR(1000) | 是 | 文档中声明的 server URL |
| content | TEXT | 否 | 原始文档内容 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `project_id` | `projects.id` | `CASCADE` |

### 约束

```text
UNIQUE (project_id, slug)   -- uq_api_specs_project_slug
```

### 为什么 spec_type 和 content_format 是两个字段

`openapi-3 / swagger-2` 是**规范方言**，`json / yaml` 是**序列化格式**，两者正交。
合成一个 `format` 字段会让 `openapi-3 + yaml` 无法表达。

### slug 是唯一的外部标识，不另存 public_id

`slug` 是**内容派生**的（标题或文件名 slug 化 + 内容哈希），其派生规则**不含项目信息**：
两个项目上传同一份文档会得到相同的 slug，所以唯一性只能是项目范围，不能是全局。

前端 `ApiSpec.id` 就是 `spec_${slug}`。本表**不再存储**等价的 `public_id` 列——
那会让数据库里有两个代表同一个外部 ID 的字段。需要对外 ID 时由 API 层拼：

```text
spec_${slug}
```

`slug` 还被下游 ID 派生使用（`plan_${spec.slug}`），所以它是被保留下来的那一列。

### 关于唯一约束的命名

本项目 `MetaData` 的命名约定用 `%(table_name)s` + **首列**生成唯一约束名，
按约定这里会得到 `uq_api_specs_project_id`——名字有误导性（读起来像"project_id 唯一"），
因此显式命名为 `uq_api_specs_project_slug`。

`environments` 的情况更严重：它有两个都以 `project_id` 开头的唯一约束，
会**争用同一个名字**，必须显式命名。

---

## 5.3 api_endpoints

### 作用

保存从 API Spec 解析出来的接口定义，供 API Client、Agent 和测试计划使用。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| public_id | VARCHAR(255) | 否 | 外部稳定 ID，如 `ep_post_api_orders` |
| spec_id | UUID | 否 | 所属 API Spec |
| method | VARCHAR(20) | 否 | GET / POST / PUT / PATCH / DELETE 等 |
| path | VARCHAR(1000) | 否 | API 路径 |
| operation_id | VARCHAR(255) | 是 | OpenAPI operationId |
| name | VARCHAR(255) | 是 | 接口名称 |
| description | TEXT | 是 | 接口描述 |
| tags | JSONB | 是 | 标签 |
| request_schema | JSONB | 是 | 请求结构 |
| response_schema | JSONB | 是 | 响应结构 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `spec_id` | `api_specs.id` | `CASCADE` |

### 约束

```text
UNIQUE (spec_id, public_id)   -- uq_api_endpoints_spec_public_id
```

作用域是 `spec_id` 而不是 `project_id`：本表没有 `project_id`，
而它编码的规则——一份文档里 method + path 唯一——是 OpenAPI 对文档的不变量。

### 为什么需要 updated_at

接口是从文档解析出来的，文档重新解析就会重建这批行。
没有 `updated_at` 就无法做增量同步、缓存失效或"自某时刻起变更"的查询。

---

## 5.4 environments

### 作用

保存项目运行环境，例如开发、测试、生产。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| public_id | VARCHAR(255) | 否 | 外部稳定 ID，如 `env_orders_staging` |
| project_id | UUID | 否 | 所属项目 |
| name | VARCHAR(100) | 否 | 环境名称 |
| kind | VARCHAR(20) | 否 | `development` / `staging` / `production` |
| base_url | VARCHAR(1000) | 否 | 基础 URL |
| is_default | BOOLEAN | 否 | 是否默认环境 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `project_id` | `projects.id` | `CASCADE` |

### 约束

```text
UNIQUE (project_id, name)        -- uq_environments_project_name
UNIQUE (project_id, public_id)   -- uq_environments_project_public_id

CREATE UNIQUE INDEX uq_environments_one_default
  ON environments (project_id) WHERE is_default
```

### is_default 用部分唯一索引

`is_default` 是普通布尔列，本身不保证"每个项目至多一个默认环境"。
用**部分**唯一索引只在 `is_default` 为真的行上施加约束，
于是项目可以有任意多个环境，但默认环境只能有一个。

`environment_auths.is_default` 同理（见 §5.6）。

---

## 5.5 environment_variables

### 作用

保存用户主动配置的环境变量。

例如：

```text
BASE_URL
USER_ID
TENANT_ID
API_VERSION
TOKEN
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| environment_id | UUID | 否 | 所属环境 |
| key | VARCHAR(255) | 否 | 变量名 |
| value_encrypted | TEXT | 否 | 加密后的变量值 |
| is_secret | BOOLEAN | 否 | 是否敏感变量 |
| enabled | BOOLEAN | 否 | 是否启用 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `environment_id` | `environments.id` | `CASCADE` |

### 约束

```text
UNIQUE (environment_id, key)   -- uq_environment_variables_environment_id
```

### 注意

运行过程中提取出来的动态变量，例如 `access_token`、`order_id`，不应该直接覆盖这里的持久化环境变量。

`value_encrypted` 只是一个 `TEXT` 列，加解密是应用层的职责。
Model 中**刻意不做**透明解密：没有 `TypeDecorator`、没有 `@validates` 钩子、
没有返回明文的 hybrid property——那会把密钥管理耦合进 ORM，并让调用方无法判断手里是密文还是明文。

---

## 5.6 environment_auths

### 作用

保存环境下的 API 认证配置。

这里的“认证”指的是 API 测试中的身份认证，例如登录以后得到 Token，后续 API 需要带上 Token 才能访问。

### 支持类型

第一版建议支持：

```text
bearer
api_key
cookie
basic
```

以后可以扩展 OAuth2、JWT 等更复杂方案。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| environment_id | UUID | 否 | 所属环境 |
| name | VARCHAR(100) | 否 | 认证配置名称 |
| auth_type | VARCHAR(30) | 否 | bearer / api_key / cookie / basic |
| config | JSONB | 否 | 认证配置结构 |
| is_default | BOOLEAN | 否 | 是否默认认证 |
| is_enabled | BOOLEAN | 否 | 是否启用 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `environment_id` | `environments.id` | `CASCADE` |

### 约束

```text
CREATE UNIQUE INDEX uq_environment_auths_one_default
  ON environment_auths (environment_id) WHERE is_default
```

与 `environments.is_default` 同样的部分唯一索引，保证每个环境至多一个默认认证配置。

### 认证示例

Bearer Token：

```json
{
  "header": "Authorization",
  "scheme": "Bearer",
  "token": "{{access_token}}"
}
```

Cookie：

```json
{
  "name": "session_id",
  "value": "{{session_id}}"
}
```

### 注意

`config` 中涉及 Token、API Key、Cookie、密码等敏感内容时，应用层必须保证敏感值加密后再持久化，不能因为使用 JSONB 就直接明文保存。

---

## 5.7 request_collections

### 作用

保存 API Client 左侧的请求集合和目录。

例如：

```text
Orders
├── List orders
├── Create order
├── Get order
└── Delete order

Auth
├── Login
└── Refresh Token
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| project_id | UUID | 否 | 所属项目 |
| parent_id | UUID | 是 | 父集合，用于目录嵌套 |
| name | VARCHAR(255) | 否 | 集合名称 |
| sort_order | INTEGER | 否 | 排序 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `project_id` | `projects.id` | `CASCADE` |
| `parent_id` | `request_collections.id` | `CASCADE` |

### 注意：递归结构是前端模型的超集

前端只支持固定两层（collection → folder → request），并明确拒绝无限树。
本表的 `parent_id` 自引用可以表达任意深度，因此是前端模型的**超集**。

PostgreSQL 无法用 CHECK 表达"不能成环"，外键也无法阻止 `parent_id` 指向**另一个项目**的集合。
所以"同项目 + 最多两层 + 无环"这三条不变量由服务层负责，不要试图用触发器解决。

### 注意：自引用关系不参与 eager loading

`parent` 与 `children` 两侧都使用 `lazy="raise"`。
若给 `parent` 设 `lazy="joined"`，自引用 join 会沿祖先链递归，必须显式限制 `join_depth`；
用 `raise` 直接规避。

---

## 5.8 saved_requests

### 作用

保存 API Client 中用户手动配置并希望长期保留的 API 请求。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| project_id | UUID | 否 | 所属项目 |
| collection_id | UUID | 是 | 所属请求集合 |
| environment_id | UUID | 是 | 默认使用的环境 |
| name | VARCHAR(255) | 否 | 请求名称 |
| method | VARCHAR(20) | 否 | HTTP 方法 |
| url | TEXT | 否 | 请求 URL |
| params | JSONB | 是 | Query 参数 |
| headers | JSONB | 是 | 请求头 |
| auth | JSONB | 是 | 请求级认证配置 |
| body | JSONB | 是 | 请求体 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `project_id` | `projects.id` | `CASCADE` |
| `collection_id` | `request_collections.id` | `SET NULL` |
| `environment_id` | `environments.id` | `SET NULL` |

`collection_id` 用 `SET NULL` 而非 `CASCADE`：**删除目录不应静默销毁用户手写的请求**，
请求会被提升到项目根，而不是跟着目录一起消失。

---

# 6. Agent 测试体系

## 6.1 agent_tasks

### 作用

记录一次 Agent 测试任务，即用户要求 Agent 分析并生成测试设计的任务。

例如：

```text
“分析订单系统，重点测试支付失败、重复支付和鉴权异常。”
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| project_id | UUID | 否 | 所属项目 |
| spec_id | UUID | 否 | 使用的 API Spec |
| environment_id | UUID | 是 | 目标环境 |
| prompt | TEXT | 否 | 用户给 Agent 的任务要求 |
| status | VARCHAR(30) | 否 | pending / analyzing / completed / failed |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `project_id` | `projects.id` | `CASCADE` |
| `spec_id` | `api_specs.id` | `NO ACTION` |
| `environment_id` | `environments.id` | `SET NULL` |

`spec_id` 是 `NO ACTION`（**不是 `RESTRICT`**）：一个 Agent Task 锚定在它实际读过的那份文档上，
删掉 spec 不应连带抹掉由它派生的计划与运行历史。选 `NO ACTION` 而非 `RESTRICT` 的理由见 §14。

---

## 6.2 test_plans

### 作用

保存 Agent 生成的测试计划。

测试计划表达的是：

> **应该怎么测试。**

### 状态

```text
draft
in_review
approved
rejected
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| public_id | VARCHAR(255) | 否 | 外部稳定 ID，如 `plan_orders_1a2b3c4d` |
| agent_task_id | UUID | 是 | 来源 Agent Task |
| project_id | UUID | 否 | 所属项目 |
| spec_id | UUID | 否 | 计划所依据的 API Spec |
| version | INTEGER | 否 | 测试计划版本，默认 1 |
| name | **JSONB** | 否 | 计划名称（`LocalizedText`） |
| description | **JSONB** | 是 | 计划目标/描述（`LocalizedText`） |
| status | VARCHAR(30) | 否 | draft / in_review / approved / rejected |
| risk_level | VARCHAR(20) | 否 | low / medium / high |
| source | VARCHAR(30) | 否 | generated / handoff |
| approved_at | TIMESTAMPTZ | 是 | 审批时间 |
| rejected_at | TIMESTAMPTZ | 是 | 驳回时间 |
| rejection_reason | TEXT | 是 | 驳回理由，由审核人输入，非生成 |
| deleted_at | TIMESTAMPTZ | 是 | **软删除**标记 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `agent_task_id` | `agent_tasks.id` | `SET NULL` |
| `project_id` | `projects.id` | `CASCADE` |
| `spec_id` | `api_specs.id` | `NO ACTION` |

`agent_task_id` 可空且 `SET NULL`：计划可以有独立于 Agent Task 的来源，
且它自身有 `project_id` 作为锚点。

### 约束

```text
UNIQUE (project_id, public_id)   -- uq_test_plans_project_public_id
```

### 为什么 name / description 是 JSONB

前端 `TestPlan.name` 与 `TestPlan.goal` 的类型是：

```ts
type LocalizedText = { key: string, params?: ... } | { text: string }
```

应用自己撰写的文案是 i18n key，模型生成的或用户改名后的是字面量。
`VARCHAR` 装不下这个联合类型——直接存会得到 `"[object Object]"`。

### 软删除

`deleted_at` 是软删除锚点。**Test Run 是历史证据，不能因为删除计划而消失**，
所以 `test_runs.plan_id` 用 `NO ACTION`，删除计划走 `deleted_at` 而不走 `DELETE`。

### 版本原则

一个测试计划可以产生多个版本；Test Run 必须指向实际执行时使用的具体 `test_plans.id`，不能只依赖名称。

⚠️ **已知建模缺口——本阶段有意保留，不修**：`version` 目前没有版本分组列
（`root_plan_id` / `plan_group_id`），也没有 `UNIQUE(project_id, name, version)`。
多个版本目前只是若干个同名行，无法可靠地找出"同一计划的第 2 版"。

**"同一测试计划多版本的分组管理" 是未来的增强能力，不属于当前阶段。**
本阶段只保留 `version INTEGER` 这一列本身。

---

## 6.3 test_workflows

> **⏸ 第二批，尚未实现。**
> 本表不属于第一批 17 张表，`src/backend/db/models/` 下没有对应的 Model。
>
> 延后是干净的：`test_plans` 没有任何指向 workflow 的列或外键，
> 依赖方向是单向的 `test_workflows.plan_id → test_plans.id`，
> 因此第二批追加时是纯增量、零回填。
>
> 另需注意：前端**没有**与本表对应的类型。UI 上的 "workflow" 指的是 Agent 流水线
> （`PIPELINE_STEPS`），不是计划里的节点图。`nodes` / `edges` 目前没有任何消费方，
> 其结构应在实现前先定义。

### 作用

保存测试计划对应的工作流结构。

例如：

```text
登录
  ↓
获取 Token
  ↓
创建订单
  ↓
查询订单
  ↓
支付
  ↓
检查支付结果
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| plan_id | UUID | 否 | 所属 Test Plan |
| name | VARCHAR(255) | 否 | 工作流名称 |
| nodes | JSONB | 否 | 工作流节点 |
| edges | JSONB | 否 | 工作流连线 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

- `plan_id → test_plans.id`

---

## 6.4 test_scenarios

### 作用

保存 Test Plan 中的测试场景。

例如：

```text
正常创建订单
支付成功
重复支付
未授权访问
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| plan_id | UUID | 否 | 所属测试计划 |
| scenario_key | VARCHAR(100) | 否 | 稳定业务 ID，对外即场景 ID |
| name | **JSONB** | 否 | 场景名称（`LocalizedText`） |
| description | **JSONB** | 是 | 场景描述（`LocalizedText`） |
| expected | **JSONB** | 是 | 预期结果（`LocalizedText`） |
| risk_level | VARCHAR(20) | 否 | low / medium / high |
| sort_order | INTEGER | 否 | 排序 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `plan_id` | `test_plans.id` | `CASCADE` |

### 约束

```text
UNIQUE (plan_id, scenario_key)   -- uq_test_scenarios_plan_id
```

`scenario_key` 是 run 侧要回显的稳定键，见 §0 双 ID 约定与 §7.4 的回显契约。

---

## 6.5 test_steps

### 作用

保存测试场景中的测试步骤定义。

重要原则：

> **Test Step 是“测试计划操作”，不是一次实际 HTTP 请求结果。**

例如：

```text
Step 1：调用登录接口
Step 2：提取 access_token
Step 3：调用创建订单接口
Step 4：检查订单状态
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| scenario_id | UUID | 否 | 所属测试场景 |
| step_key | VARCHAR(100) | 否 | 稳定业务 ID，对外即步骤 ID |
| description | **JSONB** | 否 | 步骤描述（`LocalizedText`） |
| step_type | VARCHAR(50) | 否 | request / extract / assert 等 |
| endpoint_id | UUID | 是 | 关联 API Endpoint |
| depends_on | JSONB | 是 | 依赖的其他步骤（步骤 key 列表） |
| config | JSONB | 否 | 步骤配置 |
| produces | VARCHAR(255) | 是 | 本步骤产出的变量名（extract 步骤） |
| consumes | JSONB | 是 | 本步骤消耗的变量名列表 |
| sort_order | INTEGER | 否 | 顺序 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `scenario_id` | `test_scenarios.id` | `CASCADE` |
| `endpoint_id` | `api_endpoints.id` | `SET NULL` |

`endpoint_id` 用 `SET NULL`：重新上传/解析文档会重建 `api_endpoints`，
丢失一个接口不应该连带删除引用它的测试步骤。

### 约束

```text
UNIQUE (scenario_id, step_key)   -- uq_test_steps_scenario_id
```

### 为什么字段叫 description 而不是 name

前端 `TestStep` 只有 `description: LocalizedText`，没有 `name`。
沿用 `name` 会让 API 层出现"列名 name、字段名 description"的静默错配。

### produces / consumes 不建表

它们是**变量名**，不是外键。系统中没有"变量"实体可以指向——
一次运行的变量属于该运行自己的上下文（见 §10.3）。
用 `produces VARCHAR(255)` 与 `consumes JSONB` 直接承载即可，不要为此新建表。

### config 的结构尚未定义

`config` 是 NOT NULL 的 JSONB，但**其结构随 `step_type` 变化，本文档未定义**。
同一情况的还有 `environment_auths.config`（只定义了 bearer 与 cookie 两种形状，
`api_key` / `basic` 未定义）。这三处 JSONB 的结构必须在写 Pydantic 层之前先定下来。

### depends_on 是设计上的完整性空洞

`depends_on` 存的是**步骤 key 字符串**，无法用外键约束：
不保证被引用步骤存在于同一场景，不保证引用的是**更早**的步骤（可形成环），
被引用步骤删除后也不会报错。
这是 JSONB 方案的既定代价，存在性与无环校验由服务层负责。

---

## 6.6 test_assertions

### 作用

保存测试断言定义。

例如：

```text
HTTP Status == 200
response.data.id != null
response.data.status == "paid"
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| scenario_id | UUID | 否 | 所属场景 |
| step_id | UUID | 是 | 所属步骤；为 NULL 表示场景级断言 |
| assertion_key | VARCHAR(100) | 否 | 稳定业务 ID，对外即断言 ID |
| assertion_type | VARCHAR(50) | 否 | status / field / schema / header 等 |
| target | VARCHAR(255) | 否 | 断言目标，如 `body.token` 或 `status` |
| expression | TEXT | 是 | 断言表达式 |
| expected_value | JSONB | 是 | 期望值 |
| description | **JSONB** | 是 | 断言说明（`LocalizedText`） |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |
| updated_at | TIMESTAMPTZ | 否 | 更新时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `scenario_id` | `test_scenarios.id` | `CASCADE` |
| `step_id` | `test_steps.id` | `CASCADE` |

`step_id` 用 `CASCADE` 而**不是** `SET NULL`：
把 `step_id` 置空会把"步骤级断言"静默降级成"场景级断言"，**改变测试的语义**。

### 约束

```text
UNIQUE (scenario_id, assertion_key)   -- uq_test_assertions_scenario_id
```

### scenario_id 不是冗余字段，不能删

`scenario_id` 是 NOT NULL 而 `step_id` 可空，这是**正确的**：
场景级断言没有步骤可挂，`scenario_id` 是它唯一的锚点。

**注意 UNIQUE 的作用域是整个场景，不是单个步骤。**
Agent 生成 `assertion_key` 时必须按步骤命名空间化（如 `{step_key}.{name}`），
否则同场景两个步骤都生成 `status_200` 时第二次插入就会 `UniqueViolation`。

改用 `UNIQUE(step_id, assertion_key)` 更糟：PostgreSQL 默认认为 NULL 彼此不等，
场景级断言（`step_id IS NULL`）将**完全不受约束**，一条也拦不住。

### 可选的加固：复合外键（本批未采用）

让 `test_steps` 增加 `UNIQUE(id, scenario_id)`，然后：

```sql
FOREIGN KEY (step_id, scenario_id) REFERENCES test_steps (id, scenario_id)
```

可以根治"`step_id` 属于另一个场景"的问题，且 `MATCH SIMPLE` 语义下
`step_id IS NULL` 会自动跳过校验。
但**必须同时保留**单列 `scenario_id → test_scenarios.id`，
否则场景级断言会完全绕过校验。属于可选升级项，第一批用两个普通外键即可。

---

# 7. 结果体系

## 7.1 api_request_history

### 作用

保存用户使用 API Client 手动发送请求后的历史。

这一张表与 Agent 测试的 `test_runs` 分开，因为它代表的是：

> **用户自己发的一次 API 请求。**

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| project_id | UUID | 否 | 所属项目 |
| saved_request_id | UUID | 是 | 来源保存请求 |
| environment_id | UUID | 是 | 使用环境 |
| method | VARCHAR(20) | 否 | HTTP 方法 |
| request_url | TEXT | 否 | **未解析的 URL 模板** |
| request_params | JSONB | 是 | Query 参数 |
| request_headers | JSONB | 是 | 请求头 |
| request_auth | JSONB | 是 | 请求级认证配置（`ApiAuth` 原样） |
| request_body | JSONB | 是 | 请求体 |
| response_status | INTEGER | 是 | HTTP 状态码 |
| response_headers | JSONB | 是 | 响应头 |
| response_body | TEXT | 是 | 响应内容 |
| size_bytes | INTEGER | 是 | 响应体积（字节） |
| duration_ms | INTEGER | 是 | 请求耗时 |
| error_message | TEXT | 是 | 请求错误 |
| created_at | TIMESTAMPTZ | 否 | 请求时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `project_id` | `projects.id` | `CASCADE` |
| `saved_request_id` | `saved_requests.id` | `SET NULL` |
| `environment_id` | `environments.id` | `SET NULL` |

历史行自带 `method` 与 URL，是自包含的：来源保存请求被编辑或删除后，这一行仍然读得通。

### request_url 是模板，不是最终 URL

```text
/api/orders/{{order_id}}      ← 存这个
https://api.stg.example.com/api/orders/order_90021   ← 不存这个
```

还原一条历史记录时必须把占位符带回来，否则还原出的请求被钉死在某一个 order id 上，
它原本依赖的变量就丢了。

**不存解析后的 URL**：当前前端没有任何代码会读它，
而这张表记录的是"用户组装了什么"，不是"某一次发送的报文"。
如果将来确实需要，再加 `resolved_url` 列。

### request_auth 不能由 request_headers 还原

前端 `ApiAuth` 是**平铺**存储的：

```ts
{ type, bearerToken, username, password, apiKeyName, apiKeyValue, apiKeyIn }
```

这是刻意的——编辑器是表单，填了 Bearer Token 再切到 Basic 再切回来，
不能把之前填的内容丢掉。而解析后的 header 列表已经丢失了这层信息，
所以必须单独存一份原样的 `request_auth`。

### 安全要求

请求历史可能包含：

```text
Authorization
Cookie
API Key
密码
Token
```

并且 `request_auth` 会**原样**保存这些凭据。
因此敏感字段必须支持脱敏或加密，不能默认把完整认证信息直接作为普通历史文本永久保存。

`ApiRequestHistory` 上**刻意没有定义 `__repr__`**：
SQLAlchemy 的默认 repr 不打印列值，唯一会泄漏它们的途径就是自己写一个。

---

## 7.2 test_runs

### 作用

保存一次完整的自动化测试执行。

测试计划表达“怎么测试”，Test Run 表达：

> **这一次真的执行了这个测试。**

### 状态

```text
queued
running
passed
failed
cancelled
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| project_id | UUID | 否 | 所属项目 |
| plan_id | UUID | 否 | 实际执行的测试计划版本 |
| spec_id | UUID | 否 | 本次运行使用的 API Spec |
| environment_id | UUID | **是** | 执行环境 |
| plan_name | **JSONB** | 否 | 计划名称**快照**（`LocalizedText`） |
| base_url | VARCHAR(1000) | 否 | 运行时的 base URL **快照** |
| status | VARCHAR(30) | 否 | queued / running / passed / failed / cancelled |
| started_at | TIMESTAMPTZ | 是 | 开始时间 |
| finished_at | TIMESTAMPTZ | 是 | 结束时间 |
| variable_keys | JSONB | 是 | 本次运行产生/使用的变量名，**不保存变量值** |
| error_code | VARCHAR(100) | 是 | 错误编码 |
| error_message | TEXT | 是 | 错误信息 |
| created_at | TIMESTAMPTZ | 否 | 创建时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `project_id` | `projects.id` | `CASCADE` |
| `plan_id` | `test_plans.id` | `NO ACTION` |
| `spec_id` | `api_specs.id` | `NO ACTION` |
| `environment_id` | `environments.id` | `SET NULL` |

### 历史一致性原则

Test Run 创建后，应保持执行时的数据快照，不因为后续 Test Plan 被编辑而改变历史结果。

### 三处刻意的快照

**`plan_name` 是 JSONB 快照。**
计划被改名或重新生成后，历史 run 的名称不能跟着变。

**`base_url` 必须记录，不能从 environment 反查。**
环境名或 URL 改了以后，去 `environments` 表反查会把一条 Staging 的历史 run
重新标成 Production，而界面上没有任何东西提示它变了。

**`variable_keys` 只存名字，不存值。**
环境变量可能包含密钥，而运行历史不是堆积密钥副本的地方。
接口响应里也必须只回 `variableKeys`，绝不回显 `variables` 的值。

### environment_id 可空

`environment_id` 允许为 NULL 且 `ON DELETE SET NULL`：
删除一个环境不应连带删除曾经针对它跑过的 run，而 `base_url` 快照仍能解释这些历史。
（这也消除了与环境无关的 Agent Task 允许不指定环境这一设计之间的不一致。）

### plan_id 是 NO ACTION，配合 test_plans 的软删除

`plan_id` NOT NULL 且 `NO ACTION`：
计划用 `deleted_at` 软删除退休，运行历史不受影响；
而硬删一个仍被 run 引用的计划会被数据库拒绝。

**这里不能用 `RESTRICT`** —— 理由见 §14。

### 没有 updated_at

`started_at` / `finished_at` 已经覆盖了整条生命周期，再加 `updated_at` 是噪音。
`created_at` 上单独建了索引，列表接口按它倒序分页。

---

## 7.3 run_scenarios

> **⏸ 第二批，尚未实现。** 下表已包含本阶段确定的修正。

### 作用

记录某次 Test Run 中某个测试场景的实际执行结果。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | **本次运行自己的主键**，与 `source_scenario_id` 无关 |
| run_id | UUID | 否 | 所属 Test Run |
| source_scenario_id | UUID | **是** | 原 Test Scenario |
| scenario_key | VARCHAR(100) | 否 | 对外稳定 ID |
| name | **JSONB** | 否 | 场景名称快照（`LocalizedText`） |
| risk_level | VARCHAR(20) | **否** | 风险等级快照 |
| sort_order | INTEGER | **否** | 场景在计划中的顺序快照 |
| status | VARCHAR(30) | 否 | pending / running / passed / failed / skipped |
| started_at | TIMESTAMPTZ | 是 | 开始时间 |
| finished_at | TIMESTAMPTZ | 是 | 结束时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `run_id` | `test_runs.id` | `CASCADE` |
| `source_scenario_id` | `test_scenarios.id` | `SET NULL` |

### 本阶段确定的四处修正

**一、`source_scenario_id` 改为可空 + `SET NULL`。**
原文是 NOT NULL，与"运行结果是快照"这一承诺矛盾：
原场景被删除时，历史运行不能因此失去外键而失败。
`scenario_key` 与 `name` 快照已经足以让这一行独立可读。

**二、`name` 改为 JSONB。** 前端 `RunScenario.name` 是 `LocalizedText`。

**三、新增 `sort_order`。** 前端 `RunScenario.index` 是必填数字，
且注释强调 "in run order"。`started_at` 可空且可能相同，不能替代。

**四、新增 `risk_level`。** 前端 `RunScenarioCard` 直接渲染它。

### 历史原则

运行结果需要保留执行时的 `scenario_key` 和名称快照，不能只依赖实时 Test Scenario。

---

## 7.4 run_steps

### 作用

记录某次测试运行中每一步的实际执行结果。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | **本次运行自己的主键**，与 `source_step_id` 无关 |
| run_scenario_id | UUID | 否 | 所属运行场景 |
| source_step_id | UUID | **是** | 原 Test Step |
| step_key | VARCHAR(100) | 否 | 对外稳定 ID |
| description | **JSONB** | 否 | 步骤描述快照（`LocalizedText`） |
| step_type | VARCHAR(50) | **否** | 步骤类型快照：request / extract / assert |
| endpoint_id | UUID | **是** | 关联接口快照 |
| method | VARCHAR(20) | **是** | HTTP 方法快照 |
| path | VARCHAR(1000) | **是** | 路径快照 |
| sort_order | INTEGER | **否** | 步骤在场景中的顺序快照 |
| status | VARCHAR(30) | 否 | pending / running / passed / failed / skipped |
| started_at | TIMESTAMPTZ | 是 | 开始时间 |
| finished_at | TIMESTAMPTZ | 是 | 结束时间 |
| duration_ms | INTEGER | **是** | 实测耗时 |
| error_code | VARCHAR(100) | 是 | 错误编码 |
| error_message | TEXT | 是 | 错误信息 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `run_scenario_id` | `run_scenarios.id` | `CASCADE` |
| `source_step_id` | `test_steps.id` | `SET NULL` |
| `endpoint_id` | `api_endpoints.id` | `SET NULL` |

### 重要设计

不能直接把 `test_steps.id` 作为 `run_steps` 的主键。

原因：同一个 Test Step 可以执行很多次：

```text
Test Step A
   ├── Run 1 → Step A
   ├── Run 2 → Step A
   └── Run 3 → Step A
```

因此：

```text
run_steps.id             = 本次运行自己的数据库主键
run_steps.source_step_id = 来源 Test Step
run_steps.step_key       = 前端/业务稳定 ID
```

### 🔒 对外 ID 回显契约（最重要的一条）

**`run_steps.id` 这个内部 UUID 永远不出现在 API 载荷里。**

序列化时，JSON 中的 `id` 必须是 **`source_step_id` 回显值**——
也就是请求里 `plan` 那份 `TestStep.id` 的**逐字节副本**。
`run_scenarios` / `run_assertions` 同理。

原因：前端 `utils/runState.ts` 靠 **id 相等**把事件落到正确的步骤上，
**没有任何按位置匹配的兜底**。服务端一旦重命名这些 id，
详情页会渲染出一个所有状态都不更新的空壳，**而且不会报任何错**。

> 这是"照字段名直接写 Pydantic schema"必然踩中的坑：
> 直接把 `run_steps.id` 当 `id` 输出，前端全部静默冻结。

### 本阶段确定的三处修正

**一、`source_step_id` 改为可空 + `SET NULL`**，理由同 §7.3。

**二、`name` 改为 `description`（JSONB）。**
与 `test_steps` 保持一致，对齐前端 `RunStep.description`。

**三、新增 `step_type` / `method` / `path` / `sort_order` / `duration_ms` / `endpoint_id`。**
前端 `RunStep` 直接渲染 `index`、`kind`、`method`、`path`、`durationMs`，原字段清单一个都没有。
`method` 与 `path` 必须是**快照**而不是通过 `source_step_id` 反查——
反查会违反"计划被编辑后历史结果不变"这一原则。

---

## 7.5 run_assertions

### 作用

保存断言在本次运行中的实际结果。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 本次运行自己的主键 |
| run_scenario_id | UUID | **否** | 所属运行场景 |
| run_step_id | UUID | **是** | 所属运行步骤；NULL = 场景级断言 |
| source_assertion_id | UUID | **是** | 原 Test Assertion |
| assertion_key | VARCHAR(100) | 否 | 对外稳定 ID |
| assertion_type | VARCHAR(50) | 否 | 断言类型 |
| target | VARCHAR(255) | **否** | 断言目标 |
| expression | TEXT | 是 | 断言表达式 |
| expected_value | JSONB | 是 | 期望值 |
| actual_value | JSONB | 是 | 实际值 |
| description | **JSONB** | **是** | 断言说明快照（`LocalizedText`） |
| status | VARCHAR(20) | 否 | passed / failed / skipped |
| error_message | TEXT | 是 | 失败原因 |
| created_at | TIMESTAMPTZ | 否 | 时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `run_scenario_id` | `run_scenarios.id` | `CASCADE` |
| `run_step_id` | `run_steps.id` | `SET NULL` |
| `source_assertion_id` | `test_assertions.id` | `SET NULL` |

### ⚠️ 原设计的 `run_step_id NOT NULL` 是结构错误

原文规定 `run_step_id UUID NOT NULL`，且**没有场景维度列**。三处独立证据说明它写不进去：

```text
前端 types/run.ts:102     RunAssertion.stepId: string | null
前端 types/run.ts:292     assertionStepId: string | null
                         注释："Set when the assertion belongs to no particular step"
本文件 §6.6                计划侧自己写着"允许场景级断言"
```

场景级断言**根本没有 run_step 可挂**，NOT NULL 会让它直接插入失败。

修正：新增 `run_scenario_id UUID NOT NULL`，并把 `run_step_id` 改为可空。
这与计划侧的 `test_assertions`（`scenario_id` NOT NULL + `step_id` 可空）结构对称。

---

## 7.6 run_evidence

### 作用

保存测试执行过程中的证据，用于回答：

> **为什么这一步通过了，或者为什么失败了？**

典型证据：

```text
request
response
extraction
assertion
```

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| run_id | UUID | 否 | Test Run |
| run_step_id | UUID | 是 | 对应运行步骤 |
| evidence_type | VARCHAR(50) | 否 | request / response / extraction / assertion |
| label | **JSONB** | 否 | 证据标题（`LocalizedText`），原 `title` |
| value | **TEXT** | 否 | 具体产物：状态码、路径、字段名等，原样等宽显示 |
| content | JSONB | 是 | 结构化证据内容 |
| created_at | TIMESTAMPTZ | 否 | 时间 |

### 外键

| 列 | 指向 | ON DELETE |
|---|---|---|
| `run_id` | `test_runs.id` | `CASCADE` |
| `run_step_id` | `run_steps.id` | `SET NULL` |

### 两处修正

**一、`title` → `label`，类型改 JSONB。**
前端 `AgentEvidence.label` 是 `LocalizedText`；而且当前它的取值就是
前端字典里已有的 i18n key（`console.runs.evidence.endpoint` / `.extracted` / `.checked`），
后端**无法**把它解析成文本，只能原样存 JSON。

**二、新增 `value TEXT`。**
前端 `AgentEvidence.value` 是 `string` 且是必填，渲染时原样等宽显示。
没有这个列，证据卡片就没有可展示的内容。

**`content JSONB` 保留**，但当前前端没有任何消费方——
它是留给结构化证据（完整请求/响应报文）的扩展位。

---

## 7.7 run_events

### 作用

保存一次 Test Run 的事件流，为未来 SSE 实时更新和断线重连提供持久化基础。

当前前端事件模型包含：

```text
run.started
step.started
step.completed
assertion.completed
step.failed
run.completed
run.failed
run.cancelled
```

### ⚠️ 事件名以这 8 个为准

本文档早先的版本写的是 `run.created` / `run.finished`，**是错的**。前端
`src/types/run.ts` 的 `RUN_EVENT_NAMES` 是权威定义，其注释明写 "Exactly these, no more"。
差异有三处：

| 早先文档（错） | 实际（对） | 说明 |
|---|---|---|
| `run.created` | —— | 前端**不存在**；创建走纯 REST，不发事件 |
| `run.finished` | `run.completed` | 名称不同 |
| —— | `step.failed` | 早先文档**漏了**这一个 |

前端注释还专门解释了为何拒绝 `step.finished` 这类合并命名：
一个同时覆盖成功与失败的 `step.finished` 会让读类型的人无法判断运行是否顺利。

`run_events.event_type` 的取值必须按上面 8 个来。

### 字段

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---:|---|
| id | UUID | 否 | 主键 |
| run_id | UUID | 否 | 所属 Test Run |
| seq | BIGINT | 否 | 当前 Run 内单调递增的事件序号 |
| event_type | VARCHAR(50) | 否 | 事件类型 |
| payload | JSONB | 否 | 事件内容 |
| created_at | TIMESTAMPTZ | 否 | 事件时间 |

### 外键

- `run_id → test_runs.id`

### 约束

必须保证：

```text
UNIQUE(run_id, seq)
```

### 事件原则

同一个 Run：

```text
seq 1 → run.started
seq 2 → step.started
seq 3 → step.completed
seq 4 → assertion.completed
seq 5 → run.completed
```

`seq` 从 1 开始，在每个 Run 内**密集递增**（不跨 Run 全局唯一）。
前端只做"同 Run 内单调递增"的假设，并据此丢弃重复投递的事件。

未来 SSE 断线后可以按照 `fromSeq` 读取未收到的事件。
`RunDetail.lastSeq` 就是快照被取出时的 `MAX(seq)`，客户端据此确定高水位并订阅。

---

# 8. 测试计划与测试结果的关系

这是整个数据库里最重要的关系之一。

```text
Test Plan
   │
   │ 定义“怎么测试”
   ↓
Test Scenario
   ↓
Test Step
   ↓
Test Assertion

        ↓ 用户批准

Test Run
   │
   │ 记录“这一次实际执行”
   ↓
Run Scenario
   ↓
Run Step
   ↓
Run Assertion
```

因此不能把：

```text
TestStep
```

和：

```text
RunStep
```

设计成同一张表。

---

# 9. Agent 与手动测试的边界

## 9.1 手动 API 测试

不要求 Agent。

```text
Project
  ↓
Environment
  ↓
Saved Request
  ↓
API Client
  ↓
API Request History
```

## 9.2 Agent 测试

```text
Project
  ↓
API Spec
  ↓
Agent Task
  ↓
Test Plan
  ↓
Workflow / Scenario / Step / Assertion
  ↓
Test Run
  ↓
Run Result / Evidence / Events
```

这样 Agent 是一种测试入口，而不是整个系统的基础依赖。

---

# 10. 认证、Token、Cookie 的边界

认证数据容易和运行变量混淆，因此必须明确：

## 10.1 用户配置的认证规则

放在：

```text
environment_auths
```

例如：

```text
Bearer Token
Authorization: Bearer {{access_token}}
```

## 10.2 用户配置的固定环境值

放在：

```text
environment_variables
```

例如：

```text
BASE_URL
TENANT_ID
USER_ID
```

## 10.3 测试运行过程中产生的动态变量

属于一次 Test Run 的运行时上下文，例如：

```text
access_token
order_id
session_id
payment_id
```

它们不应该直接覆盖持久化环境变量。

---

# 11. JSONB 使用原则

本项目不需要把所有东西都拆成大量字段。

JSONB 在这里只服务**两类**东西，不要为了省事把普通字段也做成 JSONB。

### 第一类：结构本身不固定

```text
api_endpoints.tags                 标签数组
api_endpoints.request_schema       随文档变化
api_endpoints.response_schema      随文档变化
saved_requests.params              编辑器行对象数组
saved_requests.headers             编辑器行对象数组
saved_requests.auth                平铺的认证表单
saved_requests.body                请求体
api_request_history.request_params
api_request_history.request_headers
api_request_history.request_auth
api_request_history.request_body
api_request_history.response_headers
test_steps.depends_on              步骤 key 列表
test_steps.config                  随 step_type 变化
test_steps.consumes                变量名数组
test_assertions.expected_value     任意 JSON 期望值
test_runs.variable_keys            变量名数组
test_workflows.nodes               （第二批）
test_workflows.edges               （第二批）
run_assertions.expected_value      （第二批）
run_assertions.actual_value        （第二批）
run_evidence.content               （第二批）
run_events.payload                 （第二批）
```

### 第二类：LocalizedText

前端存在这个联合类型：

```ts
type LocalizedText = { key: string, params?: ... } | { text: string }
```

应用自己撰写的文案是 i18n key，来自文档或模型的、以及用户改名后的是字面量。
**`VARCHAR` 装不下这个联合类型**——直接存字符串化会得到 `"{'key': '...'}"` 这种非法 JSON。

因此下列列是 JSONB：

```text
test_plans.name                 test_plans.description
test_scenarios.name             test_scenarios.description        test_scenarios.expected
test_steps.description
test_assertions.description
test_runs.plan_name
run_scenarios.name              （第二批）
run_steps.description           （第二批）
run_assertions.description      （第二批）
run_evidence.label              （第二批）
```

### 其余一律普通字段

具有明确关系、需要查询和关联的数据，仍然使用普通字段 + 外键。
判断标准：**能被 WHERE / JOIN / ORDER BY 用到的，就不是 JSONB。**

---

# 12. 第一阶段实现范围

虽然完整业务模型包含 23 张表，但第一次 Alembic migration 只实现 17 张。

> **✅ 已实现。** 这 17 张表的 SQLAlchemy Model 位于 `src/backend/db/models/`，
> 已通过 `configure_mappers()` 与 Alembic metadata diff 验证（17 张表 + 31 个索引，无其他差异）。
> **尚未生成 migration。**

## 第一批核心表

第一批 17 张：

### 用户

```text
users
guest_sessions
```

### 项目

```text
projects
api_specs
api_endpoints
environments
environment_variables
environment_auths
request_collections
saved_requests
```

### Agent 测试

```text
agent_tasks
test_plans
test_scenarios
test_steps
test_assertions
```

### 基础结果

```text
api_request_history
test_runs
```

## 第二批

等 Test Run 的完整执行链路接入后再实现：

```text
test_workflows
run_scenarios
run_steps
run_assertions
run_evidence
run_events
```

> **⏸ 尚未实现。** `src/backend/db/models/` 下没有这 6 张表的 Model。
>
> 批次切分已验证是干净的：第一批 17 张表的全部外键目标里，没有一张引用第二批的表；
> `test_plans` 也没有指向 workflow 的列。因此第二批追加是**纯增量、零回填**。
>
> **注意**：§6.3 与 §7.3–§7.7 已对这 6 张表列出第一批阶段确定的**结构修正**
> （`run_scenarios` / `run_steps` / `run_assertions` 的字段补齐与 `source_*` 可空化，
> `run_assertions.run_step_id` 改可空并新增 `run_scenario_id` 等）。
> 实现第二批时必须按修正后的结构写，不要照抄任何旧版本。

---

# 13. 索引

## 13.1 命名约定

`Base` 的 `MetaData` 带统一命名约定，因此索引与约束的名字都是确定的、可预测的：

```python
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
```

这必须在建表**之前**引入：PostgreSQL 会给未命名约束自动起名，而自动名在"全新库"和
"由早期迁移演进出来的库"之间可能不同，日后任何 `drop_constraint` 都要靠猜。
等 17 张表建好再补，就得写一份大规模重命名迁移。

注意 `ck` 含 `%(constraint_name)s`：**任何未显式命名的 `CheckConstraint` 都会直接抛异常**。
这是刻意的——本项目所有 CHECK 都手工命名。

`uq` 只用**首列**生成名字，因此同一张表上两个都以同一列开头的复合唯一约束会**争用同一个名字**。
`environments` 属于这种情况（`project_id` + `name` / `project_id` + `public_id`），必须显式命名。

`api_specs` 只有一个唯一约束，不存在争用，但按约定会得到 `uq_api_specs_project_id`——
读起来像"project_id 唯一"，有误导性，因此同样显式命名。

## 13.2 第一批实际建立的索引（31 个）

```text
-- 外键列（PostgreSQL 不会为外键自动建索引）
ix_projects_user_id                     ix_projects_guest_session_id
ix_api_specs_project_id                 ix_api_endpoints_spec_id
ix_environment_auths_environment_id
ix_request_collections_project_id       ix_request_collections_parent_id
ix_saved_requests_project_id            ix_saved_requests_collection_id
ix_saved_requests_environment_id
ix_agent_tasks_project_id               ix_agent_tasks_spec_id
ix_agent_tasks_environment_id
ix_test_plans_project_id                ix_test_plans_agent_task_id
ix_test_plans_spec_id
ix_test_steps_endpoint_id               ix_test_assertions_step_id
ix_api_request_history_project_id       ix_api_request_history_saved_request_id
ix_api_request_history_environment_id
ix_test_runs_project_id                 ix_test_runs_plan_id
ix_test_runs_spec_id                    ix_test_runs_environment_id

-- 列表查询排序键
ix_api_request_history_created_at
ix_test_runs_created_at
ix_test_plans_deleted_at                （软删除过滤）
ix_guest_sessions_expires_at            （过期扫描）

-- 部分唯一索引
uq_environments_one_default             ON environments (project_id)      WHERE is_default
uq_environment_auths_one_default        ON environment_auths (environment_id) WHERE is_default
```

## 13.3 六条由 UNIQUE 约束免费覆盖，不要再建索引

这些列的索引已经由复合 UNIQUE 约束的**前缀**提供。再加 `index=True` 只会生成冗余索引：

| 列 | 由哪个约束覆盖 |
|---|---|
| `users.username` / `users.email` | 各自的 UNIQUE |
| `guest_sessions.session_token` | UNIQUE |
| `environments.project_id` | `uq_environments_project_name` 的前缀 |
| `environment_variables.environment_id` | `uq_environment_variables_environment_id` 的前缀 |
| `test_scenarios.plan_id` | `uq_test_scenarios_plan_id` 的前缀 |
| `test_steps.scenario_id` | `uq_test_steps_scenario_id` 的前缀 |
| `test_assertions.scenario_id` | `uq_test_assertions_scenario_id` 的前缀 |

> 实测反例：同时声明 `UniqueConstraint("project_id", "name")` 和 `project_id` 的
> `index=True`，会生成两条索引，后者完全冗余。

## 13.4 第二批（尚未建立）

```text
run_scenarios.run_id                    run_events.run_id
run_steps.run_scenario_id               run_events(run_id, seq)   -- UNIQUE，回放必需
run_assertions.run_step_id              run_assertions.run_scenario_id
run_evidence.run_id                     run_evidence.run_step_id
run_scenarios.source_scenario_id        run_steps.source_step_id
```

`UNIQUE(run_id, seq)` 不只是索引，它是未来 SSE 断线重连按 `fromSeq` 重放的基础。

---

# 14. 删除策略

核心张力：

```text
Project
  ↓
Test Plan
  ↓
Test Run
```

Test Run 是历史证据，**不应该因为 Test Plan 被编辑或删除就丢失**；
但 Project 又必须能整体删除。

## 14.1 每个外键的 ON DELETE 都是显式声明的

| 语义 | ON DELETE | 用在哪 |
|---|---|---|
| 子行随父行一起消失 | `CASCADE` | 容器关系：project → 其全部子表、plan → scenario → step → assertion |
| 父行删除后子行仍要存活 | `SET NULL` | 可空的弱引用：`saved_requests.collection_id`、`*.environment_id`、`test_plans.agent_task_id` |
| 父行被引用时禁止删除 | `NO ACTION` | 历史保护：`agent_tasks.spec_id`、`test_plans.spec_id`、`test_runs.plan_id`、`test_runs.spec_id`、`projects.guest_session_id` |

`SET NULL` **只用于可空列**。`projects.user_id` / `guest_session_id` 看似适合 `SET NULL`，
但它们受 XOR CHECK 约束，置空会直接违约导致 DELETE 失败（见 §5.1）。

## 14.2 ⚠️ 历史保护用 `NO ACTION`，不用 `RESTRICT`

这两者在 PostgreSQL 里**不等价**，而差异恰好决定项目能不能删：

- `RESTRICT` 在**级联过程中立即**检查。
- `NO ACTION` 推迟到**语句结束时**检查。

用 `RESTRICT` 的后果：

```sql
DELETE FROM projects WHERE id = :p;
-- 级联删除 test_plans 时，test_runs 的行可能还没被删掉，
-- RESTRICT 立刻报错 → 整条 DELETE 失败 → 项目删不掉
```

而 `ON DELETE CASCADE` 从 `projects` 到 `test_runs` 是另一条路径，
两条级联的先后顺序 PostgreSQL 不作保证。

`NO ACTION` 同时满足两个需求：

- 项目级联删除正常完成（语句结束时引用行已全部消失）；
- 单独硬删一个仍被引用的 spec / plan 依然被数据库拒绝。

## 14.3 软删除

`test_plans.deleted_at` 是软删除锚点：计划退休走 `UPDATE ... SET deleted_at = now()`，
历史 run 不受任何影响，也不需要真的删除任何行。

⚠️ **其余表没有软删除锚点。** 如果后续需要给 `projects` / `environments` 也加，
必须现在就想清楚——有数据之后再补 NOT NULL 列要写 `server_default` 回填。

## 14.4 游客会话过期

**本阶段不自动 CASCADE 删除游客项目。**
`projects.guest_session_id` 是 `NO ACTION`，因此：

```sql
DELETE FROM guest_sessions WHERE expires_at < now();
-- 一旦命中仍有项目的会话，就会抛外键违约
```

清理过期会话必须显式处理项目归属：

```sql
DELETE FROM guest_sessions g
WHERE g.expires_at < now()
  AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.guest_session_id = g.id);
```

"过期即刻销毁游客数据" 还是 "保留 N 天" 是产品决策，尚未确定。

## 14.5 ORM 层不设 cascade

Model 中**没有**任何 `cascade=` 参数。删除是数据库的职责：
每个外键带 `ondelete`，关系带 `passive_deletes=True`，
SQLAlchemy 只为被请求的那一行发一条 `DELETE`。

刻意避开 `cascade="all"`——它内含 `delete-orphan`，
而 `test_assertions` 同时属于 scenario 和 step 两个父级，
`delete-orphan` 无法同时声明在两侧。

---

# 15. 最终表清单

| 业务体系 | 表 | Model 类 | 文件 | 状态 | 作用 |
|---|---|---|---|---|---|
| 用户 | users | `User` | `user.py` | ✅ | 正式用户 |
| 用户 | guest_sessions | `GuestSession` | `user.py` | ✅ | 游客身份 |
| 项目 | projects | `Project` | `project.py` | ✅ | 项目主表 |
| 项目 | api_specs | `ApiSpec` | `project.py` | ✅ | API 原始文档 |
| 项目 | api_endpoints | `ApiEndpoint` | `project.py` | ✅ | API 接口定义 |
| 项目 | environments | `Environment` | `project.py` | ✅ | 开发/测试/生产环境 |
| 项目 | environment_variables | `EnvironmentVariable` | `project.py` | ✅ | 环境变量 |
| 项目 | environment_auths | `EnvironmentAuth` | `project.py` | ✅ | API 认证配置 |
| 项目 | request_collections | `RequestCollection` | `project.py` | ✅ | API Client 请求目录 |
| 项目 | saved_requests | `SavedRequest` | `project.py` | ✅ | 保存的 API 请求 |
| Agent | agent_tasks | `AgentTask` | `agent.py` | ✅ | Agent 测试任务 |
| Agent | test_plans | `TestPlan` | `agent.py` | ✅ | 测试计划 |
| Agent | test_workflows | `TestWorkflow` | `agent.py` | ⏸ 第二批 | 测试工作流 |
| Agent | test_scenarios | `TestScenario` | `agent.py` | ✅ | 测试场景 |
| Agent | test_steps | `TestStep` | `agent.py` | ✅ | 测试步骤定义 |
| Agent | test_assertions | `TestAssertion` | `agent.py` | ✅ | 测试断言定义 |
| 结果 | api_request_history | `ApiRequestHistory` | `result.py` | ✅ | 手动 API 请求历史 |
| 结果 | test_runs | `TestRun` | `result.py` | ✅ | 自动化测试执行 |
| 结果 | run_scenarios | `RunScenario` | `result.py` | ⏸ 第二批 | 场景执行结果 |
| 结果 | run_steps | `RunStep` | `result.py` | ⏸ 第二批 | 步骤执行结果 |
| 结果 | run_assertions | `RunAssertion` | `result.py` | ⏸ 第二批 | 断言执行结果 |
| 结果 | run_evidence | `RunEvidence` | `result.py` | ⏸ 第二批 | 测试证据 |
| 结果 | run_events | `RunEvent` | `result.py` | ⏸ 第二批 | Test Run 事件流 |

**总计：23 张逻辑表，其中第一批 17 张已实现。**

---

# 16. 工程前置（已就绪）

## 16.1 `Base` 与模型解耦

`src/backend/db/base.py` 承载 `Base` + `NAMING_CONVENTION` + 三个 mixin
（`UUIDPrimaryKeyMixin` / `CreatedAtMixin` / `TimestampMixin`）。

**它刻意不碰 engine、session 或环境变量**：导入一个模型模块不应该建立连接或读取 `.env`。
`database.py` 从它导入 `Base`，而不是反过来。

## 16.2 Alembic 能看见全部 17 张表

`alembic/env.py` 里有这一行：

```python
import backend.db.models  # noqa: F401
```

**没有它，autogenerate 会看到空 schema，从而生成一份空的 `upgrade()`——而不是报错。**
`models/__init__.py` 逐个导入 4 个模块，而导入 Model 模块正是把表注册到
`Base.metadata` 的唯一途径。

## 16.3 连接 URL 不走 `set_main_option`

**不要**使用：

```python
config.set_main_option("sqlalchemy.url", raw_url)   # ← 有问题
```

Alembic 的 `Config` 基于带**插值**的 ConfigParser，密码里的 `%` 会让它直接抛
`ValueError: invalid interpolation syntax`。

同时，手工拼接 URL 字符串也是错的：

```python
f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"   # ← 有问题
```

密码含 `@`、`:`、`#`、`/` 时会被解析错位。
（实测 `p@ss:w#rd` → `ValueError: invalid literal for int() with base 10: 'w#rd@127.0.0.1:5432'`）

正确做法：用 `sqlalchemy.URL.create()` 构造一次，engine 与 Alembic 都从
`backend.db.database` 取同一个 `database_url`。只有一个地方拼连接串。

## 16.4 依赖

```toml
"greenlet>=3.0",
```

**必须显式声明。** SQLAlchemy 的异步支持
（`AsyncSession` → greenlet 桥接）依赖它，但默认它只是经
**CPU 架构 marker** 传入的可选依赖：

```
platform_machine == 'AMD64' or ... or 'x86_64'
```

纯 async 项目一旦换到 marker 不匹配的平台，会在第一次 `await session.execute()`
才炸，而不是在安装时。

## 16.5 写 Model 时必须显式声明的三种类型

见 §0 的表格。三条都是**静默错误**——不报错、能跑，但：

- `Mapped[datetime]` → `TIMESTAMP WITHOUT TIME ZONE`，配合前端**字符串排序**会跨时区错序；
- `sa.JSON` → PG 的 `JSON` 而非 `JSONB`；
- `Mapped[str]` → **无长度**的 `VARCHAR`。

另外：**绝不要写 `Mapped[SomeStrEnum]`**。SQLAlchemy 2.0 会按类名推导出一个
**原生 PostgreSQL 枚举类型**（`CREATE TYPE ... AS ENUM`），与 §0 的枚举策略直接冲突。

---

# 17. 下一阶段

```text
SQLAlchemy Models              ✅ 完成（第一批 17 张）
        ↓
Foreign Keys / Constraints     ✅ 完成
        ↓
Alembic Migration              ← 下一步
        ↓
PostgreSQL
        ↓
FastAPI CRUD / Service
        ↓
前端 REST API 对接
```

第一阶段不实现 Agent 真正调用 LLM，也不实现真实 HTTP Execution Engine；
先把数据库基础模型和当前 Phase 6.2 REST 所需要的 `Project / Test Plan / Test Run` 数据链打通。

**本阶段已明确不处理的遗留项**（都不是阻塞项）：

| 项 | 处置 | 位置 |
|---|---|---|
| `test_plans.version` 的版本分组 | 保留 `version` 列，分组管理作为**未来增强** | §6.2 |
| `test_steps.config` / `environment_auths.config` 的 JSONB 结构 | **后续 Pydantic Schema / REST Contract 阶段**定义 | §6.5、§5.6 |
| 游客会话过期后的数据处置 | 策略未定；本阶段不做自动 CASCADE | §14.4 |
| `run_*` 的行动线 | 第二批实现，结构修正已在文档标注 | §7.3–§7.7 |

已解决：`api_specs` 的 `slug` / `public_id` 同源冗余 —— 已删除 `public_id`（§5.2）。
