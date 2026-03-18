---
name: deploy-helper
description: |
  项目部署助手。帮助在 Docker 或虚拟环境中安全部署 Python/Node.js 项目。
  
  **当以下情况时使用此 Skill**：
  (1) 需要部署一个 GitHub 项目到服务器
  (2) 需要用 Docker 隔离测试后再部署
  (3) 部署过程中遇到依赖问题（torch/CUDA、编译失败等）
  (4) 用户提到"部署"、"安装"、"docker"、"运行项目"
---

# Deploy Helper

安全部署项目的标准流程。核心原则：**先测试，再部署**。

## 部署流程

```
1. 分析项目 → 2. Docker 测试 → 3. 修复问题 → 4. 验证功能 → 5. 部署生产
```

## Step 1: 分析项目

读取项目的以下文件，了解技术栈和依赖：
- `README.md` / `README_CN.md`
- `pyproject.toml` / `requirements.txt` / `package.json`
- `Dockerfile` / `docker-compose.yml`（如果有）
- 配置文件（`config.yaml` 等）

**输出**：技术栈、依赖列表、已知坑点。

## Step 2: Docker 测试环境

优先使用 Docker 隔离测试，避免污染主机环境。

### Python 项目

```bash
docker run -it --rm -v $(pwd):/app -w /app python:3.12-slim bash
# 在容器内安装和测试
```

### Node.js 项目

```bash
docker run -it --rm -v $(pwd):/app -w /app node:20-slim bash
```

### 全栈项目（前后端分离）

写一个临时 docker-compose.yml 来测试。

## Step 3: 常见坑点速查

### Python 依赖

| 问题 | 解决方案 |
|------|----------|
| torch 拉取 CUDA 包（4GB+） | 用 `--index-url https://download.pytorch.org/whl/cpu` 安装 CPU 版本 |
| hdbscan 编译失败 | 先装 `setuptools cython<3 numpy`，再装 hdbscan |
| sentence-transformers 首次下载模型 hang | 提前下载模型或设置超时 |
| uv sync 缺 setuptools | `uv pip install setuptools` 后重试 |

### Node.js 依赖

| 问题 | 解决方案 |
|------|----------|
| node_modules 没装到位 | 删除 node_modules 重新 `pnpm install` |
| next 命令找不到 | 检查 `node_modules/.bin/` 是否存在 |
| 端口被占用 | 用 `lsof -i :PORT` 查找并 kill |

### 通用问题

| 问题 | 解决方案 |
|------|----------|
| 配置文件需要手动编辑 | 启动前检查并自动生成 |
| 首次启动下载大文件 | 提前下载或设置代理 |
| 权限问题 | Docker 内用 root，生产环境用专用用户 |

## Step 4: 验证功能

部署后必须验证核心功能：

```bash
# 健康检查
curl -s http://localhost:PORT/health

# API 测试（根据项目调整）
curl -s -X POST http://localhost:PORT/api/xxx -H "Content-Type: application/json" -d '{}'

# 前端检查
curl -s http://localhost:FRONTEND_PORT | head -20
```

## Step 5: 生产部署

测试通过后，从 Docker 测试环境迁移到生产环境：

1. 确认所有依赖版本锁定（lock 文件存在）
2. 配置文件中的敏感信息用环境变量
3. 用 systemd 或 supervisor 管理进程
4. 配置日志轮转

## 子 Agent 指令模板

派子 Agent 部署时，使用以下模板：

```
## 任务：部署 [项目名]

## ⚠️ 关键约束（必须遵守）
1. [最重要的约束，如"不要安装 CUDA 版 torch"]
2. [第二重要的约束]

## 不要做的事
- [禁止事项]

## 具体步骤
1. [步骤1，附带具体命令]
2. [步骤2]

## 完成标准
- curl health 端点返回 200
- 核心 API 测试通过
```
