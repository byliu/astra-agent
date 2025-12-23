# 运行与运维 FAQ

## 如何检查服务健康？
在 `docker/astronAgent` 下执行 `docker compose ps` 查看状态，`docker compose logs <service>` 查看日志。HTTP 入口：前端 `http://localhost/`，Casdoor 管理端 `http://localhost:8000`。

## 如何备份数据？
数据应放在 volume 或外部数据库。升级前按基础设施方式对 volume/数据库做快照或备份。

