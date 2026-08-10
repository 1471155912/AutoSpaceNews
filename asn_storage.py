"""
AutoSpaceNews (ASN) - 存储模块
负责新闻数据的 JSON 文件持久化，包括：
- 读写 news.json（自动创建 data/ 目录）
- 过期新闻清理（超过 MAX_DAYS_TO_KEEP 天自动删除）
- 新旧数据合并（同一事件归入已有故事，新事件创建新故事）
- 分页查询 + 全文搜索（标题/简介/标签/来源名）
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict

import asn_config as config

logger = logging.getLogger(__name__)


def _ensure_data_dir():
    """确保 data/ 目录存在（首次运行时自动创建）"""
    os.makedirs(config.DATA_DIR, exist_ok=True)


def load_news() -> List[Dict]:
    """
    从 data/news.json 加载新闻列表
    返回空列表表示文件不存在或解析失败（不会抛异常）
    """
    _ensure_data_dir()
    if not os.path.exists(config.NEWS_FILE):
        return []
    try:
        with open(config.NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Load error: {e}")
        return []


def save_news(stories: List[Dict]):
    """将新闻列表写入 data/news.json（UTF-8 编码，缩进 2 空格便于调试）"""
    _ensure_data_dir()
    try:
        with open(config.NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"Save error: {e}")


def cleanup_old_news(stories: List[Dict]) -> List[Dict]:
    """
    清理过期新闻：删除发布时间超过 MAX_DAYS_TO_KEEP 天的故事
    时间判断逻辑：取故事自身 published_at 和所有来源中最早的 published_at
    """
    cutoff = (datetime.now() - timedelta(days=config.MAX_DAYS_TO_KEEP)).strftime("%Y-%m-%d %H:%M:%S")
    cleaned = []
    for story in stories:
        # 取故事时间和所有来源时间中最早的作为判断基准
        earliest = story.get("published_at", "")
        for src in story.get("sources", []):
            t = src.get("published_at", "")
            if t and (not earliest or t < earliest):
                earliest = t
        if earliest and earliest < cutoff:
            continue
        cleaned.append(story)

    removed = len(stories) - len(cleaned)
    if removed:
        logger.info(f"Cleaned {removed} old stories (>{config.MAX_DAYS_TO_KEEP}d)")
    return cleaned


def merge_new_results(existing_stories: List[Dict], processed_articles: List[Dict]) -> List[Dict]:
    """
    将 AI 处理后的新文章合并到已有故事列表中
    两种情况：
    1. 文章匹配已有故事（_match_story_index）→ 追加为新的来源条目
    2. 文章是新故事（_new_story）→ 创建新的故事条目
    合并后限制每个故事最多 MAX_SOURCES_PER_STORY 个来源（保留最新的）
    """
    # 建立 story_id → 索引 的快速查找表
    story_map = {}
    for i, story in enumerate(existing_stories):
        story_map[story.get("story_id", "")] = i

    new_count = 0
    updated_count = 0

    for article in processed_articles:
        # 提取内部标记字段（这些字段不会写入最终数据）
        match_idx = article.pop("_match_story_index", None)
        is_new = article.pop("_new_story", False)
        story_id = article.pop("_story_id", None)

        # 如果AI没有匹配到故事，尝试基于标题相似度进行匹配
        if match_idx is None and not is_new:
            # 检查是否与已有故事标题相似（用于AI未正确匹配的情况）
            article_title = article.get("title", "").lower().strip()
            article_title_zh = article.get("title_zh", "").lower().strip()
            
            # 计算与现有故事的标题相似度
            best_match_idx = None
            best_similarity = 0
            
            for i, story in enumerate(existing_stories):
                story_title = story.get("title", "").lower().strip()
                story_title_zh = story.get("title_zh", "").lower().strip()
                
                # 计算标题相似度（使用简单的关键词匹配）
                similarity = calculate_title_similarity(article_title, story_title)
                if article_title_zh:
                    similarity = max(similarity, calculate_title_similarity(article_title_zh, story_title_zh))
                
                # 如果相似度足够高，认为是同一故事
                if similarity > 0.8:  # 相似度阈值
                    if best_match_idx is None or similarity > best_similarity:
                        best_match_idx = i
                        best_similarity = similarity
            
            if best_match_idx is not None:
                match_idx = best_match_idx

        if match_idx is not None and 0 <= match_idx < len(existing_stories):
            # --- 归入已有故事 ---
            story = existing_stories[match_idx]
            # URL 去重：同一来源 URL 不重复添加
            existing_urls = {s.get("url", "") for s in story.get("sources", [])}
            if article.get("url", "") and article["url"] in existing_urls:
                continue

            # 如果故事缺少 title_zh，使用新文章的 title_zh 填充
            if not story.get("title_zh") and article.get("title_zh"):
                story["title_zh"] = article["title_zh"]
            # 如果故事缺少 summary，使用新文章的 summary 填充
            if not story.get("summary") and article.get("summary"):
                story["summary"] = article["summary"]
            # 如果故事缺少 tags，使用新文章的 tags 填充
            if not story.get("tags") or not any(story.get("tags", {}).values()) and article.get("tags"):
                story["tags"] = article["tags"]

            source_entry = {
                "url": article.get("url", ""),
                "source": article.get("source_name", article.get("source", "")),
                "published_at": article.get("published_at", ""),
                "title": article.get("title", ""),
            }
            story.setdefault("sources", []).append(source_entry)

            # 超出上限时按时间排序保留最新的
            if len(story["sources"]) > config.MAX_SOURCES_PER_STORY:
                story["sources"].sort(key=lambda s: s.get("published_at", ""))
                story["sources"] = story["sources"][:config.MAX_SOURCES_PER_STORY]
            updated_count += 1

        elif is_new and story_id:
            # --- 创建新故事 ---
            new_story = {
                "story_id": story_id,
                "title": article.get("title", ""),
                "title_zh": article.get("title_zh", ""),
                "summary": article.get("summary", ""),
                "tags": article.get("tags", {}),
                "published_at": article.get("published_at", ""),
                "sources": [{
                    "url": article.get("url", ""),
                    "source": article.get("source_name", article.get("source", "")),
                    "published_at": article.get("published_at", ""),
                    "title": article.get("title", ""),
                }],
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            existing_stories.append(new_story)
            story_map[story_id] = len(existing_stories) - 1
            new_count += 1

    logger.info(f"Merge: {new_count} new, {updated_count} updated")
    return existing_stories


def dedup_stories(stories: List[Dict]) -> List[Dict]:
    """
    去除重复故事：基于标题相似度检测同一事件的不同故事，合并它们。
    优先保留：
    1. 有中文标题（title_zh）的故事
    2. 摘要（summary）更长的故事（文字信息更多）
    3. 来源数量更多的故事
    """
    if len(stories) <= 1:
        return stories

    merged_into = {}  # index -> target index (合并目标)

    for i in range(len(stories)):
        if i in merged_into:
            continue
        for j in range(i + 1, len(stories)):
            if j in merged_into:
                continue
            # 比较标题相似度（中英文都检查）
            title_i = stories[i].get("title", "")
            title_j = stories[j].get("title", "")
            title_zh_i = stories[i].get("title_zh", "")
            title_zh_j = stories[j].get("title_zh", "")

            # 计算标题相似度（中英文都检查）
            sim = calculate_title_similarity(title_i, title_j)
            if title_zh_i and title_zh_j:
                sim_zh = calculate_title_similarity(title_zh_i, title_zh_j)
                sim = max(sim, sim_zh)

            # 如果标题相似度在 0.75-0.85 之间，检查是否有共同的关键实体
            # 例如："Live Coverage: SpaceX West Coast..." vs "SpaceX West Coast..."
            if 0.75 <= sim < 0.85:
                # 提取标题中的关键词（去除常见前缀如 "Live Coverage:", "Breaking:" 等）
                def extract_keywords(title):
                    # 移除常见前缀
                    cleaned = re.sub(r'^(Live Coverage|Breaking|Update|Report):\s*', '', title, flags=re.IGNORECASE)
                    # 提取所有单词（保留中文和英文）
                    words = set(re.findall(r'[\w\u4e00-\u9fff]+', cleaned.lower()))
                    # 移除常见停用词
                    stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'with'}
                    return words - stopwords
                
                keywords_i = extract_keywords(title_i)
                keywords_j = extract_keywords(title_j)
                
                # 如果两个标题的关键词重叠度很高（>= 80%），视为同一事件
                if keywords_i and keywords_j:
                    overlap = len(keywords_i.intersection(keywords_j))
                    min_keywords = min(len(keywords_i), len(keywords_j))
                    if min_keywords > 0 and overlap / min_keywords >= 0.8:
                        sim = 0.9  # 提升到合并阈值以上

            # 如果标题不够相似，再检查摘要相似度（避免漏掉标题不同但内容相同的新闻）
            if sim < 0.85:
                summary_i = stories[i].get("summary", "")
                summary_j = stories[j].get("summary", "")
                if summary_i and summary_j:
                    sim_summary = calculate_summary_similarity(summary_i, summary_j)
                    sim = max(sim, sim_summary)

            if sim >= 0.85:
                # 计算综合评分：中文标题(3分) + 摘要长度/100(每100字1分) + 来源数
                def story_score(s):
                    score = 0
                    if s.get("title_zh"):
                        score += 3
                    summary_len = len(s.get("summary", ""))
                    score += summary_len // 100
                    score += len(s.get("sources", [])) * 0.5
                    return score

                score_i = story_score(stories[i])
                score_j = story_score(stories[j])

                if score_i >= score_j:
                    keep, remove = i, j
                else:
                    keep, remove = j, i

                # 将 remove 的来源合并到 keep
                keep_sources = stories[keep].get("sources", [])
                remove_sources = stories[remove].get("sources", [])
                existing_urls = {s.get("url", "") for s in keep_sources}
                for src in remove_sources:
                    if src.get("url", "") and src["url"] not in existing_urls:
                        keep_sources.append(src)
                        existing_urls.add(src["url"])
                    elif not src.get("url"):
                        keep_sources.append(src)
                stories[keep]["sources"] = keep_sources

                # 填充缺失的 title_zh（优先保留中文标题）
                if not stories[keep].get("title_zh") and stories[remove].get("title_zh"):
                    stories[keep]["title_zh"] = stories[remove]["title_zh"]
                # 如果 keep 的 summary 为空但 remove 有，也填充
                if not stories[keep].get("summary") and stories[remove].get("summary"):
                    stories[keep]["summary"] = stories[remove]["summary"]
                # 填充 tags
                if not stories[keep].get("tags") or not any(stories[keep].get("tags", {}).values()):
                    if stories[remove].get("tags") and any(stories[remove]["tags"].values()):
                        stories[keep]["tags"] = stories[remove]["tags"]

                merged_into[remove] = keep

    # 移除被合并的故事
    deduped = [s for i, s in enumerate(stories) if i not in merged_into]
    removed = len(stories) - len(deduped)
    if removed:
        logger.info(f"Dedup: removed {removed} duplicate stories")
    return deduped


def calculate_title_similarity(title1: str, title2: str) -> float:
    """
    计算两个标题之间的相似度
    返回0-1之间的数值，1表示完全相同
    """
    if not title1 or not title2:
        return 0.0
    
    # 移除常见停用词和标点符号，只保留关键词
    # 移除非字母数字字符（保留中文字符）
    clean1 = re.sub(r'[^\w\u4e00-\u9fff]', ' ', title1.lower()).strip()
    clean2 = re.sub(r'[^\w\u4e00-\u9fff]', ' ', title2.lower()).strip()
    
    # 分割成单词
    words1 = set(clean1.split())
    words2 = set(clean2.split())
    
    if not words1 and not words2:
        return 1.0
    if not words1 or not words2:
        return 0.0
    
    # 计算Jaccard相似度
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    
    return intersection / union if union > 0 else 0.0


def calculate_summary_similarity(summary1: str, summary2: str) -> float:
    """
    计算两个摘要之间的相似度（用于检测内容相同但标题不同的新闻）
    使用简化的余弦相似度算法
    返回0-1之间的数值
    """
    if not summary1 or not summary2:
        return 0.0
    
    # 取前200个字符进行比较（避免过长摘要影响性能）
    s1 = summary1[:200].lower()
    s2 = summary2[:200].lower()
    
    # 简单的词袋模型
    words1 = set(re.findall(r'[\w\u4e00-\u9fff]+', s1))
    words2 = set(re.findall(r'[\w\u4e00-\u9fff]+', s2))
    
    if not words1 or not words2:
        return 0.0
    
    # 计算重叠比例（相对于较短的那个集合）
    intersection = len(words1.intersection(words2))
    min_len = min(len(words1), len(words2))
    
    return intersection / min_len if min_len > 0 else 0.0


def get_paginated(stories: List[Dict], page: int = 1, page_size: int = 30, search: str = "") -> Dict:
    """
    分页查询 + 全文搜索
    搜索范围：标题、简介、标签（国家/机构/领域）、来源名称
    返回格式：{items, total, page, page_size, total_pages}
    """
    filtered = stories

    if search:
        q = search.lower()
        filtered = []
        for story in stories:
            # 搜索标题
            if q in story.get("title", "").lower():
                filtered.append(story)
                continue
            # 搜索简介
            if q in story.get("summary", "").lower():
                filtered.append(story)
                continue
            # 搜索标签（国家/机构/领域）
            tags = story.get("tags", {})
            all_tags = tags.get("countries", []) + tags.get("organizations", []) + tags.get("domains", [])
            if any(q in t.lower() for t in all_tags):
                filtered.append(story)
                continue
            # 搜索来源名称（如搜索 "SpaceNews" 可匹配来源）
            if any(q in s.get("source", "").lower() for s in story.get("sources", [])):
                filtered.append(story)
                continue

    # 按发布时间倒序排列（最新的在前）
    filtered.sort(key=lambda s: s.get("published_at", ""), reverse=True)

    # 分页计算
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))  # 限制在有效范围内
    start = (page - 1) * page_size
    items = filtered[start:start + page_size]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
