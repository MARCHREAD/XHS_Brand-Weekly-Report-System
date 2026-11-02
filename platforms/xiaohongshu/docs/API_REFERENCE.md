# XHS Collector API

当前版本：`0.7.1`

本项目提供类似 TikHub 调用方式的本地 HTTP API，用于读取小红书 Web 数据：

- 关键词笔记搜索
- 笔记详情、简介、平台标签和互动数
- 作者资料和作者笔记
- 主评论与内嵌子评论
- 主评论及完整二级评论分页
- 有界聚合采集与 JSONL 保存
- 可选 OpenAI Structured Outputs 摘要和主题补全
- 蒲公英笔记详情、博主完整数据、相似博主与笔记博主广场筛选

v0.6.0 将设备标识、`X-S`、`X-S-Common`、`X-Rap-Param` 和 XYW 签名实现内置到 `collector/_signer`，并将 120 短信验证改为纯 Python HTTP 协议。运行时不再依赖 `xhshow` 或浏览器页面。

最终请求路径、设备标识和签名均由项目内置的纯 Python 实现执行，不依赖 Playwright、Selenium、浏览器 Profile 或外部签名包。

蒲公英接口同样由纯 Python HTTP 和内置 `X-S` / `X-S-Common` 签名执行。普通小红书登录态与蒲公英后台登录态分开保存；蒲公英会话见下方“蒲公英接口”。蒲公英列表请求默认超时 20 秒并重试 1 次；可选的 `track` 请求采用 8 秒快速超时，失败后直接继续列表请求。批量抓取中重试仍失败的页会记录到 `failed_pages`，其余页面继续执行。可通过 `XHS_PGY_TIMEOUT_SECONDS`、`XHS_PGY_MAX_RETRIES` 和 `XHS_PGY_RETRY_BACKOFF_SECONDS` 调整。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

首次启动可以不提供 Cookie。打开数据工作台，点击顶部“Cookie 未配置 · 登录”，使用小红书 App 扫码并确认。后端会在同一个纯 Python Session 中完成二维码状态轮询，把包含 `a1`、`web_session` 和 `webId` 的会话原子写入 `secrets/xhs_cookie.txt`，并立即热切换采集 Worker；浏览器之后不需要保持登录。

如果扫码确认后平台要求二次扫码验证（HTTP 471、`verifytype=124` 或 `209`），工作台会自动换成一张新的验证二维码，并提示“需要再次扫码验证”。请使用刚才的同一 App 账号再次扫码并确认。后端通过官方二维码验证的初始化、状态查询接口等待确认，再用原 Python Session 重放登录状态请求。登录码和每轮验证二维码分别有约一分钟有效期；取消、过期或验证失败时不会安装新会话。其他验证类型会明确显示类型编号，不再误报为等待扫码。

`verifytype=120` 属于短信验证。后端在原 Python Session 中调用官方 `vc/init`、`vc/send`、`vc/check` 接口，工作台直接显示脱敏接收号码和 6 位验证码输入框；校验通过后继续原登录状态机，不再打开官方验证网页。登录尝试最多保留五分钟。

2026-09-14 已完成真实验收：二次扫码确认、`code_status=2`、SSK 解密、Cookie 落盘、会话 `valid`、有效 Worker 1；两次独立首页请求分别返回 5、7 条笔记，工作台完整关键词采集的 5 个步骤全部成功。脱敏证据见 `analysis/live_acceptance.json` 和 `analysis/proof_manifest.json`。

会话建立后由后台自动维护：默认每 15 分钟调用一次轻量身份接口验证服务端状态，复用每个 Cookie 对应的 HTTP Session，并把上游通过 `Set-Cookie` 轮换的新值原子写回本地。服务端明确返回未登录时，该 Cookie 会标记为 `expired` 并从下一代 Worker 池隔离；网络超时等不确定错误只标记为 `degraded`，原会话继续保留。检查周期可通过 `XHS_SESSION_CHECK_SECONDS` 调整，最低 60 秒。

也可以手动把网页 Cookie 放在 `secrets/xhs_cookie.txt` 第一行，或设置环境变量 `XHS_COOKIE`、通过 `XHS_COOKIE_FILE` 指定其他本地文件。环境变量的优先级高于本地文件。

