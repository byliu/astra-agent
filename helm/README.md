# Astron Agent Helm 部署指南

## 快速部署

### 1. 克隆项目

```bash
# 克隆仓库
git clone https://github.com/iflytek/astron-agent.git
cd astron-agent/helm/astron-agent
```

### 2. 修改配置

编辑 `astron-agent/values.yaml`，修改关键配置：

```yaml
# 全局配置 - 主机访问地址
global:
  # 镜像版本
  astronAgentVersion: latest
  
  # 主机地址，用于 MinIO、Casdoor 等服务的外部访问
  # 例如: http://your-domain.com
  hostBaseAddress: "http://your-domain.com"
  
  # 配置 讯飞开放平台 相关 APP_ID API_KEY 等信息
  #获取文档详见：https://www.xfyun.cn/doc/platform/quickguide.html
  platformAppId: "your-app-id"
  platformApiKey: "your-api-key"
  platformApiSecret: "your-api-secret"
  # https://console.xfyun.cn/services/bm4
  sparkApiPassword: "your-api-password"
  # https://console.xfyun.cn/services/rta
  sparkRtasrApiKey: "your-rtasr-api-key"

# 修改ingress域名，与hostBaseAddress保持一致
ingress:
  enabled: true
  hosts:
    - host: your-domain.com
  tls:
      hosts:
        - your-domain.com
```

### 3. 部署

```bash
# 使用 Helm 安装
helm install astron-agent . -n astron-agent --create-namespace
```

### 4. 访问应用

- **生产环境**：配置域名解析后访问 `http://your-domain.com`

## 相关资源

- [Kubernetes 官方文档](https://kubernetes.io/docs/)
- [Helm 官方文档](https://helm.sh/docs/)
- [Astron Agent GitHub](https://github.com/iflytek/astron-agent)
