# 小C助手（C Assistant）

基于 **FastAPI** 与静态前端（HTML / CSS / JS）的旅行助手：多智能体对话（天气、地图、行程规划）、WebSocket 流式回复、会话历史、高德逆地理与路线、管理员 RAG 上传等。对话模型通过 **LangChain** `create_agent` 调用 **阿里云 DashScope（通义）** `ChatTongyi`。

---
依赖安装：
`pip install -r requirements.txt`

## 目录结构与各代码包说明

### 目录树（概览）

```
小C助手/
├── backend/                      # FastAPI 后端工程根目录
│   ├── .env.example              # 环境变量模板（复制为 .env）
│   ├── .env                      # 本地密钥（勿提交；见 .gitignore）
│   ├── requirements.txt          # Python 依赖
│   ├── chroma_db/                # Chroma 持久化目录（运行期生成；默认被 .gitignore 忽略）
│   └── app/
│       ├── __init__.py
│       ├── main.py               # FastAPI 应用：路由挂载、CORS、启动时建表与管理员引导
│       ├── config.py             # Pydantic Settings：从 backend/.env 读取配置
│       ├── db.py                 # SQLAlchemy Engine、Session、get_db
│       ├── security.py           # JWT 签发/解析、密码哈希与校验
│       ├── api/                  # HTTP / WebSocket 路由层
│       ├── agents/               # LangChain 多智能体（通义模型）
│       ├── services/             # 业务编排与外部服务封装
│       ├── tools/                # 供智能体调用的 LangChain Tools
│       ├── rag/                  # 管理员上传、向量库与 Neo4j 写入
│       ├── models/               # ORM：用户、聊天记录
│       ├── schemas/              # Pydantic：鉴权、聊天、历史的请求/响应模型
│       └── data/                 # 只读静态数据（城市码、风俗 CSV 等）
├── frontend/                     # 无构建步骤的静态站点
│   ├── index.html / main.js      # 主聊天页与 WS 流式逻辑
│   ├── login.html / register.html / auth.js
│   ├── admin-login.html / admin-login.js
│   ├── rag.html                  # 管理员 RAG 上传页
│   ├── common.js / style.css / favicon.ico
│   ├── assets/                   # 图片等静态资源
│   └── vendor/                   # marked、DOMPurify 等第三方脚本
├── start-assistant.bat           # Windows：起后端 Uvicorn + 前端 http.server + 打开浏览器
├── stop-assistant.bat            # Windows：按端口结束监听进程
├── README.md
└── .gitignore
```

### 仓库根目录

| 路径 | 功能 |
|------|------|
| `start-assistant.bat` / `stop-assistant.bat` | 一键启停默认端口 **8000**（后端）与 **5500**（前端静态服务）。 |
| `README.md` | 项目说明与运维指引。 |
| `.gitignore` | 忽略 `.env`、`backend/chroma_db/`、虚拟环境、IDE 配置等。 |

### `backend/`（后端工程）

| 路径 | 功能 |
|------|------|
| `requirements.txt` | 生产/开发依赖清单。 |
| `.env.example` | 环境变量说明与占位符，复制为 `.env` 后填写真实值。 |
| `.env` | 实际运行配置（API Key、数据库 DSN 等），**不要**提交到 Git。 |
| `chroma_db/` | Chroma 向量库持久化目录（与 `chroma_client` 等共用）；损坏时可删目录后重新上传入库。 |

### `backend/app/` 根文件

| 文件 | 功能 |
|------|------|
| `main.py` | 创建 `FastAPI` 实例，注册 `auth` / `history` / `location` / `rag_admin` / `ws` 路由；启动时执行 PG 轻量迁移、可选创建管理员。 |
| `config.py` | `Settings`：Neo4j、PostgreSQL、JWT、和风、高德、管理员密码等，自 `backend/.env` 加载。 |
| `db.py` | SQLAlchemy `engine`、`SessionLocal`、`Base`，供 ORM 与依赖注入使用。 |
| `security.py` | `hash_password` / `verify_password`；`create_access_token`；`decode_access_token` 等 JWT 逻辑。 |

