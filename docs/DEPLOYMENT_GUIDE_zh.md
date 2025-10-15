# astronAgent 项目完整部署指南

本指南将帮助您按照正确的顺序启动 astronAgent 项目的所有组件，包括身份认证、知识库和核心服务。

## 📋 项目架构概述

astronAgent 项目包含以下三个主要组件：

1. **Casdoor** - 身份认证和单点登录服务(必要部署组件,提供单点登录功能)
2. **RagFlow** - 知识库和文档检索服务(非必要部署组件,根据需要部署)
3. **astronAgent** - 核心业务服务集群(必要部署组件)

## 🚀 部署步骤

### 前置要求

**Agent系统配置要求**
- CPU >= 2 Core
- RAM >= 4 GiB
- Disk >= 50 GB

**RAGFlow配置要求**
- CPU >= 4 Core
- RAM >= 16 GB
- Disk >= 50 GB

### 第一步：启动 Casdoor 身份认证服务

Casdoor 是一个开源的身份和访问管理平台，提供OAuth 2.0、OIDC、SAML等多种认证协议支持。

启动 Casdoor 服务请运行我们的 [docker-compose.yaml](/docker/casdoor/docker-compose.yaml) 文件。在运行安装命令之前，请确保您的机器上安装了 Docker 和 Docker Compose。

```bash
# 进入 Casdoor 目录
cd docker/casdoor

# 修改环境变量配置
vim conf/app.conf

# 创建日志挂载目录
mkdir -p logs

# 设置日志目录权限
chmod -R 777 logs

# 启动 Casdoor 服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

**服务信息：**
- 访问地址：http://localhost:8000
- 容器名称：casdoor
- 默认配置：生产模式 (GIN_MODE=release)

**配置目录：**
- 配置文件：`./conf` 目录
- 日志文件：`./logs` 目录

### 第二步：启动 RagFlow 知识库服务（根据需要部署）

RagFlow 是一个开源的RAG（检索增强生成）引擎，使用深度文档理解技术提供准确的问答服务。

启动 RagFlow 服务请运行我们的 [docker-compose.yml](/docker/ragflow/docker-compose.yml) 文件或 [docker-compose-macos.yml](/docker/ragflow/docker-compose-macos.yml) 。在运行安装命令之前，请确保您的机器上安装了 Docker 和 Docker Compose。

```bash
# 进入 RagFlow 目录
cd docker/ragflow

# 启动 RagFlow 服务（包含所有依赖）
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看服务日志
docker-compose logs -f ragflow
```

**访问地址：**
- RagFlow Web界面：http://localhost/

**重要配置说明：**
- 默认使用 Elasticsearch，如需使用 opensearch、infinity，请修改 .env 中的 DOC_ENGINE 配置
- 支持GPU加速，使用 `docker-compose-gpu.yml` 启动

### 第三步：集成配置 Casdoor、RagFlow 服务（根据需要配置相关信息）

在启动 astronAgent 服务之前，配置相关的连接信息以集成 Casdoor 和 RagFlow。

```bash
# 进入 astronAgent 目录
cd docker/astronAgent

