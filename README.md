backend.app.# 小C助手

旅行场景的智能对话：**FastAPI** 后端 + 静态前端；多智能体（天气 / 地图 / 行程规划）、WebSocket 流式回复、会话与历史；模型采用 **qwen3-32b**。

## 目录

- `backend/`：后端与 `requirements.txt`、`.env`
- `frontend/`：静态页面，无构建步骤


```
小C助手/
├── backend/                      # FastAPI 后端工程根目录
│   ├── .env                      # 本地环境配置
│   ├── requirements.txt          # Python 依赖
│   ├── chroma_db/                # Chroma 持久化目录
│   └── app/
│       ├── __init__.py
│       ├── main.py               # FastAPI 应用：路由挂载、CORS、启动时建表与管理员引导
│       ├── config.py             # Pydantic Settings：从 backend/.env 读取配置
│       ├── db.py                 # SQLAlchemy Engine、Session、get_db
│       ├── security.py           # JWT 签发/解析、密码哈希与校验
│       ├── api/                  # HTTP / WebSocket 路由层
│       ├── agents/               # LangChain 多智能体与通义模型配置
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
├── README.md                     # 使用文档
└── .gitignore                    # 不提交到git上的目录或文件
```

## 快速开始

1. 配置 `backend/.env`，至少配置 **`DASHSCOPE_API_KEY`**、**`PG_DSN`**。
2. 安装依赖（在项目根目录执行）：

   ```bash
   pip install -r backend/requirements.txt
   ```

3. 开两个终端：一个启动后端，一个启动前端（默认端口 **8000** / **5500**）。

   ```bash
   python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
   ```

   ```bash
   cd frontend
   python -m http.server 5500
   ```

4. 浏览器打开 `http://127.0.0.1:5500`，API 基地址填 `http://127.0.0.1:8000`，WebSocket 为 `ws://127.0.0.1:8000/ws/chat`。

## 其他说明

- 接口文档：`http://127.0.0.1:8000/docs`
- 规划、套餐、RAG 等依赖 Neo4j、Chroma、Ollama 等时，按 `.env` 配置即可。
