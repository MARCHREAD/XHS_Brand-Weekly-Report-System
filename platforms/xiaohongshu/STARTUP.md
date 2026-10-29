# XHS Collector 启动文档

## 最简单的启动方式

在项目目录中双击 `start.cmd`。

脚本会打开浏览器并启动服务。命令窗口需要保持打开；关闭窗口或按 `Ctrl+C` 会停止服务。

启动后访问：

- 工作台：http://127.0.0.1:8000/
- Swagger 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

## PowerShell 启动

打开 PowerShell，执行：

```powershell
cd C:\path\to\Crawler-Lab
.\start.ps1 -OpenBrowser
```

如果 PowerShell 阻止脚本运行，可以只为本次启动放行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -OpenBrowser
```

不自动打开浏览器：

```powershell
.\start.ps1
```

改用其他端口：

```powershell
.\start.ps1 -Port 8001 -OpenBrowser
```

## 首次安装或重新安装依赖

`start.ps1` 检测不到 `.venv` 时，会自动创建虚拟环境并安装依赖。已有虚拟环境时，如需主动更新依赖，执行：

```powershell
.\start.ps1 -Install
```

要求 Windows 已安装 Python 3，并且 `py` 或 `python` 命令可用。

项目已内置纯 Python 请求签名实现，安装依赖时不再下载 `xhshow`。底层 ARC4/AES 算法由 `pycryptodome` 提供。

## 登录和会话

当前登录信息保存在 `secrets\xhs_cookie.txt`，普通重启不需要重新扫码。页面顶部显示“会话有效”即可使用。

蒲公英后台使用独立登录态。点击工作台顶部“蒲公英”，填写蒲公英邮箱账号和密码即可登录；后端以纯 Python HTTP 完成 CAS 换票并把 Cookie 保存到 `secrets\pgy_cookie.txt`，普通重启无需重新登录。也可以设置 `XHS_PGY_COOKIE` 或 `XHS_PGY_COOKIE_FILE` 导入已有会话。`/health` 中 `pgy_session.state=valid` 表示蒲公英会话已经过服务端验证。

如果显示 Cookie 未配置、会话失效或有效 Worker 为 0：

1. 点击页面顶部的会话状态。
2. 生成登录二维码并使用小红书 App 扫码确认。
3. 页面出现短信验证码输入框时，填写账号绑定手机收到的 6 位验证码；后端会在原 Python Session 中完成验证。
4. 页面出现二次验证二维码时，使用同一账号再次扫码确认。
5. 等待页面显示“会话有效”和 `Worker 1/10`。

平台可能连续要求多种验证。当前纯 Python 链已接入短信验证类型 `120`，以及二维码验证类型 `124`、`209`。其他验证类型会显示编号并提供官方验证入口。

不要把 `secrets` 目录中的文件发给其他人。其他调用方只需要 API 地址，不需要登录 Cookie。

## 验证服务是否正常

新开一个 PowerShell 窗口执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

正常结果应满足：

```text
data.status = ok
data.session.state = valid
data.effective_workers >= 1
```

也可以测试首页数据：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/v1/xhs/homefeed?num=5"
```

## 停止服务

回到运行 `start.ps1` 或 `start.cmd` 的窗口，按 `Ctrl+C`。也可以双击 `stop.cmd`，或在另一个 PowerShell 窗口执行：

```powershell
.\stop.ps1
```

停止脚本只会关闭命令行属于本项目 `main.py` 的监听进程。如果 8000 端口属于其他程序，脚本会保留该程序并报告错误。确认停止后，健康检查地址应不再响应。

## 常见问题

### 端口 8000 被占用

启动脚本会显示占用端口的进程号。可以关闭旧服务，或改用其他端口：

```powershell
.\start.ps1 -Port 8001
```

### 会话变成 expired

平台已撤销登录状态，需要在工作台重新扫码。后台会定期检查会话，但不能延长已经被平台撤销的登录。

### 提示找不到依赖

执行：

```powershell
.\start.ps1 -Install
```

### 让局域网或公网用户访问

默认只监听本机 `127.0.0.1`。这适合自己使用，也能避免登录管理入口暴露。对外提供接口时，应使用 HTTPS 反向代理或 Tunnel，并在业务接口前增加 API Key 和限流；扫码登录管理接口应继续仅限本机。
