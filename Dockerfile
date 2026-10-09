FROM python:3.14-rc-alpine

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 复制依赖配置
COPY pyproject.toml uv.lock ./

# 安装依赖；构建时预编译字节码，避免每次 run --rm 新容器都重新编译
ENV UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev

# 复制项目文件
COPY main.py .
COPY core/ ./core/
COPY products/ ./products/
RUN .venv/bin/python -m compileall -q main.py core products

# 版本文件通过 volume 挂载
RUN mkdir -p /app/output

CMD ["uv", "run", "python", "main.py"]
