"""Pure projections for the visual dashboard. All numbers derive from observed records."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import json

from .store import now

LABELS = ["positive", "neutral", "negative", "pending"]
ASPECTS = {"价格与积分": ["价格", "积分", "收费", "贵", "便宜", "算力"], "生成效果": ["效果", "质感", "画质", "好看", "一致", "变形", "口型"], "使用体验": ["好用", "难用", "卡", "打开", "排队", "速度", "操作", "报错"], "学习与创作": ["教程", "提示词", "怎么做", "制作", "学习", "创作", "模型"]}


def distribution(docs, predictions):
    counts = Counter(predictions.get(d["id"], "pending") for d in docs if d["kind"] == "comment")
    return {label: counts[label] for label in LABELS}


def interaction(note):
    values = [note["counts"].get(k, {}).get("value") for k in ["liked", "collected", "comment", "share"]]
    return sum(values) if all(isinstance(v, int) and not isinstance(v, bool) for v in values) else None


def project(report, notes, docs, lookup, topic_info, predictions, *, scope="week", brand=None, week_start=None):
    config = dict(report["config"])
    if week_start:
        config["week_start"] = week_start
        config["week_end"] = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
    start, end = config["week_start"], config["week_end"]
    names = [config["primary"], *config["competitors"]]
    brand = brand or config["primary"]
    if brand not in names:
        raise ValueError("Unknown brand")
    in_window = lambda day: scope == "history" or bool(day and start <= day <= end)
    # Search cards alone lack dates and a full body. Include verified details in comparisons.
    cohort = [n for n in notes.values() if n["detail_done"] and n["brands"] and in_window(n["date"])]
    selected = [n for n in cohort if brand in n["brands"]]
    relevant = [d for d in docs if brand in d["brands"] and in_window(d["date"])]
    comments = [d for d in relevant if d["kind"] == "comment"]
    sentiment = distribution(comments, predictions)
    classified = sum(sentiment[k] for k in LABELS[:3])
    valid_interactions = [v for n in selected if (v := interaction(n)) is not None]
    competitors = []
    for name in names:
        subset = [n for n in cohort if name in n["brands"]]
        amounts = [v for n in subset if (v := interaction(n)) is not None]
        dist = distribution([d for d in docs if name in d["brands"] and in_window(d["date"])], predictions)
        competitors.append({"brand": name, "volume": len(subset), "interactions": sum(amounts) if amounts else None, "metric_notes": len(amounts), "sentiment": dist})
    total = sum(row["volume"] for row in competitors)
    for row in competitors:
        row["share"] = row["volume"] / total if total else None
    dates = sorted({n["date"] for n in selected if n["date"]})
    series_end = date.fromisoformat(max(dates)) if scope == "history" and dates else date.fromisoformat(end)
    series_start = series_end - timedelta(days=13) if scope == "history" else date.fromisoformat(start)
    trend = []
    for i in range((series_end - series_start).days + 1):
        day = (series_start + timedelta(days=i)).isoformat()
        subset = [n for n in selected if n["date"] == day]
        amounts = [v for n in subset if (v := interaction(n)) is not None]
        trend.append({"date": day, "volume": len(subset), "interactions": sum(amounts) if len(amounts) == len(subset) else None, "metric_notes": len(amounts), "sentiment": distribution([d for d in comments if d["date"] == day], predictions)})
    topic_rows = []
    for topic in topic_info:
        group = [d for d in relevant if lookup.get(d["text"]) == topic["id"]]
        if not group:
            continue
        dist = distribution(group, predictions)
        count = sum(dist[label] for label in LABELS[:3])
        negative_rate = dist["negative"] / count if count else None
        evidence = sorted(group, key=lambda d: predictions.get(d["id"]) != "negative")[:5]
        topic_rows.append({**topic, "title": " · ".join(topic["keywords"][:3]), "text_count": len(group), "note_count": len({d["note_id"] for d in group}), "sentiment": dist, "negative_rate": negative_rate,
            "risk_candidate": bool(count >= 3 and negative_rate is not None and negative_rate >= .35),
            "evidence": [{"id": d["id"], "note_id": d["note_id"], "text": d["text"][:300], "kind": d["kind"], "date": d["date"], "sentiment": predictions.get(d["id"], "pending")} for d in evidence]})
    topic_rows.sort(key=lambda row: row["text_count"], reverse=True)
    risks = [row for row in topic_rows if row["risk_candidate"]]
    aspects = []
    for name, words in ASPECTS.items():
        matches = [d for d in comments if any(word in d["text"] for word in words)]
        if matches:
            aspects.append({"name": name, "count": len(matches), "sentiment": distribution(matches, predictions)})
    insights = []
    if topic_rows:
        first = topic_rows[0]
        insights.append({"title": f"关注焦点：{first['title']}", "text": f"当前范围内关联 {first['text_count']} 条文本、{first['note_count']} 篇笔记，可从原文判断创作场景与需求。", "target": "topics", "topic_id": first["id"]})
    if risks:
        first = max(risks, key=lambda t: t["sentiment"]["negative"])
        insights.append({"title": f"优先复核：{first['title']}", "text": f"模型标记 {first['sentiment']['negative']} 条负向评论；当前为舆情候选，需结合上下文确认。", "target": "sentiment", "topic_id": first["id"]})
    if competitors:
        leader = max(competitors, key=lambda row: row["volume"])
        insights.append({"title": f"样本声量领先：{leader['brand']}", "text": f"已取得详情的样本中识别 {leader['volume']} 篇相关笔记。采集覆盖尚不一致时，不解释为全平台市场份额。", "target": "competitors"})
    insights.append({"title": "先检查数据覆盖", "text": f"共发现 {report['collection']['notes']} 篇笔记，{report['collection']['notes_complete']} 篇已采完详情及评论；缺失日期和未采完内容不会补成演示数据。", "target": "collection"})
    pending = sentiment["pending"]
    actions = [{"id": "review-negative", "title": f"复核 {sentiment['negative']} 条负向候选", "owner": "品牌运营", "priority": "高", "target": "sentiment"},
        {"id": "review-pending", "title": f"补标 {pending} 条待判定评论", "owner": "数据分析", "priority": "中", "target": "models"},
        {"id": "coverage", "title": "核对竞品采集覆盖与样本口径", "owner": "市场研究", "priority": "中", "target": "collection"}]
    risk_available = report["models"]["sentiment"]["state"] == "trained"
    return {"scope": scope, "brand": brand, "period": [start, end], "generated_at": report["generated_at"], "observed_at": now(),
        "kpis": {"volume": len(selected), "interactions": sum(valid_interactions) if valid_interactions else (0 if not selected else None), "interaction_coverage": len(valid_interactions), "positive_rate": sentiment["positive"] / classified if classified else None, "risk_topics": len(risks) if risk_available else None, "valid_sentiment_texts": classified, "pending_texts": pending},
        "trend": trend, "trend_period": [series_start.isoformat(), series_end.isoformat()], "sentiment": sentiment, "competitors": competitors, "topics": topic_rows,
        "aspects": sorted(aspects, key=lambda row: row["count"], reverse=True), "insights": insights[:4], "actions": actions,
        "risk_rule": {"minimum_classified_comments": 3, "negative_rate": .35, "human_confirmation_required": True},
        "sample_quality": {"detail_notes": len(cohort), "completed_selected_notes": sum(n["comments_complete"] for n in selected), "selected_notes": len(selected), "selected_comment_texts": len(comments), "unassigned_topic_texts": sum(lookup.get(d["text"], -1) == -1 for d in relevant), "growth_available": False},
        "evidence": [{"id": d["id"], "note_id": d["note_id"], "text": d["text"][:400], "date": d["date"], "sentiment": predictions.get(d["id"], "pending"), "topic_id": lookup.get(d["text"], -1)} for d in comments[:100]]}


def load_dashboard(store, report, *, scope="week", brand=None, week_start=None):
    from .analysis import corpus
    notes, docs = corpus(store)
    def read(name, default):
        path = store.directory / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    bundle = report.get("_analysis", {})
    lookup = bundle.get("lookup", read("topic-assignments.json", {}))
    info = bundle.get("topics", read("topic-info.json", []))
    if not info:
        info = [{"id": t["id"], "keywords": t["keywords"], "training_count": t.get("training_count", 0)} for t in report.get("history_topics", [])]
    predictions = bundle.get("predictions", read("sentiment-predictions.json", {}))
    return project(report, notes, docs, lookup, info, predictions, scope=scope, brand=brand, week_start=week_start)
