# 小C助手

旅行场景的智能对话：**FastAPI** 后端 + 静态前端；多智能体（天气 / 地图 / 行程规划）、WebSocket 流式回复、会话与历史；模型采用 **qwen3-32b**。

## 项目目录结构

```bash
小C助手/                           # 高性价比旅游出行智能助手
├── backend/                      # FastAPI 后端核心（推荐使用 PyCharm/VSCode 打开此目录）
│   ├── .env                      # 环境配置（API Key、数据库连接、模型配置等）
│   ├── requirements.txt          # Python 依赖列表
│   ├── chroma_db/                # Chroma 向量数据库持久化目录（自动生成）
│   └── app/
│       ├── main.py               # 应用入口：FastAPI实例、CORS、中间件、启动时初始化
│       ├── config.py             # Pydantic Settings 配置管理
│       ├── db.py                 # SQLAlchemy 数据库连接、Session管理
│       ├── api/                  # RESTful + WebSocket 路由层
│       ├── agents/               # 三大核心智能体实现
│       ├── services/             # 业务逻辑层（重点体现高性价比）
│       ├── tools/                # LangChain工具集（20+个）
│       ├── rag/                  # RAG知识库模块（高性价比知识增强）
│       ├── models/               # SQLAlchemy ORM模型
│       ├── schemas/              # Pydantic数据校验模型
│       └── data/                 # 静态数据文件
├── frontend/                     # 纯静态前端（无需构建，直接运行）
│   ├── index.html                # 主聊天界面
│   ├── main.js                   # WebSocket流式交互核心逻辑
│   ├── auth.js                   # 登录注册认证逻辑
│   ├── common.js                 # 公共工具函数
│   ├── style.css                 # 现代聊天界面样式（支持深色模式）
│   ├── login.html / register.html
│   ├── admin-login.html          # 管理员登录
│   ├── admin-login.js
│   ├── rag.html                  # RAG知识上传管理后台
│   ├── vendor/                   # 第三方库（marked.js、DOMPurify）
│   └── assets/                   # 图片、图标等静态资源
├── .gitignore
├── README.md                   
```


## 快速开始

1. 配置 `backend/.env`，至少配置 **阿里云百炼平台获取`DASHSCOPE_API_KEY`**、**PG数据库`PG_DSN`**。
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

## 其他说明

- 接口文档：`http://127.0.0.1:8000/docs`
- 规划、套餐、RAG 等依赖 Neo4j、Chroma、Ollama 等时，按 `.env` 配置即可。