# 复制环境变量配置
cp .env.example .env
```

#### 3.1 配置知识库服务连接

编辑 docker/astronAgent/.env 文件，配置 RagFlow 连接信息：

**关键配置项：**

```env
# RAGFlow配置
RAGFLOW_BASE_URL=http://localhost/
RAGFLOW_API_TOKEN=ragflow-your-api-token-here
RAGFLOW_TIMEOUT=60
RAGFLOW_DEFAULT_GROUP=星辰知识库
```

**获取 RagFlow API Token：**
1. 访问 RagFlow Web界面：http://localhost/
2. 登录并进入用户设置
3. 生成 API Token
4. 将 Token 更新到配置文件中

#### 3.2 配置 Casdoor 认证集成

编辑 docker/astronAgent/.env 文件，配置 Casdoor 连接信息：

**关键配置项：**

```env
# Casdoor配置
CONSOLE_CASDOOR_URL=http://your-casdoor-server:8000
CONSOLE_CASDOOR_ID=your-casdoor-client-id
CONSOLE_CASDOOR_APP=your-casdoor-app-name
CONSOLE_CASDOOR_ORG=your-casdoor-org-name
```

**获取 Casdoor 配置信息：**
1. 访问 Casdoor Web界面：http://localhost:8000
2. 默认账号: admin/123 登陆进入管理页面
3. 进入 http://localhost:8000/organizations 页创建组织
4. 进入http://localhost:8000/applications页 创建应用，并绑定组织
5. 设置应用的重定向URL为：http://localhost:10080/callback (项目nginx容器端口,默认10080)
6. 将Casdoor地址，应用的客户端ID，应用名称，组织名称等信息更新到配置文件中

### 第四步：启动 astronAgent 核心服务（必要部署步骤）

#### 4.1 配置 讯飞开放平台 相关APP_ID API_KEY等信息

获取文档详见：https://www.xfyun.cn/doc/platform/quickguide.html

创建应用完成后可能需要购买或领取相应能力的API授权服务量
- 星火大模型API: https://xinghuo.xfyun.cn/sparkapi
  (对于大模型API会有额外的SPARK_API_PASSWORD需要在页面上获取)
- 语音转写API: https://www.xfyun.cn/services/lfasr
- 图片生成API: https://www.xfyun.cn/services/wtop

最后编辑 docker/astronAgent/.env 文件，更新相关环境变量：
```env
PLATFORM_APP_ID=your-app-id
PLATFORM_API_KEY=your-api-key
PLATFORM_API_SECRET=your-api-secret

SPARK_API_PASSWORD=your-api-password
```

#### 4.2 如果您想使用星火RAG云服务，请按照如下配置

星火RAG云服务提供两种使用方式：

##### 方式一：在页面中获取

1. 使用讯飞开放平台创建的 APP_ID 和 API_SECRET
2. 直接在页面中获取星火数据集ID，详见：[xinghuo_rag_tool.html](/docs/xinghuo_rag_tool.html)

##### 方式二：使用 cURL 命令行方式

如果您更喜欢使用命令行工具，可以通过以下 cURL 命令创建数据集：

```bash
# 创建星火RAG数据集
curl -X PUT 'https://chatdoc.xfyun.cn/openapi/v1/dataset/create' \
    -H "Accept: application/json" \
    -H "appId: your_app_id" \
    -H "timestamp: $(date +%s)" \
    -H "signature: $(echo -n "$(echo -n "your_app_id$(date +%s)" | md5sum | awk '{print $1}')" | openssl dgst -sha1 -hmac 'your_api_secret' -binary | base64)" \
    -F "name=我的数据集"
```

**注意事项：**
- 请将 `your_app_id` 替换为您的实际 APP ID
- 请将 `your_api_secret` 替换为您的实际 API Secret

获取到数据集ID后，请将数据集ID更新到 docker/astronAgent/.env 文件中：
```env
XINGHUO_DATASET_ID=
```

#### 4.3 启动 astronAgent 服务

启动 astronAgent 服务请运行我们的 [docker-compose.yaml](/docker/astronAgent/docker-compose.yaml) 文件。在运行安装命令之前，请确保您的机器上安装了 Docker 和 Docker Compose。

```bash
# 进入 astronAgent 目录
cd docker/astronAgent

# 根据需要修改配置
vim .env

# 启动所有服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看服务日志
docker-compose logs -f
```

## 📊 服务访问地址

启动完成后，您可以通过以下地址访问各项服务：

### 认证服务
- **Casdoor 管理界面**：http://localhost:8000

### 知识库服务
- **RagFlow Web界面**：http://localhost/

### AstronAgent 核心服务
- **控制台前端(nginx代理)**：http://localhost:10080

## 📚 更多资源

- [AstronAgent 官方文档](https://docs.astronAgent.cn)
- [Casdoor 官方文档](https://casdoor.org/docs/overview)
- [RagFlow 官方文档](https://ragflow.io/docs)
- [Docker Compose 官方文档](https://docs.docker.com/compose/)

## 🤝 技术支持

如遇到问题，请：

1. 查看相关服务的日志文件
2. 检查官方文档和故障排除指南
3. 在项目 GitHub 仓库提交 Issue
4. 联系技术支持团队

---

**注意**：首次部署建议在测试环境中验证所有功能后再部署到生产环境。