二维码会话管理路由默认只接受来自 `localhost` / `127.0.0.1` 的请求。即使通过 Tunnel 公开数据 API，远程调用方也不能替换服务器上的采集账号。

多会话并发时，在 `secrets/xhs_cookies.txt` 中每行放一个独立 Cookie。每个 Cookie 会创建一个隔离 Worker，分别持有签名器、`SessionManager`、HTTP Session、限速器和请求锁。`XHS_WORKER_COUNT` 默认上限为 10；只有一个 Cookie 时有效 Worker 仍为 1，不会复制同一会话制造伪并发。

GPT 补全需要设置 `OPENAI_API_KEY`。默认模型是 `gpt-4o-mini`，可以用 `OPENAI_MODEL` 调整。实现采用 OpenAI Responses API 的 Pydantic Structured Outputs：

https://developers.openai.com/api/docs/guides/structured-outputs

## 启动

Windows 一键启动、首次安装、停止服务和故障排查见 [STARTUP.md](../STARTUP.md)。最简单的方式是在项目目录双击 `start.cmd`。

PyCharm 中直接运行项目根目录的 `main.py`，或执行：

```powershell
.\.venv\Scripts\python.exe .\main.py
```

默认地址：

- 数据工作台: http://127.0.0.1:8000/
- API: http://127.0.0.1:8000
- Swagger: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

数据工作台包含关键词聚合采集、普通接口调试和蒲公英接口调试三种模式，支持卡片/接口调用/JSON 视图、笔记详情抽屉、后台任务进度、Worker 排队状态、缓存命中、请求次数估算、结果复制与 CSV 导出。CSV 会导出当前全部结果，将嵌套对象展开为点号列名，并使用 UTF-8 BOM 兼容 Excel 中文显示。蒲公英工作区内置笔记详情、博主完整详情、相似博主、博主广场和筛选字典；博主广场提供按合作目标、博主与粉丝画像、数据表现、平台推荐和常规剔除分组的可视化筛选器，动态选项来自实时字典，高级 JSON 可补充任意请求字段。广场与相似博主响应会按博主生成卡片，点击卡片可继续查看完整资料、报价、数据概览、粉丝画像、趋势和近期笔记。

## 登录会话

当前首页、搜索、作者、详情和评论业务接口都要求账号会话。`a1` 和 `webId` 可以由本地算法初始化，但只生成这两个访客标识时，上游会明确返回“无登录信息”；`web_session` 由二维码登录成功响应写入，因此仍需在二维码上做一次账号确认。

扫码建立会话使用以下本机管理接口：

```text
POST /v1/xhs/auth/qrcode
GET  /v1/xhs/auth/qrcode/{login_id}
```

会话状态和主动验证接口：

```text
GET  /v1/xhs/auth/session
POST /v1/xhs/auth/session/verify
```

状态分为：`missing`（未配置）、`unverified`（文件已读取）、`valid`（服务端验证通过）、`degraded`（临时网络异常，继续保留）、`expired`（服务端确认失效）和 `error`（本地配置异常）。状态响应只包含脱敏会话编号和时间，不包含 Cookie、账号资料或 Token。

二维码约 60 秒过期。状态 `waiting_scan` 表示等待扫码，`scanned` 表示已扫码待确认，`authenticated` 表示 Cookie 已保存且 Worker 已切换，`expired` 表示需要重新生成。接口响应只返回二维码图片和状态，不返回 Cookie 内容。

二次扫码增加 `verification_waiting_scan`（展示新验证码）、`verification_scanned`（App 待确认）、`verification_cancelled`、`verification_failed` 和 `verification_required`。验证请求标识和原始响应头仅存在后端内存中；客户端只收到二维码图片、脱敏状态与倒计时。

120 短信验证状态为 `sms_code_required`。本地管理接口如下：

```text
POST /v1/xhs/auth/qrcode/{login_id}/sms
POST /v1/xhs/auth/qrcode/{login_id}/sms/resend
```

提交 Body 为 `{"code":"123456"}`。这两个接口与其他登录管理接口一样只接受 localhost 请求；验证码不写入日志或文件。

