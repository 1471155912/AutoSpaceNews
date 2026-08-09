# AutoSpaceNews (ASN) - 航天新闻聚合器

---

## **免责声明**

**1. 新闻内容不确定性**
本工具自动从互联网多个来源抓取新闻，经 AI 筛选和摘要后呈现。由于信息来源的多样性和自动化处理的局限性，新闻内容的准确性、完整性和时效性无法得到完全保证。部分摘要可能存在翻译偏差或语义丢失，请务必以原始来源为准。

**2. 不代表作者立场**
本工具所展示的新闻内容均来自第三方来源，不代表工具作者或开发者对这些消息的认可、支持或背书。新闻观点、分析结论等均为原始来源作者的个人或机构立场。

**3. API 隐私与安全风险**
本工具使用 DeepSeek API 进行 AI 处理。使用时请注意：
- 您的 API 密钥保存在本地文件中（已做混淆处理，但非强加密），请注意保护
- 抓取到的新闻内容会发送至 DeepSeek API 服务器进行处理
- 请勿在公共网络或不受信任的环境中运行本工具
- 分发本工具时，请提醒使用者注意 API 密钥的安全性和数据隐私问题

**4. API 资费消耗**
本工具每次更新新闻均需调用 DeepSeek API，会产生费用：
- 使用 DeepSeek V4 Flash 模型，输入约 ¥1/百万token，输出约 ¥2/百万token
- 每次更新约消耗 50,000 ~ 150,000 tokens（视新闻数量而定）
- 单次更新费用约 ¥0.05 ~ ¥0.30
- 若每 4 小时更新一次，日均约 6 次更新，日费用约 ¥0.3 ~ ¥1.8
- 月费用约 ¥9 ~ ¥54（取决于新闻量和更新频率）
- 请合理设置更新间隔，避免不必要的资费消耗

**5. 其他**
- 本工具仅供学习和个人使用，请勿用于商业用途
- 使用者应自行承担因使用本工具产生的一切风险和责任
- 本工具作者不对因使用本工具造成的任何损失负责

---

## 项目简介

AutoSpaceNews（ASN）是一款**AI 生成的**面向航天爱好者的**自动化航天新闻聚合工具**。它从全球 22 个数据源（19 个 RSS 新闻源 + Spaceflight News API + 新浪科技 API + 中文招投标平台）自动抓取最新内容，经 AI 智能筛选、翻译、摘要后，以卡片流形式呈现给用户。整个过程无需人工干预，运行后即可获得全球航天动态。

### 核心功能

- **多源并发抓取** — 22 个数据源同时请求，耗时仅取决于最慢的单个源
- **AI 智能处理** — DeepSeek V4 Flash 自动过滤非航天内容，生成中文摘要与分类标签
- **跨源去重合并** — Jaccard 标题相似度 ≥ 0.85 自动识别同一事件，多来源聚合展示
- **定时自动刷新** — 默认 4 小时一轮，系统托盘常驻后台，支持 10 分钟 ~ 24 小时自定义

### 工作流程

并发抓取 → 标题快筛 → AI 过滤+摘要 → 相似度去重 → 合并存储 → 分页展示

---

## 数据源列表

### RSS 新闻源（19个，并发抓取）

| 分类 | 来源名称 | 网址 |
|------|---------|------|
| 核心航天 | SpaceNews | https://spacenews.com/ |
| | NASA Breaking News | https://www.nasa.gov/news/ |
| | Space.com | https://www.space.com/ |
| | Spaceflight Now | https://spaceflightnow.com/ |
| | The Verge Space | https://www.theverge.com/space |
| | Ars Technica Space | https://arstechnica.com/space/ |
| 高频航天 | NASASpaceFlight | https://www.nasaspaceflight.com/ |
| | SpaceFlight Insider | https://spaceflightinsider.com/ |
| | SpaceQ | https://spaceq.ca/ |
| | SatNews | https://www.satnews.com/ |
| 政策与追踪 | Space Policy Online | https://spacepolicyonline.com/ |
| | KeepTrack.Space | https://www.keeptrack.space/ |
| 国防/航天 | DefenseScoop | https://defensescoop.com/ |
| | Air & Space Forces | https://www.airandspaceforces.com/ |
| 传统媒体 | BBC Science | https://www.bbc.com/news/science_and_environment |
| | CNN Tech | https://edition.cnn.com/specials/tech |
| | Fox News Science | https://www.foxnews.com/science |
| | NYT Science | https://www.nytimes.com/section/science |
| | The Guardian Science | https://www.theguardian.com/science/space |

### REST API 数据源

| 来源名称 | 类型 | 说明 |
|---------|------|------|
| Spaceflight News API | REST API | https://spaceflightnewsapi.net/ — 免费航天新闻聚合 API |
| 新浪科技 | JSON API | https://tech.sina.com.cn/ — 国内科技新闻，按航天关键词过滤 |

### 中文招投标信息

| 来源名称 | 网址 |
|---------|------|
| 中国招投标公共服务平台 | http://bulletin.cebpubservice.com/ |

---

## 快速开始

### 环境要求
- Python 3.10+
- Windows 10/11（系统托盘功能依赖 Windows API）

### 安装与运行

1. 确保已安装 Python 3.10 或更高版本
2. 双击运行 `start.bat`（首次会安装依赖），或双击 `ASN-Launcher.vbs`（静默启动，无控制台窗口）
3. 浏览器将自动打开 `http://localhost:8890`
4. 首次运行需配置 DeepSeek API 密钥（在网页弹窗中粘贴）

