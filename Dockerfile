FROM python:3.12-alpine

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY main.py .
COPY core/ ./core/
COPY products/ ./products/

# 版本文件通过 volume 挂载
RUN mkdir -p /app/output

CMD ["python", "main.py"]