### `backend/app/api/`（路由层）

| 模块 | 功能 |
|------|------|
| `auth.py` | 用户注册、登录，返回 JWT。 |
| `history.py` | 按用户拉取聊天历史列表。 |
| `location.py` | 高德逆地理等位置相关 HTTP 接口。 |
| `rag_admin.py` | 管理员上传文件（multipart），调用 `rag.ingest_file` 入库。 |
| `ws.py` | WebSocket `/ws/chat`：鉴权、会话、流式调用 `AssistantService`。 |
| `deps.py` | FastAPI 依赖：`get_current_user`、`get_current_admin_user` 等。 |

### `backend/app/agents/`（智能体）

| 模块 | 功能 |
|------|------|
| `tongyi_llm.py` | 封装 `ChatTongyi`（DashScope），统一模型名、`enable_thinking` 等与重试策略。 |
| `agent_for_planner.py` | **行程规划**智能体：`create_agent` + 套餐/地图/天气/RAG/风俗/预算等工具集。 |
| `agent_for_weather.py` | **天气**智能体：和风预报 + 季节/安全提示类工具。 |
| `agent_for_map.py` | **地图**智能体：地理编码、路线、周边酒店/餐饮、用户定位等。 |

### `backend/app/services/`（业务与基础设施）

| 模块 | 功能 |
|------|------|
| `assistant_service.py` | 对外统一助手入口：按 `agent` 类型选择天气/地图/规划智能体并返回正文与工具轨迹。 |
| `planner_query_builder.py` | 为规划智能体拼接「偏好摘要 + 用户行程上下文 + 原始 query」。 |
| `user_travel_context.py` | 从 PostgreSQL 读取用户近期对话，生成规划用的历史消息片段。 |
| `preference_extractor.py` | 从自然语言中抽取结构化偏好（目的地、天数、预算等）供规划增强。 |
| `chroma_client.py` | Chroma 单例、嵌入（Ollama）、加文档与相似度检索；与 `travel_deals` / `rag_kb` 共用持久目录。 |
| `travel_package_query.py` | 与 Neo4j / 套餐检索相关的查询辅助（供工具层使用）。 |
| `amap_route_service.py` | 高德驾车路线等 REST 封装，供地图工具调用。 |
| `tool_trace.py` | 从 LangChain 消息列表中提取工具名与返回摘要，供前端展示「用了哪些工具」。 |

### `backend/app/tools/`（LangChain Tools）

| 模块 | 功能 |
|------|------|
| `get_map.py` | 地理编码、路线、周边 POI、`get_user_location` 等地图类工具。 |
| `get_weather.py` | 和风 `qweather_forecast` 等多日预报工具。 |
| `get_tips.py` | 出行安全、季节提示等文案类工具。 |
| `get_travel_details.py` | 套餐向量检索、价格区间、优惠、目的地风俗等与 **Neo4j + Chroma travel_deals** 相关的工具。 |
| `rag_kb.py` | **`rag_kb`** 集合上的 RAG 检索工具（攻略、通用表格转文本等）。 |
| `trip_agents_tools.py` | 行程预算骨架等规划辅助工具。 |
| `NoTool.py` | 占位/无操作工具，用于在部分分支中满足 LangChain 工具接口。 |

### `backend/app/rag/`（知识入库）

| 模块 | 功能 |
|------|------|
| `ingest_upload.py` | 解析 `.txt` / `.csv` / `.xlsx`：写入 `rag_kb`、或在表结构符合时写入 **Neo4j + travel_deals**。 |
| `chroma_rag_kb.py` | 通用知识块写入与检索 **`rag_kb`** 集合。 |
| `models.py` | `TravelListing` 数据类：与 Neo4j 节点、Chroma 文档字段对齐。 |
| `persist_chroma.py` | 将套餐列表写入 Chroma **`travel_deals`**。 |
| `persist_neo4j.py` | 将套餐列表 Upsert 到 Neo4j 图谱（与 `get_travel_details` 中 Cypher 一致）。 |

