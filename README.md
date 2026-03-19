# 医院一键部署工具

基于 `PySide2 + paramiko` 的 Windows 桌面部署工具，适合在医院远程桌面的 Windows 机器上运行。

## 功能

- 支持部署单文件或目录内容
- 支持自定义 Linux 主机、端口、账号、密码、目标路径
- 文件模式下只备份目标文件再覆盖
- 目录模式下整包备份目标目录，再清空并上传目录内容
- 支持后置命令，例如 `systemctl restart his-drg.service`
- 支持备份列表查看、恢复、滚动删除旧备份
- 支持执行历史和本地日志导出

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 启动

```powershell
python -m hospital_deploy_tool
```

## 打包 exe

打包环境建议使用 Python 3.10（PySide2 兼容性）。

生成单文件 exe：

```powershell
py -3.10 -m venv .venv310
.\.venv310\Scripts\python.exe -m pip install -r requirements.txt
.\.venv310\Scripts\python.exe -m pip install pyinstaller
.\build_exe.bat
```

打包产物：

```text
dist\HospitalDeployTool.exe
```

## 使用说明

1. 在主界面新建或选择一个 Profile。
2. 选择源类型：
   - `文件`：例如 `\\tsclient\E\deploy-test\drg-service.jar`
   - `目录`：例如 `E:\temp`
3. 填写 Linux 主机信息和目标路径。
4. 配置最大备份数、备份根目录、后置命令。
5. 先点击 `测试连接`。
6. 再点击 `开始部署`。

## 源路径注意事项

- 工具只支持“当前运行会话可直接访问”的源路径。
- 在医院远程桌面里，通常可用的是：
  - 医院远程机本地磁盘路径
  - `\\tsclient\盘符\...`
- `\\wsl.localhost\Ubuntu\...` 通常不能在医院远程桌面会话里直接访问。
- 如果 jar 在您本机 WSL 中，建议先复制到您本机普通 Windows 目录，再通过 `\\tsclient\...` 给远程桌面读取。

## 备份规则

- 文件模式：
  - 目标路径可填写“目录”或“完整文件路径”
  - 填目录时，按源文件原名上传到该目录
  - 如目标目录下已有同名文件，只备份该文件并覆盖
- 目录模式：
  - 备份目标目录为 `.tar.gz`
  - 清空目标目录内容
  - 上传源目录内容

## 日志与配置位置

- 配置文件：`%LOCALAPPDATA%\Hospital Deploy Tool\config.json`
- 运行日志：`%LOCALAPPDATA%\Hospital Deploy Tool\logs\`