如需生成独立 EXE 可执行文件，运行 `build_exe.bat`，生成的 `dist/AutoSpaceNews.exe` 可放到桌面使用。

### 手动运行

```bash
pip install -r requirements.txt
python asn_main.py
```

### 系统托盘

启动后系统托盘会出现 ASN 图标，右键菜单支持：打开浏览器、手动更新、退出。

---

## 项目结构

```
AutoSpaceNews/
├── asn_main.py          # 主程序（FastAPI 服务 + 系统托盘）
├── asn_config.py        # 配置文件（数据源、API、存储参数）
├── asn_ai.py            # AI 处理模块（过滤/摘要/标签/去重）
├── asn_scheduler.py     # 定时调度器
├── asn_storage.py       # 存储模块（JSON 持久化 + 去重）
├── asn_token_tracker.py # Token 用量追踪与动态定价
├── asn_fetchers/        # 数据抓取模块
│   ├── asn_rss.py       #   RSS 源抓取（19 个源，并发请求）
│   ├── asn_snapi.py     #   Spaceflight News API 抓取
│   ├── asn_sina.py      #   新浪科技 API 抓取
│   └── asn_bidding.py   #   招投标网站抓取
├── static/
│   ├── index.html       # 前端界面（暗色/亮色主题切换）
│   └── asn_icon.ico     # 系统托盘图标
├── data/
│   ├── news.json        # 新闻数据（自动生成）
│   ├── settings.json    # 用户设置（主题、刷新间隔等）
│   └── token_usage.json # API 开销记录
├── requirements.txt     # Python 依赖
├── start.bat            # Windows 启动脚本（有控制台窗口）
├── ASN-Launcher.vbs     # 静默启动器（无控制台窗口）
├── build_exe.bat        # EXE 打包脚本（需 PyInstaller）
├── LICENSE              # MIT 开源许可证
├── .asn_key             # API 密钥文件（自动生成，已混淆）
└── README.md            # 本文件
```

---

## 配置说明

### 更新间隔

编辑 `asn_config.py` 中的 `FETCH_INTERVAL_MINUTES`，默认 240 分钟（4小时）。也可在网页设置面板中调整（10分钟 ~ 24小时）。

### AI 批处理大小

`BATCH_SIZE` 控制每次送入 AI 的文章数量，默认 15。增大可减少 API 调用次数但增加单次延迟。

### 数据保留天数

`MAX_DAYS_TO_KEEP` 默认 10 天，超过的新闻会自动清理。

### 动态定价

系统每天首次更新时自动获取 DeepSeek 最新定价并保存到 `data/token_usage.json`。历史成本按当时价格计算，新更新按最新价格计算。也可在网页"Token 用量"面板中手动修改。

---

## 内容过滤规则

本工具使用双重过滤机制确保只显示航天相关新闻：

### 标题级快速过滤
系统首先检查标题中是否包含以下关键词，匹配则直接跳过（不调用AI）：
- **天文观测**: "apod", "astronomy picture", "meteor shower", "solar eclipse", "lunar eclipse", "comet visible", "planet alignment", "stargazing"
- **航空内容**: "fighter jet", "air show", "airline", "boeing", "airbus", "f-16", "f-22", "f-35", "drone", "uav"
- **产品评测**: "product review", "开箱", "unboxing", "review"
- **历史回顾**: "on this day", "this day in space", "space history", "historical", "anniversary", "retrospective"
- **娱乐内容**: "game", "gaming", "simulator", "movie", "film", "entertainment", "sci-fi"

### AI智能过滤
对于未被标题过滤的文章，AI进一步分析内容，排除：
- 纯天文观测事件（如月相、流星雨等，不属于航天工程）
- 历史回顾类文章（"On this day in space!" 等）
- 产品评测和广告内容
- 游戏、影视等娱乐内容
- 纯航空新闻（民航、战斗机等）

---

## 去重策略

系统采用多层去重机制：

1. **URL 去重**：同一来源 URL 不重复添加
2. **标题相似度去重**：基于 Jaccard 相似度算法，当两篇新闻标题相似度 ≥ 0.85 时视为同一事件
3. **质量评分合并**：优先保留有更多来源、已有中文标题、摘要更长的版本
4. **来源上限**：每个故事最多保留 15 个来源（可配置），超出时按时间排序保留最新的

---

## 技术栈

- **后端**: Python FastAPI + Uvicorn
- **AI**: DeepSeek V4 Flash（动态定价：输入 ¥1/M tokens，输出 ¥2/M tokens）
- **数据抓取**: httpx + feedparser + BeautifulSoup
- **定时任务**: APScheduler
- **前端**: 原生 HTML/CSS/JS（单文件，响应式设计，暗色/亮色主题切换）
- **系统托盘**: pystray + Pillow
- **数据存储**: JSON 文件（news.json + settings.json + token_usage.json）

---

## 关于作者

本项目通过 **Vibe Coding** 方式由 AI 辅助构建。

**来源**: AutoSpaceNews, made by [@小橙子的宇宙Jackoraniverse](https://space.bilibili.com/455972735) with Qoder AI agent program & Deepseek API

**开源协议**: [MIT License](LICENSE)

---

## 许可证

本项目采用 MIT 开源许可证。详见 [LICENSE](LICENSE) 文件。

Copyright © 2026 小橙子的宇宙Jackoraniverse

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