### `backend/app/models/`（ORM）

| 模块 | 功能 |
|------|------|
| `user.py` | 用户表：用户名、密码哈希、`is_admin` 等。 |
| `chat_message.py` | 聊天消息表：用户、角色、内容、会话 id、时间戳等。 |

### `backend/app/schemas/`（Pydantic）

| 模块 | 功能 |
|------|------|
| `auth.py` | 注册/登录请求体、`TokenResponse` 等。 |
| `chat.py` | WebSocket 侧使用的 `AgentType` 等枚举与消息结构。 |
| `history.py` | 历史记录列表项等响应模型。 |

### `backend/app/data/`（静态数据）

| 资源 | 功能 |
|------|------|
| `city_code.csv` / `ctrip_domestic_cities.json` | 城市与站点编码等辅助数据。 |
| `中国各地风俗.csv` | 目的地风俗文案数据源（供风俗相关工具读取）。 |
| `dest_city_hints.csv` | RAG 套餐入库时无「目的地」列则从详情文案推断城市的关键词表（列名可为 `city` 等，见 `ingest_upload.py`）。 |

### `frontend/`（静态前端）

| 路径 | 功能 |
|------|------|
| `index.html` + `main.js` | 主聊天界面：WebSocket 连接、流式渲染、会话与 `agent` 选择等。 |
| `login.html` / `register.html` + `auth.js` | 普通用户登录、注册，写入 Token 与 API 基地址。 |
| `admin-login.html` + `admin-login.js` | 管理员登录，用于调用 RAG 上传等需 `is_admin` 的接口。 |
| `rag.html` | 管理员上传知识文件、查看入库说明与结果提示。 |
| `common.js` | 多页共用的 API 基址、`localStorage`、fetch 封装等。 |
| `style.css` | 全局样式。 |
| `favicon.ico` / `assets/logo-c.png` | 站点图标与品牌图。 |
| `vendor/marked.min.js`、`vendor/purify.min.js` | Markdown 渲染与安全过滤（以页面实际引用为准）。 |

---

## 快速开始（Windows）

1. 复制 **`backend/.env.example`** 为 **`backend/.env`**，至少填写 **`DASHSCOPE_API_KEY`**、**`PG_DSN`**；按需配置 Neo4j、和风、高德、Ollama 等（见下文变量表）。  
2. 在仓库根目录双击 **`start-assistant.bat`**（或手动执行下方「手动启动」命令）。  
3. 浏览器访问 **`http://127.0.0.1:5500`**。页面中 API 基地址建议为 **`http://127.0.0.1:8000`**，WebSocket 为 **`ws://127.0.0.1:8000/ws/chat`**。  
4. 停止：双击 **`stop-assistant.bat`**（按端口结束监听进程）。

### 手动启动（任意系统）

在项目**根目录**（与 `backend` 同级）启动后端：

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

前端（必须在 **`frontend`** 目录内，否则静态资源路径会 404）：

```bash
cd frontend
python -m http.server 5500
```

---

## 环境依赖

| 依赖 | 用途 |
|------|------|
| Python 3.10+ | 后端与简易静态服务 |
| **DashScope API Key**（`DASHSCOPE_API_KEY`） | 通义对话，供各智能体 |
| PostgreSQL | 用户与聊天消息（`PG_DSN`） |
| Neo4j | 旅行套餐图谱（规划工具检索） |
| Ollama + `nomic-embed-text` | Chroma 向量写入与检索（`travel_deals` 与 `rag_kb` 共用嵌入） |
| 和风天气 / 高德 | 按 `.env` 启用（`QWEATHER_*`、`AMAP_API_KEY`） |

### `.env` 常用变量（完整示例见 `backend/.env.example`）

