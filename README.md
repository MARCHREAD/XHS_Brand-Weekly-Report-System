# 基于小红书数据的品牌营销可视化周报系统

主推品 **libtv**，竞品 **即梦、updream**。在小红书数据采集工作台上增加可断点续采的品牌周报任务，结合 BERTopic 热点发现和 LinearSVC 情感分类。

## 快速入口

- [小红书平台安装与启动](platforms/xiaohongshu/README.md)
- [真实采集与模型运行说明](platforms/xiaohongshu/docs/WEEKLY_REPORT.md)
- [系统设计](docs/brand-weekly-report-system.md)
- [课程作业最新版](docs/李昊阅_202409010201_大作业_AI代码提示词修订版.docx)

在 `platforms/xiaohongshu` 独立安装依赖并运行 `main.py`。采集工作台为 `http://127.0.0.1:8000/`，品牌周报为 `http://127.0.0.1:8000/brand-report/`。

默认每个关键词目标 100 个有效搜索结果页。平台提前结束时按不同排序补采，分别记录真实页数，去重合并；每篇笔记的主评论和子评论按游标采至平台结束。支持暂停和断点续采，异常保留未完成状态。

BERTopic 使用多语言 MiniLM、UMAP、HDBSCAN 与 c-TF-IDF。SVM 使用字符 TF-IDF 与 LinearSVC，标签与测试按笔记分组隔离；首批 AI 辅助标签只作为原型参考，不能当作独立人工验证结果。

账号登录信息、原始采集结果、运行数据库和模型权重仅保存在本地，均不上传。仓库包含源码、离线测试和设计材料。

采集基座复用自 [Maxiom-AI/Crawler-Lab](https://github.com/Maxiom-AI/Crawler-Lab) 的小红书平台模块。第三方签名组件许可见平台目录中的说明与许可证。
