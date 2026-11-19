# ScholarFlow Windows 版本升级

## 已经安装的电脑怎样升级？

1. 保留原来的部署文件夹，启动 Docker Desktop。
2. 将 `scholarflow-upgrade-windows-amd64-*.zip` 解压到一个临时文件夹。
3. 双击其中的 **`upgrade.bat`**。
4. 在选择窗口中选中**原来的部署文件夹**，也就是同时包含 `compose.yaml`、`.env`、`data/` 和 `embedding/` 的那个文件夹。
5. 等待出现 `[OK] Upgraded`，再刷新原来的软件页面。

升级包包含 `start.bat` 和 `stop.bat`，升级成功后会自动复制到原部署目录。以后在原目录双击它们即可启动或停止服务；升级前已有的同名脚本会一并备份。

也可以在 PowerShell 中指定原目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\upgrade.ps1 -InstallDirectory "D:\ScholarFlow\scholarflow-offline"
```

升级时应用会短暂停止。镜像导入完成后，脚本先备份，再替换应用容器。备份较多 PDF 时需要等待一段时间。

## 什么会更新，什么会保留？

| 内容 | 处理方式 |
|---|---|
| 应用程序 | 切换为升级包中的版本专属镜像标签 |
| API Key 等配置 | 保留原 `.env`，仅更新 `SCHOLARFLOW_IMAGE` |
| 论文信息与处理状态 | 继续使用原 PostgreSQL 数据库卷 |
| PDF、文本、索引、会话 | 继续挂载原 `data/` 目录 |
| BGE-M3 模型 | 继续使用原 `embedding/`，不重新下载 |
| 原 Compose 配置、端口与数据库服务 | 保留，不使用新目录重新创建服务 |

升级包不包含新的数据库镜像、空白业务数据或模型，不需要重新安装整个软件。

## 升级前会备份什么？

备份自动保存在原目录的 `backups/upgrade-时间-编号/`：

```text
.env                   原有配置
compose*.yaml/yml      原有服务配置
postgres.dump          PostgreSQL 数据库备份
data/                  原有 PDF、文本、索引和会话文件
upgrade-record.json    版本、旧镜像标签和备份完成状态
control-scripts/       升级前已有的 start.bat、stop.bat
```

旧应用镜像会保留为 `scholarflow:rollback-...`。升级成功后也会保留备份，可在确认运行正常后由维护人员按需整理。

## 升级失败怎么办？

- 在替换应用之前备份失败：不会切换到新版本；脚本会尝试重新启动旧应用。
- 新应用启动失败或健康检查不通过：脚本恢复原 `.env`，尝试用保留的旧镜像重新启动应用，并保留备份位置。
- 保存报错文字和 `upgrade-record.json`，联系维护人员处理。

**恢复旧应用不等于恢复数据库。** 如果新版本已经修改数据库结构，或需要回退升级期间写入的文件，应由维护人员根据 `postgres.dump` 与 `data/` 备份一起恢复。数据库结构变更需要随版本提供兼容的迁移流程；此通用脚本不自动执行删除字段、清库或数据库降级。

## 开发者怎样生成升级包？

先准备好需要发布的本地应用镜像，再运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package_upgrade.ps1 -Image scholarflow:local -Version 1.1.0
```

产物在 `dist/`，同时生成 `.zip.sha256`。该命令只导出已有镜像并打包，不自动构建、运行 CI 或做全流程测试。**修改源码后，必须先把新代码构建进本地镜像，打包命令不会自动把工作区代码注入已有镜像。**

首次安装继续使用 `scripts/package_deployment.ps1` 生成的完整安装包。应用升级保持原 Compose 服务布局；数据库服务、挂载方式或模型本身发生不兼容变化时，应另行提供迁移说明。
