from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import PyPDF2
import io
import json
import os
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== API Key =====
api_key = None
try:
    with open(".env", "r") as f:
        for line in f:
            if "ANTHROPIC_API_KEY" in line:
                api_key = line.strip().split("=")[1]
except:
    pass

client = anthropic.Anthropic(api_key=api_key, base_url="https://api.yunjintao.com/")

# ===== 知识库 =====
KB_FILE = "knowledge_base.json"

def load_kb():
    if os.path.exists(KB_FILE):
        with open(KB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_kb(kb):
    with open(KB_FILE, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)

def add_to_kb(name, text, company, industry=""):
    kb = load_kb()
    for doc in kb:
        if doc["name"] == name:
            return False
    kb.append({"name": name, "text": text[:2000], "company": company, "industry": industry})
    save_kb(kb)
    return True

def search_similar(query, company, industry, n=10):
    kb = load_kb()
    if not kb:
        return []
    query_words = set(query[:500])
    same_company, same_industry = [], []
    for doc in kb:
        doc_words = set(doc["text"][:500])
        overlap = len(query_words & doc_words)
        if doc.get("company") == company:
            same_company.append((overlap, id(doc), doc))
        elif doc.get("industry") == industry and industry:
            same_industry.append((overlap, id(doc), doc))
    same_company.sort(reverse=True)
    same_industry.sort(reverse=True)
    results = [doc for _, _, doc in same_company[:6]] + [doc for _, _, doc in same_industry[:4]]
    return results[:n]

# ===== 巨潮资讯 =====
def search_stock_code(keyword):
    try:
        res = requests.post(
            "http://www.cninfo.com.cn/new/information/topSearch/query",
            params={"keyWord": keyword, "maxNum": 5},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        return [{"name": i.get("zwjc",""), "code": i.get("code",""), "orgId": i.get("orgId","")}
                for i in res.json() if i.get("category") == "A股"]
    except:
        return []

def fetch_announcement_list(stock_code, org_id, page_size=10):
    try:
        column = "sse" if stock_code.startswith("6") else ("bjse" if stock_code.startswith(("8","4")) else "szse")
        payload = (f"stock={stock_code},{org_id}&tabName=fulltext&pageSize={page_size}"
                   f"&pageNum=1&column={column}&category=&plate=&seDate=&searchkey="
                   f"&secid=&sortName=&sortType=&isHLtitle=true")
        res = requests.post(
            "http://www.cninfo.com.cn/new/hisAnnouncement/query", data=payload,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "http://www.cninfo.com.cn",
                "Origin": "http://www.cninfo.com.cn"
            }, timeout=10
        )
        return [{"title": i.get("announcementTitle",""),
                 "date": str(i.get("announcementTime",""))[:10],
                 "url": "http://static.cninfo.com.cn/" + i.get("adjunctUrl","")}
                for i in (res.json().get("announcements") or [])]
    except:
        return []

def fetch_announcement_text(pdf_url):
    try:
        res = requests.get(pdf_url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "http://www.cninfo.com.cn"
        }, timeout=15)
        reader = PyPDF2.PdfReader(io.BytesIO(res.content))
        return "".join(p.extract_text() or "" for p in reader.pages[:10])
    except:
        return ""

def auto_build_kb(company_name, stock_code, org_id, industry, peers):
    for ann in fetch_announcement_list(stock_code, org_id, page_size=6)[1:6]:
        text = fetch_announcement_text(ann["url"])
        if text:
            add_to_kb(f"{company_name}_{ann['date']}_{ann['title'][:20]}", text, company_name, industry)
    if peers:
        for peer_name in peers[:2]:
            stocks = search_stock_code(peer_name)
            if stocks:
                p = stocks[0]
                for ann in fetch_announcement_list(p["code"], p["orgId"], page_size=2)[:2]:
                    text = fetch_announcement_text(ann["url"])
                    if text:
                        add_to_kb(f"{p['name']}_{ann['date']}_{ann['title'][:20]}", text, p["name"], industry)

