import os
import arxiv
import feedparser
from datetime import datetime, timedelta
from jinja2 import Environment, FileSystemLoader
from openai import OpenAI
from dotenv import load_dotenv
import time  # 新增：用于延时避免速率限制

load_dotenv()

# ==================== Groq 免费 API 配置 ====================
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# ==================== 光学相控阵专版配置 ====================
# arXiv 关键词 + 分类 + 排除无关领域
ARXIV_QUERY = (
    'cat:physics.optics OR cat:physics.app-ph OR cat:physics.atom-ph '
    '("optical phased array" OR OPA OR LOCSET OR '
    '"coherent beam combining" OR "phased array optics" OR '
    '"optical beam combining" OR "optical phased-array") '
    '-radar -mmwave -rf -antenna -microwave -phased-array-radar'
)

# RSS 源：Optica 核心期刊
RSS_FEEDS = [
    "https://opg.optica.org/rss/opex_feed.xml",      # Optics Express
    "https://opg.optica.org/rss/ol_feed.xml",        # Optics Letters
    "https://opg.optica.org/rss/prj_feed.xml",       # Photonics Research
    "https://opg.optica.org/rss/optcon_feed.xml",    # Optics Continuum
]

MAX_DAYS_BACK = 14         # 扩大到14天，给期刊更多机会
MAX_ITEMS_PER_SOURCE = 12  # 每个 RSS 源最多取12条
FINAL_LIMIT = 12           # 最终显示条数（可自行改大，如20、30）

# 关键词过滤列表（用于 RSS 条目过滤）
RELEVANT_KEYWORDS = [
    "optical phased array", "opa", "locset",
    "coherent beam combining", "phased array optics",
    "optical beam combining", "phased-array", "optical phased-array",
    "beam steering", "phased array", "optical phased"
]

# ============================================================

def summarize_item(title: str, content: str, source: str) -> str:
    """升级版总结：300–600字中文，结构化、技术细节多"""
    prompt = f"""
你是一位光学与光子学领域的资深研究员，风格严谨、客观、技术性强。
请用**流畅的中文**（约300–600字）总结以下内容，结构如下：
1. 论文/文章核心技术路线（包括关键方法、实验/模拟设置、主要参数）
2. 提出的主要创新点或改进（用事实描述，不用“突破”“革命”等词）
3. 潜在应用场景及可能影响（基于文中讨论，保持现实）
4. 标题：{title}
5. 来源：{source}

原文摘要/内容：
{content[:12000]}

输出只包含以上4部分，不要加多余开头结尾或评价。
"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=1200
        )
        result = resp.choices[0].message.content.strip()
        print(f"[总结成功] {title[:60]}...")
        return result
    except Exception as e:
        err_msg = str(e)
        print(f"[总结失败] {title[:60]}... → {err_msg[:100]}")
        return f"总结失败：{err_msg[:150]}"
    finally:
        time.sleep(4)  # 每条总结后等待4秒，缓解速率限制

def fetch_arxiv():
    """抓取 arXiv 最新相关论文"""
    search = arxiv.Search(
        query=ARXIV_QUERY,
        max_results=40,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )
    items = []
    cutoff = datetime.now() - timedelta(days=MAX_DAYS_BACK)
    
    for result in search.results():
        pub_date = result.published.replace(tzinfo=None)
        if pub_date < cutoff:
            break
        summary_text = summarize_item(result.title, result.summary, "arXiv")
        items.append({
            "title": result.title,
            "summary": summary_text,
            "link": result.entry_id,
            "date": pub_date.strftime("%Y-%m-%d"),
            "source": "arXiv"
        })
    print(f"[arXiv] 抓到 {len(items)} 条")
    return items

def fetch_rss():
    """抓取 Optica 等期刊 RSS，并加关键词过滤"""
    items = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        source_name = feed.feed.title if 'feed' in feed and 'title' in feed.feed else url.split('/')[-1].replace('_feed.xml', '')
        
        for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                pub_date = datetime(*published[:6])
                if pub_date < datetime.now() - timedelta(days=MAX_DAYS_BACK):
                    continue
            else:
                pub_date = datetime.now()
            
            # 关键词过滤
            text_to_check = " ".join([
                entry.title or "",
                entry.get("summary") or "",
                entry.get("description") or ""
            ]).lower()
            
            if not any(kw.lower() in text_to_check for kw in RELEVANT_KEYWORDS):
                # print(f"[RSS 跳过] {entry.title[:60]}... ({source_name})")
                continue
            
            content = entry.get("summary", "") or entry.get("description", "") or entry.title
            summary_text = summarize_item(entry.title, content, source_name)
            
            items.append({
                "title": entry.title,
                "summary": summary_text,
                "link": entry.link,
                "date": pub_date.strftime("%Y-%m-%d"),
                "source": source_name
            })
    print(f"[RSS 总计] 抓到 {len(items)} 条")
    return items

def main():
    print("🚀 光学相控阵专版简报开始生成...")
    
    arxiv_items = fetch_arxiv()
    rss_items = fetch_rss()
    
    all_items = arxiv_items + rss_items
    all_items.sort(key=lambda x: x["date"], reverse=True)
    
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("index.html")
    
    today = datetime.now().strftime("%Y年%m月%d日")
    html = template.render(
        date=today,
        items=all_items[:FINAL_LIMIT],
        total=len(all_items),
        sources=", ".join(set(i["source"] for i in all_items if i["summary"].startswith("总结失败") == False))
    )
    
    os.makedirs("public", exist_ok=True)
    filename = f"public/optical_brief_{datetime.now().strftime('%Y%m%d')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✅ 生成完成！共 {len(all_items)} 条（显示前 {FINAL_LIMIT} 条），输出到 {filename}")
    print("请在浏览器打开查看 → " + filename)

if __name__ == "__main__":
    main()