| 变量 | 说明 |
|------|------|
| `DASHSCOPE_API_KEY` | 阿里云百炼 / DashScope，**智能体必需** |
| `PG_DSN` | PostgreSQL 连接串（SQLAlchemy + psycopg2） |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | 套餐图谱（未配则相关工具可能无数据） |
| `QWEATHER_HOST` / `QWEATHER_API_KEY` | 和风天气 |
| `AMAP_API_KEY` | 高德 Web 服务（地理编码、路线、逆地理等） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 设置密码后启动会创建管理员并开放 RAG 上传等 |
| `JWT_SECRET_KEY` / `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT 与有效期 |

`Settings` 从 **`backend/.env`** 读取（路径相对于 `backend/app/config.py`）。

---

## 大模型与智能体

- **实现位置**：`backend/app/agents/`（`agent_for_planner.py`、`agent_for_weather.py`、`agent_for_map.py`）。  
- **模型封装**：`backend/app/agents/tongyi_llm.py` 使用 `ChatTongyi`，默认型号为 `qwen3-32b`；对 Qwen3 等须在非流式场景下 **`enable_thinking=False`**（已在封装中处理），否则 DashScope 可能返回 `InvalidParameter`。更换型号可改 `DEFAULT_QWEN_MODEL`。  
- **路由**：`AssistantService` 在 `agent=auto` 时按关键词分流天气 / 地图，其余走规划智能体。  
- **工具调用**：各智能体通过 LangChain `create_agent` 绑定工具列表，**不再挂载**「在未出现工具结果前禁止直接作答」的 Agent 中间件；是否调用工具、调用顺序由**系统提示**与模型自行决定。若出现未查工具就回答的情况，可在各智能体的 `system_prompt` 中加强约束，或在前端引导用户换种问法。

### `agent` 取值

| `agent` | 说明 |
|---------|------|
| `weather` | 和风天气预报 |
| `map` | 高德地理编码、驾车路线、周边 POI 等 |
| `planner` | 行程规划：Neo4j + `travel_deals` 向量、RAG（`rag_kb`）、风俗、预算骨架、天气/地图工具等 |
| `auto` | 按问句路由（天气 / 地图关键词 → 对应智能体，否则规划） |

---

## HTTP / WebSocket 摘要

- 健康检查：`GET http://127.0.0.1:8000/health`  
- OpenAPI：`http://127.0.0.1:8000/docs`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register`、`/auth/login` | 注册 / 登录（JWT） |
| GET | `/history` | 历史（需 Bearer） |
| GET | `/location/reverse` | 逆地理（需高德 Key） |
| POST | `/admin/rag/upload` | 管理员上传 RAG（需管理员 Token） |
| WS | `/ws/chat` | 对话（先 `type: auth` 再发业务 JSON） |

WebSocket 业务字段示例：`query`、`agent`（`auto` \| `weather` \| `map` \| `planner`）、`conversation_id` 等，详见 **`backend/app/api/ws.py`**。

---

## 管理员与 RAG / 套餐入库

`.env` 中设置 `ADMIN_PASSWORD` 后，启动时会确保 `ADMIN_USERNAME`（默认 `admin`）存在且 `is_admin=true`。

`POST /admin/rag/upload` 上传 **`.csv` / `.xlsx`** 时：

- 若表头可映射为 **详情/行程、出发地、价格**（**列顺序不限**），则写入 **Neo4j** 与 Chroma 集合 **`travel_deals`**；**「优惠」等列可选**（无优惠列则按「无优惠」）。  
- 否则整表按行文本分块写入 Chroma **`rag_kb`**，**不**写入 Neo4j / `travel_deals`。  
- **`.txt`** 仅写入 `rag_kb`。

**两个向量库**：规划智能体里 **`vector_store_retriever`** 查 **`travel_deals`**（套餐）；**`rag_kb_retriever`** 查 **`rag_kb`**（攻略、价目表、未识别为套餐的表格等）。

**检索条数**：`rag_kb_retriever` 默认 `top_k=16`，上限 40；路书较长时可适当增大 `top_k`。

Excel 首列 `Unnamed: 0` 或首行为大标题时，后端会尝试剥前导空列或对 `.xlsx` 尝试 `header=1`。详见 **`backend/app/rag/ingest_upload.py`**。前端说明见 **`frontend/rag.html`**。
