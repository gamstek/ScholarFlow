# ScholarFlow 离线部署包

默认生成适用于 **Windows 10/11 x64 + Docker Desktop** 的 ZIP 包，包含 ScholarFlow 应用镜像、PostgreSQL 16 镜像、完整 BGE-M3 模型、Compose 配置以及双击部署脚本。Docker Desktop 使用 WSL2 后端和 Linux 容器模式，与本项目当前 Windows 开发机的运行方式一致。启动时无需访问镜像仓库或下载模型，云端 LLM、文献检索等功能仍需访问相应的外部 API。

## Windows 目标机器部署

1. 安装并启动 Docker Desktop，启用 WSL2 后端，使用 Linux 容器模式。
2. 将 `scholarflow-offline-windows-amd64-*.zip` 和对应的 `.sha256` 传至目标电脑，通过资源管理器解压，进入 `scholarflow-offline` 文件夹。
3. 将 `.env.example` 复制为 `.env`，填写 `LLM_BACKEND`、`CLOUD_API_KEY`、`CLOUD_API_BASE` 和 `CLOUD_MODEL`。镜像标签已预设为包内的 `scholarflow:local`。
4. 双击 **`deploy.bat`**。它会导入镜像、使用本地模型启动服务、检查健康状态并打开浏览器。

也可在解压目录使用 PowerShell 执行：

```powershell
Copy-Item .env.example .env  # 首次部署时执行，然后编辑 .env
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
```

访问 `http://localhost:8000`。首次导入镜像需要一些时间。`model-init` 显示 `Exited (0)` 表示模型验证成功，属于正常状态。

可使用 PowerShell 检查 ZIP 的 SHA256，并与随包 `.sha256` 中的值对照：

```powershell
Get-FileHash .\scholarflow-offline-windows-amd64-YYYYMMDD-HHMMSS.zip -Algorithm SHA256
```

## 在当前开发机器重新打包

在项目根目录的 PowerShell 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package_deployment.ps1
```

默认生成 Windows ZIP 包，打包 `scholarflow:local` 和本机已准备的模型，产物位于 `dist/`，同时生成 SHA256 校验文件。可通过 `-Image` 和 `-OutputDirectory` 指定镜像与输出目录。需要 Linux `.tar.gz` 版本时增加 `-Target Linux`。

## Linux 版本的传输与部署

以下命令用于通过 `-Target Linux` 生成的 Linux x86_64 / amd64 包，目标机器需安装 Docker Engine 与 Docker Compose v2。

将 `.tar.gz` 和对应 `.sha256` 一起传输，例如：

```bash
scp scholarflow-offline-linux-amd64-*.tar.gz* user@server:/opt/
ssh user@server
cd /opt
```

也可以通过 SFTP、移动硬盘或内网文件共享传输。

### 校验、解压并启动

以下文件名替换为实际下载的部署包文件名：

```bash
sha256sum -c scholarflow-offline-linux-amd64-YYYYMMDD-HHMMSS.tar.gz.sha256
tar -xzf scholarflow-offline-linux-amd64-YYYYMMDD-HHMMSS.tar.gz
cd scholarflow-offline
cp .env.example .env
```

编辑 `.env`，配置 `LLM_BACKEND`、`CLOUD_API_KEY`、`CLOUD_API_BASE` 和 `CLOUD_MODEL`。模板已设置应用镜像为包内的本地标签。随后执行：

```bash
bash deploy.sh
```

脚本通过 `docker load` 导入镜像，以 `--pull never` 启动 Compose，自动验证并复用包内 BGE-M3 模型。`model-init` 服务成功退出为 `Exited (0)` 是正常状态。

本包部署的是新的独立实例，配置模板需要重新填写；本地业务数据库、会话和 API 密钥不在包内。文献等新数据写入解压目录的 `data/`，数据库保存在 Docker 持久化卷中。

## 远程访问

服务默认只监听目标机器的 `127.0.0.1:8000`。在自己的电脑建立 SSH 隧道：

```bash
ssh -N -L 8000:127.0.0.1:8000 user@server
```

保持该 SSH 连接，浏览器访问 `http://localhost:8000`。如果本机 8000 已被占用，可改成 `-L 18000:127.0.0.1:8000`，然后访问 `http://localhost:18000`。

## 日常管理

```bash
docker compose ps -a
docker compose logs -f app
docker compose down
docker compose up -d --pull never
```

以后仅需重启时不用再次导入 `images.tar`。普通的 `docker compose down` 会保留数据。
