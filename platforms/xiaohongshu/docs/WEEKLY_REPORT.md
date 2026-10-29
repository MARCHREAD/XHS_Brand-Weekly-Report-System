# libtv 品牌营销周报

主推品为 **libtv**，竞品为 **即梦、updream**。默认报告窗口为 2026-10-19 至 2026-10-25（北京时间）；修改 `weekly_config.json` 或在门户中设置其他连续七天。

## 运行

原采集工作台保持 `http://127.0.0.1:8000/`，品牌周报入口为 `http://127.0.0.1:8000/brand-report/`，原静态演示保存在 `demo.html`。普通小红书 Cookie 登录和蒲公英登录是两个会话，本功能使用前者。

默认入口现在是 `dashboard.html`，以演示版风格呈现真实数据：深蓝侧栏、四项 KPI、发文与累计互动趋势、话题排行、样本竞品份额、情绪环图、评价维度及本地行动清单。可按品牌、连续七天或全部已采样本筛选，点击话题查看原文，导出与当前范围一致的 JSON，或查看保存的周报快照。`operations.html` 保留采集配置和人工标注入口。

在小红书平台目录运行：

```powershell
py -3 -m venv .venv-weekly
.\.venv-weekly\Scripts\python.exe -m pip install -r requirements-weekly.txt
.\.venv-weekly\Scripts\python.exe main.py
```

已有兼容 PyTorch 的本地环境可用 `--system-site-packages` 复用大型依赖。本次环境使用独立 `.venv-weekly` 安装模型组件，并复用了本机 CPU PyTorch；首次编码需下载指定 MiniLM 权重，完整缓存可直接复用。

门户点击“启动真实采集”，或在 PyCharm 中右键运行 `weekly.py`。无参数启动配置文件中的新任务；程序输出任务 ID，采集在独立后台进程继续。续采和分析也可手动运行：

```powershell
py -3 weekly.py collect --job REPORT_ID
.\.venv-weekly\Scripts\python.exe weekly.py analyze --job REPORT_ID
.\.venv-weekly\Scripts\python.exe weekly.py train --job REPORT_ID
```

## 采集口径

- 每个关键词默认目标为 100 个非空搜索结果页，页面与 API 均校验最低值 100。
- 当前平台最新发布搜索实测在第 51 页返回 `has_more=false`，前 50 页有结果。采集器按最新发布、综合、最多点赞的顺序补足目标，分别保留每种排序的页数，笔记按 ID 合并。跨排序有效页是抽样请求量，不能等同 100 页互不重复的笔记。
- 不设置原综合采集的 50 篇笔记上限。逐篇取得详情，每篇默认采集前两页主评论及页面自带的回复，不展开追抓子评论。`comment_page_limit=2` 控制上限，`null` 可选择原来的全量评论模式。
- `notes_complete` 表示详情和当前配置的评论采样目标完成；`comments.complete` 保留主评论实际翻页结束事实，`full_comments_complete` 单列主评论和回复是否全量完成。两页采样不代表全量评论，前期超出两页的已采数据仍保留，情绪与话题结果仅代表混合覆盖的样本。
- 每页落盘，异常、重复游标、重复页面、登录失效均记录状态。游标停滞时保留未完成标记；暂停后可续采。
- 临时延后的笔记保留已有评论和游标，并移至普通待采笔记之后；仍计入未完成数量，达到当前配置的采集目标后清除延后标记。调整为两页时，已有两页以上或主评论已自然结束的断点直接满足采样目标，旧数据保留。
- 默认 `rate_limit_policy=pause`：遇到平台限流立即保留断点并暂停，人工处理后续采原任务；不自动等待长时间冷却。`backoff` 可启用原来的递增冷却策略。
- SQLite 中保存搜索 ID、原始观测令牌及归一化数据，因此只存于被 Git 忽略的 `output/weekly/<REPORT_ID>/`。不上传 Cookie、原始采集数据、运行数据库或模型权重。

## BERTopic

固定编码器：`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`。处理链为多语言 MiniLM 语义向量、UMAP 降维、HDBSCAN 聚类、c-TF-IDF 话题词提取，采用固定随机种子。少于 20 条有效去重文本时明确返回样本不足，不替换为随机话题。

模型可在跨期已采集语料上训练，周报话题只计入目标日期内的文本；跨期训练话题另列。保存 `bertopic-topics.csv`、`topic-assignments.json` 和向量数组，便于核查样本归属。话题编号只在同一次训练中有效，重训后的编号不能直接当作历史话题增长。

