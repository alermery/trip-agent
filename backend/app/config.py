from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库配置
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "12345678"
    PG_DSN: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/xiaoc_assistant"
    JWT_SECRET_KEY: str = "haowehrfofqwd"
    JWT_ALGORITHM: str = "HS256"
    # 个人助手场景：默认 30 天，避免短周期关机再开就因 JWT 过期导致 WS/接口 鉴权失败
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30
    APP_ENV: str = "development"

    # 管理员：用于独立管理员登录与 RAG 上传；在 .env 中设置密码后，启动时会确保该用户存在且 is_admin=true
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""

    # 接口配置：这些字段会自动从环境变量读取
    QWEATHER_HOST: str | None = None
    QWEATHER_API_KEY: str | None = None
    # 高德 Web 服务 Key：地理编码、驾车路径规划、逆地理等 REST 接口（服务端）
    AMAP_API_KEY: str | None = None

    model_config = {
        "env_file": str(Path(__file__).resolve().parents[1] / ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()