def get_industry_peers(company_name, ann_text=""):
    try:
        prompt = f"""你是A股行业分析师。请根据以下信息判断该公司所属行业，并给出2个最具可比性的A股上市公司。

公司名称：{company_name}
公告摘要：{ann_text[:500]}

请严格按以下JSON格式输出，不要输出任何其他内容：
{{"industry": "行业名称", "peers": ["可比公司1", "可比公司2"]}}"""
        message = client.messages.create(
            model="claude-3-5-haiku-20241022", max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        result = message.content[0].text.strip().replace("```json","").replace("```","").strip()
        data = json.loads(result)
        return data.get("industry",""), data.get("peers",[])
    except:
        return "", []

def analyze_announcement(text, similar_docs, company_name, industry):
    context = ""
    if similar_docs:
        context = "\n\n【知识库召回的参考案例】\n"
        for doc in similar_docs:
            label = "同公司历史" if doc.get("company") == company_name else f"同行业({doc.get('company','')})"
            context += f"\n▸ [{label}] {doc['name'][:30]}\n{doc['text'][:100]}...\n"

    prompt = f"""你是一位资深A股投研分析师，请对以下公告进行结构化分析。
{"以下是知识库中召回的历史参考案例，请结合这些案例对当前公告进行对比分析。" if similar_docs else ""}

【当前公告】
公司：{company_name}{"（" + industry + "行业）" if industry else ""}
{text[:3000]}
{context}

请严格按以下JSON格式输出，不要输出任何其他内容：
{{
  "oneLiner": "一句话说清楚：谁、做了什么、关键数字",
  "sentiment": "positive或neutral或negative三选一",
  "sentimentReason": "一句话理由，不超过20字",
  "actionHolders": "持仓者的一句话行动建议",
  "actionNonHolders": "未持仓者的一句话行动建议",
  "keyRisk": "最重要的一个风险，一句话不超过30字",
  "historyComparison": "与该公司历史公告相比有何变化，一句话",
  "peerComparison": "与同行业可比公司相比表现如何，一句话",
  "keyData": [
    {{"label": "指标名称", "value": "具体数值"}},
    {{"label": "指标名称", "value": "具体数值"}},
    {{"label": "指标名称", "value": "具体数值"}}
  ]
}}"""

    message = client.messages.create(
        model="claude-3-5-haiku-20241022", max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    result = message.content[0].text.strip().replace("```json","").replace("```","").strip()
    return json.loads(result)

# ===== 接口定义 =====
class SearchRequest(BaseModel):
    keyword: str

class AnnouncementRequest(BaseModel):
    stock_code: str
    org_id: str

class AnalyzeRequest(BaseModel):
    stock_code: str
    org_id: str
    company_name: str
    announcement_url: str
    announcement_title: str
    announcement_date: str

@app.post("/api/search")
def api_search(req: SearchRequest):
    stocks = search_stock_code(req.keyword)
    return {"results": stocks}

@app.post("/api/announcements")
def api_announcements(req: AnnouncementRequest):
    anns = fetch_announcement_list(req.stock_code, req.org_id)
    result = [{"id": f"{a['date']}_{i}", "title": a["title"], "date": a["date"], "url": a["url"]}
              for i, a in enumerate(anns)]
    return {"announcements": result}

@app.post("/api/analyze")
def api_analyze(req: AnalyzeRequest):
    ann_text = fetch_announcement_text(req.announcement_url)
    if not ann_text.strip():
        return {"error": "公告内容获取失败"}

    industry, peers = get_industry_peers(req.company_name, ann_text)
    auto_build_kb(req.company_name, req.stock_code, req.org_id, industry, peers)
    similar_docs = search_similar(ann_text, req.company_name, industry)
    result = analyze_announcement(ann_text, similar_docs, req.company_name, industry)

    add_to_kb(
        f"{req.company_name}_{req.announcement_date}_{req.announcement_title[:20]}",
        ann_text, req.company_name, industry
    )

    kb = load_kb()
    companies = list(set([d.get("company","") for d in kb]))

    recalls = [{"source": "self" if d.get("company") == req.company_name else "peer",
                "title": d.get("name","")[:30], "date": "", "company": d.get("company","")}
               for d in similar_docs]

    return {
        "industry": industry,
        "comparables": peers,
        "recalls": recalls,
        "oneLiner": result.get("oneLiner",""),
        "sentiment": result.get("sentiment","neutral"),
        "sentimentReason": result.get("sentimentReason",""),
        "actionHolders": result.get("actionHolders",""),
        "actionNonHolders": result.get("actionNonHolders",""),
        "keyRisk": result.get("keyRisk",""),
        "historyComparison": result.get("historyComparison",""),
        "peerComparison": result.get("peerComparison",""),
        "keyData": result.get("keyData",[]),
        "kb": {
            "totalAnnouncements": len(kb),
            "totalCompanies": len(companies),
            "companies": [{"name": c, "code": "", "count": len([d for d in kb if d.get("company")==c])}
                          for c in companies]
        }
    }

@app.get("/api/kb")
def api_kb():
    kb = load_kb()
    companies = list(set([d.get("company","") for d in kb]))
    return {
        "totalAnnouncements": len(kb),
        "totalCompanies": len(companies),
        "companies": [{"name": c, "code": "", "count": len([d for d in kb if d.get("company")==c])}
                      for c in companies]
    }