## 并发、缓存与后台任务

- 搜索分页在同一个 `search_id` 下保持顺序。
- 搜索完成后，详情、作者和评论任务并行进入 SessionPool。
- 每个 Worker 内部仍然串行；多个独立 Worker 才产生真实上游并发。
- 相同请求会通过 singleflight 合并，避免同时击穿上游。
- 默认 TTL：Homefeed 30 秒、搜索 2 分钟、评论 2 分钟、详情 10 分钟、作者 30 分钟。
- GPT 使用独立信号量，默认并发 3，不占用 XHS Worker。

后台采集接口：

```text
POST /v1/xhs/collect/jobs
GET  /v1/xhs/collect/jobs/{job_id}
GET  /v1/xhs/runtime
```

任务快照中的 `events` 会逐条返回接口名称、目标、状态、Worker、排队耗时、执行耗时、缓存状态及有界响应摘要。

## 图片与视频

详情接口会返回完整媒体信息：

- `images`：按原顺序排列的全部主图 URL，保留用于兼容简单调用方。
- `image_count`：图片总数。
- `image_items`：每张图的宽高、默认 URL、预览 URL、全部场景变体，以及 Live Photo 视频 URL。
- `video.best_url`：按分辨率、码率和文件大小选择的最高质量播放地址。
- `video.streams`：全部视频流，包含编码、格式、分辨率、FPS、码率、文件大小、主 URL 和备用 URL。

视频和图片 CDN 地址可能带有效期。需要长期使用时，应重新调用笔记详情接口刷新媒体 URL。

## 调用示例

搜索笔记：

```text
GET /v1/xhs/search/notes?keyword=咖啡&pages=3
```

获取笔记详情：

```text
GET /v1/xhs/notes/NOTE_ID?xsec_token=XSEC_TOKEN&xsec_source=pc_search
```

获取评论：

```text
GET /v1/xhs/notes/NOTE_ID/comments?xsec_token=XSEC_TOKEN
```

获取作者资料：

```text
GET /v1/xhs/users/USER_ID
```

搜索用户并补全年龄、关注/粉丝数量、获赞与收藏统计及收藏隐私状态：

```text
GET /v1/xhs/search/users?keyword=咖啡&pages=1
```

年龄来自用户公开资料标签；未公开年龄时返回 `null`。当前网页协议仅公开关注数和粉丝数，不提供任意用户的关注/粉丝名单，因此对应字段会返回 `available=false`。收藏笔记仅在 `tab_public` 明确公开时抓取；隐藏或锁定时返回 `visibility=private`，不把私密状态误报为空列表。

用户搜索结果会返回每个用户对应的 `xsec_token`。调用用户资料接口时可继续传入该 Token：

```text
GET /v1/xhs/users/USER_ID?xsec_token=XSEC_TOKEN&xsec_source=pc_search
```

资料结果会返回 `xsec_token`、`xsec_source` 和 `xsec_token_available`。只提供 `user_id` 时无法本地推导 Token，此时 `xsec_token_available=false`。

获取作者笔记时需要从搜索或作者页链路取得的 `xsec_token`：

```text
GET /v1/xhs/users/USER_ID/notes?xsec_token=XSEC_TOKEN&xsec_source=pc_search
```

## 蒲公英接口

工作台顶部有独立的“蒲公英”会话入口，可直接使用蒲公英邮箱账号和密码登录。后端以纯 Python HTTP 完成官方 CAS 邮箱密码换票、蒲公英 ticket 登录和账号验证；邮箱和密码只存在于当前请求内存中，签发的 Cookie 原子写入 `secrets/pgy_cookie.txt`，重启后自动复用。该流程不会改动小红书官网的扫码登录会话。

也可以设置 `XHS_PGY_COOKIE`，或用 `XHS_PGY_COOKIE_FILE` 指向已有 Cookie 文件。使用工作台邮箱登录时不要设置 `XHS_PGY_COOKIE`，否则环境变量会覆盖新写入的文件。不要提交 `secrets/` 中的任何内容。

蒲公英本机会话管理接口：