模型训练排除重复文本、纯表情或数字以及订阅提醒机器人文本；这些过滤只作用于分析输入，原始评论仍完整保留。中文话题词过滤标点、单字和常见虚词，避免用标点符号作为话题名称。语义向量按文本与编码器 ID 缓存，新增数据只编码未缓存文本。

完整拟合后的 UMAP、HDBSCAN 和 c-TF-IDF 管线保存为 `bertopic-model.joblib`，MiniLM 使用固定模型 ID 重新挂接，不复制权重到仓库。训练后实际加载模型并对样本执行 `transform`，记录校验结果、依赖版本和文件哈希至 `topic-model-metadata.json`。加载需要与训练时兼容的依赖环境。

## LinearSVC 情感分类

采用字符 TF-IDF 和 `LinearSVC(class_weight="balanced")`，分类为正向、中性、负向。默认同时引入固定 MiniLM 语义向量作为辅助特征，编码器不参与微调；可通过 `svm_semantic_features=false` 关闭该增强。字符特征对中文短评论及混合英文产品名较直接，不依赖运行时分词。

真实评论在标注工作台逐条标注，或编辑任务目录的 `sentiment-labels.csv`。至少需要 45 条有效去重评论、每类 8 条，并且不同笔记组中应同时具有类别覆盖。人工工作台标签优先于旧 CSV 中的辅助标签。首次测试评论及其整篇笔记保留为固定测试组，后续训练继续使用相同测试评论；同组其他新标签不进入训练。完全重复文本先去重，TF-IDF 只在训练部分拟合。字符 n-gram 范围和 C 值由训练数据内部三折分组交叉验证选择，不依据测试分数选参。评估分类器另存于 `training-history/`，生产分类器在评估后重新拟合全部已标注样本并保存、加载验证。

结果保存 `sentiment-svm.joblib`、`sentiment-metrics.json` 和预测映射，指标包括分类报告、混淆矩阵和标签来源。`ai_assisted_review` 表示 AI 辅助标注，相关分数仅衡量相对这批标签的一致性；只有全部标签来自门户中的 `human_review` 时才标记为独立人工参考。首批辅助标注规模小，仍需人工补标并增加负向样本。

页面同时展示宏平均 F1、各类召回率、测试支持数、标签来源与混淆矩阵，不以总体准确率掩盖少数类表现。预测分类间隔小于 0.2 时进入“待复核”，该间隔不是概率。正向率以已判定文本为分母；环图只包含正、中、负三类，待复核数量另列。负向话题仅作为人工复核候选。

## 快照与接口

每次分析保存完整周报快照与一致的内部话题/预测映射，避免训练期间把新旧模型结果混用。内部映射不会通过周报 API 输出。数据记录有独立版本号，任务状态更新不等同数据变化；页面会标记新增数据尚待模型更新的情况。

- `GET /v1/xhs/weekly/jobs/{id}/report?scope=week&brand=libtv&week_start=2026-10-19`：选择品牌和周次；`scope=history` 查看跨期样本。
- `GET /v1/xhs/weekly/jobs/{id}/snapshots`：列出可查看快照。
- `GET /v1/xhs/weekly/jobs/{id}/report?snapshot=SNAPSHOT_ID`：读取冻结的历史结果。
- `GET /v1/xhs/weekly/jobs/{id}/training-history`：读取训练历史中的评估记录。

## 数据边界

品牌归因由观测到的标题、正文中的名称匹配产生，搜索来源只保留为来源信息。多品牌笔记可以计入多个品牌，不能把相加结果解释为去重市场总量。评论按所属讨论串归因，内容可能在评价生成作品而非工具产品本身，需下钻确认。

周报按真实发布时间筛选，日期缺失保持缺失。互动量为采集时累计快照，非当周新增互动；缺少此前采集基线时增长率保持不可用。未训练情感模型、数据字段缺失、评论未采全等情况均在门户显示，不使用旧演示数字补齐。

## 离线验证

```powershell
py -3 -m pytest tests -q
node --check web/brand-report/live.js
```

新增用例覆盖两页上限、随页回复保留、大笔记断点直接达标、限流暂停、跨排序 100 页、主评论与子评论全分页、断点去重、游标停滞、周次筛选、标注 CSV 保留和 API 参数边界。测试使用本地 fixture，不调用真实采集接口。
