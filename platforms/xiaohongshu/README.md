# 小红书 · 内容采集与品牌营销周报

[← 返回 Crawler Lab](../../README.md) · [API 参数详解](docs/API_REFERENCE.md) · [原启动说明](STARTUP.md)

这是 Crawler Lab 仓库原有的小红书项目，现整体迁入 `platforms/xiaohongshu/`。内容接口、签名实现、前端、测试与独立配置均保留。

## 能力

| 类别 | 功能 |
| --- | --- |
| 内容搜索 | 关键词笔记搜索、用户搜索、分页与筛选 |
| 笔记详情 | 文本、话题、图片、视频流、互动统计与原始信息 |
| 用户 | 资料、作者笔记；平台实际返回的统计、标签和公开收藏状态 |
| 评论 | 主评论、子评论和分页 |
| 综合采集 | 搜索、详情、作者、评论组合；后台任务与 JSONL 落盘 |
| 蒲公英 | 笔记商业信息、博主画像、相似博主、广场筛选与字典 |
| 可选内容补全 | OpenAI Structured Outputs 摘要与主题补全 |
| 品牌营销周报 | libtv 与即梦、updream 的真实采集任务；100 页目标、评论全分页、断点续采；BERTopic 与 LinearSVC 本地分析 |

普通内容签名和蒲公英请求由 Python HTTP 完成，`collector/_signer/` 内置适配的签名实现；工作台页面不承担抓取或签名。

## 启动

建议使用 Python 3.13，并在本目录建立独立虚拟环境：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.cmd
```

默认工作台：**http://127.0.0.1:8000/**；交互式接口文档：**http://127.0.0.1:8000/docs**。

品牌营销周报门户：**http://127.0.0.1:8000/brand-report/**。真实数据看板沿用演示版的侧栏、KPI、趋势、竞品条形图、情绪环图和行动面板，支持切换品牌、周次、跨期范围、原文下钻及归档快照。默认主推 libtv、竞品即梦和 updream，每个关键词目标 100 个有效结果页，逐篇采集详情及前两页主评论（含随页回复），支持暂停与断点续采。安装独立 `requirements-weekly.txt` 后可运行并保存 BERTopic 和 LinearSVC；SVM 需真实评论标注。采集与标注管理在 `operations.html`，原演示页面保存在 `demo.html`。[周报运行与数据口径](docs/WEEKLY_REPORT.md)。

大评论量笔记可保留断点延后补采，仍计入未完成；遇到平台限流时，默认保留断点并暂停，处理后继续原任务。

模型离线复核：在本平台目录运行 `.\.venv-weekly\Scripts\python.exe scripts\verify_weekly_models.py --job REPORT_ID`，可复算固定测试集并检查已保存的 BERTopic 和 SVM 模型；此命令不启动采集或重新训练。[算法原理、实测效果与开发截图](../../docs/algorithm-implementation.md)。

如果浏览器提示无法访问，请先在本目录启动服务：

```powershell
cd platforms\xiaohongshu
.\start.cmd
```

启动后再打开 `/brand-report/`；直接双击 HTML 文件不会加载 FastAPI 的静态路由。

手动运行可使用 `.\.venv\Scripts\python.exe main.py`。可配置项参考 [.env.example](.env.example)；按配置项设置进程环境变量，勿将真实 Key 填进示例文件。

## 登录与配置

| 会话 | 配置 / 使用方式 |
| --- | --- |
| 普通小红书 | 工作台扫码登录；或本机 `secrets/xhs_cookie.txt`、`XHS_COOKIE` / `XHS_COOKIE_FILE` |
| 多账号采集 | `secrets/xhs_cookies.txt`，每行一个独立会话；有效 Worker 数受可用账号数限制 |
| 蒲公英 | 独立邮箱密码或手机号验证码登录；或 `XHS_PGY_COOKIE` / `XHS_PGY_COOKIE_FILE`，默认保存在 `secrets/pgy_cookie.txt` |
| 可选 OpenAI 补全 | `OPENAI_API_KEY`；不用补全时无需配置此项 |

普通会话与蒲公英会话分开保存。平台要求再次扫码或短信验证时，工作台显示对应本人确认流程；未知验证类型明确报告，不伪装为登录成功。手机号验证码登录使用同一 Python Session 完成发送、换票、账号验证和 Cookie 保存；发送失败或验证码错误不会覆盖已有有效会话。

登录管理仅接受本机来源。运行 Cookie、会话文件和采集输出均不随本次仓库整理上传。

## 接口导航

| 路由 | 说明 |
| --- | --- |
| `GET /v1/xhs/search/notes` | 搜索笔记 |
| `GET /v1/xhs/search/users` | 搜索用户 |
| `GET /v1/xhs/notes/{note_id}` | 笔记详情 |
| `GET /v1/xhs/notes/{note_id}/comments` | 笔记评论 |
| `GET /v1/xhs/users/{user_id}` | 用户资料 |
| `GET /v1/xhs/users/{user_id}/notes` | 作者笔记 |
| `POST /v1/xhs/collect` | 综合采集 |
| `POST /v1/xhs/collect/jobs` | 后台采集任务 |
| `GET /v1/xhs/runtime` | Worker、队列与运行状态 |
| `/v1/xhs/pgy/...` | 蒲公英笔记、画像、相似博主、广场和字典 |

蒲公英登录管理路由：`POST /v1/xhs/pgy/auth/email`、`POST /v1/xhs/pgy/auth/phone/code`、`POST /v1/xhs/pgy/auth/phone`。手机号接口只接受本机请求，发送接口返回短期 `login_id`，提交接口只需 `login_id` 和 6 位验证码。

笔记/作者请求中的 `xsec_token` 和 `xsec_source` 应来自搜索或分享链接，不按 ID 凭空生成。完整参数、请求示例和业务响应层次见 [API 参数详解](docs/API_REFERENCE.md) 或运行中的 `/docs`。

## 目录

```text
collector/          采集、签名、会话、任务、归一化与 API
collector/_signer/  内置签名实现及其 MIT 许可证
web/                原有工作台界面
web/brand-report/   品牌营销可视化周报门户
 tests/             离线测试
 secrets/           本机凭据，Git 忽略
 output/            采集结果，Git 忽略
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

原 README 中的历史线上验收结论保留在参数详解中；对应本机 `analysis/` 记录不随仓库迁移上传。本次仅验证目录迁移后的离线行为，不新增真实登录、采集或商业账号操作。

## 边界

- 资料字段可能缺失；未公开或上游未返回的信息不作推断。
- 当前协议并不提供任意用户的完整关注/粉丝名单；数量与名单是不同能力。
- 私密收藏、商业权限不足、验证要求和上游错误按实际状态返回。
- 多账号并发不等同于复制同一 Cookie 创建多个独立身份；媒体地址也有有效期。
- OpenAI 补全是可选独立步骤，产生的摘要与平台原始数据分开处理。

[第三方说明](THIRD_PARTY_NOTICES.md) · [仓库迁移说明](../../docs/REPOSITORY_LAYOUT.md)

品牌周报 Word 文档：[数据需求说明书](../../docs/brand-weekly-report-data-requirements.docx) · [系统架构与功能说明书](../../docs/brand-weekly-report-system-diagrams.docx)