```text
GET  /v1/xhs/pgy/auth/session
POST /v1/xhs/pgy/auth/session/verify
POST /v1/xhs/pgy/auth/email
```

邮箱登录 Body 为 `{"email":"name@example.com","password":"..."}`。这些登录管理接口与小红书扫码管理接口一样只接受 localhost 请求。

接口列表：

```text
POST /v1/xhs/pgy/get_note_detail
POST /v1/xhs/pgy/get_blogger_detail
POST /v1/xhs/pgy/get_blogger_similar
POST /v1/xhs/pgy/get_blogger_square
GET  /v1/xhs/pgy/get_blogger_filter_options
```

笔记详情：

```json
{"note_url":"https://www.xiaohongshu.com/explore/NOTE_ID?xsec_token=XSEC_TOKEN&xsec_source=pc_pgy"}
```

调试页只需粘贴原始完整链接，后端会解析 Note ID、Xsec Token 和 Xsec Source。若蒲公英首页案例详情接口明确返回无权限，服务会先用已验证的小红书官网 Worker 获取笔记和作者，再自动分页匹配该作者在蒲公英博主主页中的笔记案例，并从传播表现接口补齐单篇曝光量与阅读量。完整命中时业务数据包含 `data_source=pgy_blogger_metrics+xhs_web` 和 `pgy_access=matched`；只有案例列表数据时标记为 `partial`，蒲公英未收录该笔记时保留小红书详情并标记为 `not_listed`。

博主综合详情一次返回 `profile`、`data_summary`、`fans_summary`、`fans_profile` 和 `fans_history`：

```json
{
  "user_id": "5c668b3e0000000012021605",
  "business": 0,
  "increase_type": 1,
  "date_type": 1
}
```

相似博主按页数连续抓取，每页固定最多 4 条：

```json
{"user_id":"5c668b3e0000000012021605","pages":3}
```

博主广场支持 `goal`、`blogger`、`fans`、`note`、`coop`、`live`、`flags` 七组筛选，并通过 `pages` 从第 1 页开始连续抓取，每页固定 20 条。工作台会把多页任务拆成每页一次本地接口调用，实时显示已完成页数，并在后续页面复用第一页返回的 `trackId`；单页失败只记录该页，不会丢弃其它页面。完整字段、枚举和上下限见 Swagger；字段名写错会返回 422。区间只填一端即可，缺少 `min` 按 0 处理，缺少 `max` 按不限处理：

```json
{
  "keyword": "护肤",
  "search_type": 1,
  "column": "fansCount",
  "sort": "desc",
  "pages": 3,
  "blogger": {
    "content_tag": ["美妆", "面部保养"],
    "location": ["上海"],
    "audience20": ["自在户外"]
  },
  "fans": {
    "count": {"min": 100000, "max": 500000},
    "location": ["浙江", "杭州"],
    "gender": 2
  },
  "coop": {
    "pic_price": {"max": 5000},
    "reply_48h_ratio": {"min": 90}
  },
  "flags": {
    "high_quality": true,
    "exclude_low_active": true
  }
}
```

树形筛选值先从 `get_blogger_filter_options` 读取。粉丝地域可传裸地名，服务会转换为平台需要的完整路径；`audience20`、`note_scene`、`consumer_behavior` 和 `industry_crowd` 仍按蒲公英字典原值传入。

所有蒲公英接口保留平台原始信封，因此业务数据固定取两层：

```python
data = resp["data"]["data"]
```

第一层 `data` 的值是完整蒲公英信封（`code/msg/success/data`）；该信封自己的 `data` 才是业务数据。

聚合采集并写入 `output/`：

```json
POST /v1/xhs/collect
{
  "keyword": "咖啡",
  "pages": 1,
  "page_size": 20,
  "note_limit": 5,
  "include_details": true,
  "include_authors": true,
  "include_comments": true,
  "comment_pages": 1,
  "use_gpt": false,
  "save": true,
  "sort": "general",
  "note_type": 0
}
```

所有列表请求采用单会话串行执行，默认请求间隔至少 1 秒。聚合接口最多搜索 5 页、返回 50 篇笔记、每篇最多抓取 5 页主评论。
