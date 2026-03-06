import streamlit as st
import anthropic
import PyPDF2
import io
import json
import os
import requests

st.set_page_config(
    page_title="FinInsight · AI投研助手",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

#MainMenu, footer, header { visibility: hidden; }

.stApp {
    background: #f4f4f5;
}

/* ===== 左栏 ===== */
section[data-testid="column"]:first-child {
    background: #ffffff;
    border-right: 1px solid #e4e4e7;
    min-height: 100vh;
    padding: 0 !important;
}

section[data-testid="column"]:last-child {
    background: #f4f4f5;
    min-height: 100vh;
}

/* ===== 输入框 ===== */
.stTextInput input {
    background: #f9f9f9 !important;
    border: 1px solid #e4e4e7 !important;
    border-radius: 8px !important;
    padding: 10px 14px !important;
    font-size: 14px !important;
    color: #18181b !important;
    transition: all 0.15s ease !important;
    box-shadow: none !important;
}
.stTextInput input:focus {
    background: #fff !important;
    border-color: #18181b !important;
    box-shadow: 0 0 0 2px rgba(24,24,27,0.08) !important;
}
.stTextInput input::placeholder { color: #a1a1aa !important; }

/* ===== 셀렉트박스 ===== */
.stSelectbox > div > div {
    background: #f9f9f9 !important;
    border: 1px solid #e4e4e7 !important;
    border-radius: 8px !important;
    font-size: 14px !important;
    color: #18181b !important;
}

/* ===== 버튼 ===== */
.stButton > button {
    background: #18181b !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 11px 20px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    width: 100% !important;
    transition: all 0.15s ease !important;
    letter-spacing: 0.01em !important;
}
.stButton > button:hover {
    background: #27272a !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.12) !important;
}

.stDownloadButton > button {
    background: #fff !important;
    color: #18181b !important;
    border: 1px solid #e4e4e7 !important;
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    padding: 9px 16px !important;
    width: auto !important;
}
.stDownloadButton > button:hover {
    border-color: #18181b !important;
    background: #fafafa !important;
}

/* ===== Spinner ===== */
.stSpinner > div { border-top-color: #18181b !important; }

/* ===== Alert ===== */
.stAlert { border-radius: 8px !important; font-size: 13px !important; }

div[data-testid="stExpander"] {
    border: 1px solid #e4e4e7 !important;
    border-radius: 8px !important;
    background: #fafafa !important;
}
</style>
""", unsafe_allow_html=True)

# ===== API =====
api_key = None
try:
    with open(".env", "r") as f:
        for line in f:
            if "ANTHROPIC_API_KEY" in line:
                api_key = line.strip().split("=")[1]
except:
    pass

if not api_key:
    st.error("请在 .env 文件中填入你的 ANTHROPIC_API_KEY")
    st.stop()

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

# ===== AI 행업 판단 =====
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
        result = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(result)
        return data.get("industry", ""), data.get("peers", [])
    except:
        return "", []

# ===== 巨潮 =====
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
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                     "Content-Type": "application/x-www-form-urlencoded",
                     "Referer": "http://www.cninfo.com.cn",
                     "Origin": "http://www.cninfo.com.cn"}, timeout=10
        )
        return [{"title": i.get("announcementTitle",""),
                 "date": str(i.get("announcementTime",""))[:10],
                 "url": "http://static.cninfo.com.cn/" + i.get("adjunctUrl","")}
                for i in (res.json().get("announcements") or [])]
    except Exception as e:
        st.error(f"公告列表获取失败：{e}")
        return []

def fetch_announcement_text(pdf_url):
    try:
        res = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "http://www.cninfo.com.cn"}, timeout=15)
        reader = PyPDF2.PdfReader(io.BytesIO(res.content))
        return "".join(p.extract_text() or "" for p in reader.pages[:10])
    except:
        return ""

def auto_build_kb(company_name, stock_code, org_id, industry, peers, status_el):
    added = 0
    status_el.markdown(render_step("构建知识库：抓取历史公告"), unsafe_allow_html=True)
    for ann in fetch_announcement_list(stock_code, org_id, page_size=6)[1:6]:
        text = fetch_announcement_text(ann["url"])
        if text and add_to_kb(f"{company_name}_{ann['date']}_{ann['title'][:20]}", text, company_name, industry):
            added += 1
    if peers:
        status_el.markdown(render_step("构建知识库：抓取同行业公告"), unsafe_allow_html=True)
        for peer_name in peers[:2]:
            stocks = search_stock_code(peer_name)
            if stocks:
                p = stocks[0]
                for ann in fetch_announcement_list(p["code"], p["orgId"], page_size=2)[:2]:
                    text = fetch_announcement_text(ann["url"])
                    if text and add_to_kb(f"{p['name']}_{ann['date']}_{ann['title'][:20]}", text, p["name"], industry):
                        added += 1
    return added

def analyze_announcement(text, similar_docs, company_name, industry):
    context = ""
    if similar_docs:
        context = "\n\n【知识库召回的参考案例】\n"
        for doc in similar_docs:
            label = "同公司历史" if doc.get("company") == company_name else f"同行业({doc.get('company','')})"
            context += f"\n▸ [{label}] {doc['name'][:30]}\n{doc['text'][:100]}...\n"

    prompt = f"""你是一位资深A股投研分析师，请对以下公告进行分析。
{"以下是知识库中召回的历史参考案例，请结合这些案例对当前公告进行对比分析。" if similar_docs else ""}

【当前公告】
公司：{company_name}{"（" + industry + "行业）" if industry else ""}
{text[:3000]}
{context}

请严格按照以下格式输出，总字数控制在250字以内：

## ⚡ 30秒速读

**【一句话事件】**
（谁、做了什么、关键数字）

**【影响判断】** 🔴负面 / 🟡中性 / 🟢正面（选一个）
（一句话理由，不超过20字）

**【你需要做的】**
持仓者：（一句话行动建议）
未持仓者：（一句话行动建议）

**【最需要关注的风险】**
（一句话，不超过30字）

{"**【历史对比】**" if similar_docs else ""}
{"（分两点：①与该公司历史公告相比有何变化；②与同行业可比公司相比表现如何。每点一句话）" if similar_docs else ""}

---
**关键数据**
（3-5条核心数字，每条不超过15字）
"""
    message = client.messages.create(
        model="claude-3-5-haiku-20241022", max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

# ===== UI 헬퍼 =====
def render_step(label):
    return f"""
    <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;
                background:#fff;border:1px solid #e4e4e7;border-radius:8px;margin-bottom:8px">
        <div style="width:8px;height:8px;border-radius:50%;background:#18181b;
                    animation:pulse 1s infinite"></div>
        <span style="font-size:13px;color:#3f3f46">{label}</span>
    </div>
    <style>@keyframes pulse {{0%,100%{{opacity:1}}50%{{opacity:0.3}}}}</style>
    """

def render_tag(text, color="#18181b", bg="#f4f4f5", border="#e4e4e7"):
    return f"""<span style="display:inline-flex;align-items:center;padding:3px 10px;
               border-radius:20px;font-size:12px;font-weight:500;color:{color};
               background:{bg};border:1px solid {border};margin:2px">{text}</span>"""

# ===== 레이아웃 =====
col1, col2 = st.columns([4, 6], gap="small")

with col1:
    # 로고
    st.markdown("""
    <div style="padding:24px 24px 0">
        <div style="font-size:18px;font-weight:700;color:#18181b;letter-spacing:-0.3px">
            Fin<span style="color:#71717a">Insight</span>
        </div>
        <div style="font-size:11px;color:#a1a1aa;letter-spacing:1.5px;
                    text-transform:uppercase;margin-top:2px">AI 投研公告分析</div>
    </div>
    <hr style="border:none;border-top:1px solid #e4e4e7;margin:16px 0">
    """, unsafe_allow_html=True)

    with st.container():
        st.markdown('<div style="padding:0 24px">', unsafe_allow_html=True)

        st.markdown('<p style="font-size:11px;font-weight:600;color:#a1a1aa;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px">搜索标的</p>', unsafe_allow_html=True)
        keyword = st.text_input("search", placeholder="股票代码或公司名，如：600036", label_visibility="collapsed")

        selected_stock = None
        announcements = []
        selected_ann = None

        if keyword:
            with st.spinner(""):
                stocks = search_stock_code(keyword)
            if not stocks:
                st.warning("未找到相关公司")
            else:
                stock_options = {f"{s['name']}（{s['code']}）": s for s in stocks}
                st.markdown('<p style="font-size:11px;font-weight:600;color:#a1a1aa;letter-spacing:1px;text-transform:uppercase;margin:14px 0 6px">选择公司</p>', unsafe_allow_html=True)
                sel_name = st.selectbox("公司", list(stock_options.keys()), label_visibility="collapsed")
                selected_stock = stock_options[sel_name]

                with st.spinner(""):
                    announcements = fetch_announcement_list(selected_stock["code"], selected_stock["orgId"])

                if not announcements:
                    st.warning("暂未获取到公告")
                else:
                    ann_options = {a["title"]: a for a in announcements}
                    st.markdown('<p style="font-size:11px;font-weight:600;color:#a1a1aa;letter-spacing:1px;text-transform:uppercase;margin:14px 0 6px">选择公告</p>', unsafe_allow_html=True)
                    sel_ann_name = st.selectbox("公告", list(ann_options.keys()), label_visibility="collapsed")
                    selected_ann = ann_options[sel_ann_name]

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<hr style="border:none;border-top:1px solid #e4e4e7;margin:20px 0">', unsafe_allow_html=True)

    with st.container():
        st.markdown('<div style="padding:0 24px">', unsafe_allow_html=True)
        if selected_stock and selected_ann:
            analyze_btn = st.button("开始分析 →", type="primary", use_container_width=True)
        else:
            analyze_btn = False
        st.markdown("</div>", unsafe_allow_html=True)

    # 知识库 상태
    kb = load_kb()
    companies = list(set([d.get("company","") for d in kb]))
    st.markdown(f"""
    <div style="position:fixed;bottom:0;width:inherit;padding:20px 24px;
                background:#fff;border-top:1px solid #e4e4e7">
        <p style="font-size:11px;font-weight:600;color:#a1a1aa;letter-spacing:1px;
                  text-transform:uppercase;margin-bottom:10px">知识库</p>
        <div style="display:flex;gap:24px">
            <div>
                <div style="font-size:22px;font-weight:700;color:#18181b;line-height:1">{len(kb)}</div>
                <div style="font-size:11px;color:#a1a1aa;margin-top:3px">已存储公告</div>
            </div>
            <div>
                <div style="font-size:22px;font-weight:700;color:#18181b;line-height:1">{len(companies)}</div>
                <div style="font-size:11px;color:#a1a1aa;margin-top:3px">覆盖公司</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown('<div style="padding:24px">', unsafe_allow_html=True)

    if keyword and announcements and selected_stock and selected_ann and analyze_btn:
        status = st.empty()

        # 1. 공고 읽기
        status.markdown(render_step("读取公告全文..."), unsafe_allow_html=True)
        ann_text = fetch_announcement_text(selected_ann["url"])

        if not ann_text.strip():
            status.empty()
            st.error("公告内容获取失败，请换一篇试试")
        else:
            # 2. 행업 판단
            status.markdown(render_step("AI 识别行业及可比标的..."), unsafe_allow_html=True)
            industry, peers = get_industry_peers(selected_stock["name"], ann_text)

            # 3. 知识库 구축
            added = auto_build_kb(selected_stock["name"], selected_stock["code"],
                                  selected_stock["orgId"], industry, peers, status)

            # 4. 유사 案例 검색
            status.markdown(render_step("检索历史相似案例..."), unsafe_allow_html=True)
            similar_docs = search_similar(ann_text, selected_stock["name"], industry)

            # 5. AI 분석
            status.markdown(render_step("AI 生成分析报告..."), unsafe_allow_html=True)
            result = analyze_announcement(ann_text, similar_docs, selected_stock["name"], industry)

            status.empty()

            # 존入知识库
            add_to_kb(
                f"{selected_stock['name']}_{selected_ann['date']}_{sel_ann_name[:20]}",
                ann_text, selected_stock["name"], industry
            )

            # 헤더
            st.markdown(f"""
            <div style="margin-bottom:20px">
                <div style="font-size:11px;color:#a1a1aa;letter-spacing:1px;
                            text-transform:uppercase;margin-bottom:6px">分析报告</div>
                <div style="font-size:20px;font-weight:700;color:#18181b;letter-spacing:-0.3px">
                    {selected_stock['name']}
                </div>
                <div style="font-size:13px;color:#71717a;margin-top:4px">{sel_ann_name[:50]}...</div>
            </div>
            """, unsafe_allow_html=True)

            # 태그
            tags_html = ""
            if industry:
                tags_html += render_tag(f"🏭 {industry}", "#15803d", "#f0fdf4", "#bbf7d0")
            for peer in peers:
                tags_html += render_tag(f"对比 {peer}", "#1d4ed8", "#eff6ff", "#bfdbfe")
            if tags_html:
                st.markdown(f'<div style="margin-bottom:16px">{tags_html}</div>', unsafe_allow_html=True)

            # 召回 패널
            if similar_docs:
                recall_html = ""
                for d in similar_docs:
                    is_same = d.get("company") == selected_stock["name"]
                    icon = "📁" if is_same else "🔗"
                    recall_html += render_tag(
                        f"{icon} {d.get('company','')}",
                        "#6d28d9" if is_same else "#1d4ed8",
                        "#faf5ff" if is_same else "#eff6ff",
                        "#e9d5ff" if is_same else "#bfdbfe"
                    )
                st.markdown(f"""
                <div style="background:#fafafa;border:1px solid #e4e4e7;border-radius:10px;
                            padding:14px 16px;margin-bottom:20px">
                    <div style="font-size:11px;font-weight:600;color:#a1a1aa;letter-spacing:1px;
                                text-transform:uppercase;margin-bottom:10px">
                        召回 {len(similar_docs)} 个参考案例
                    </div>
                    {recall_html}
                </div>
                """, unsafe_allow_html=True)

            # 결과 카드
            st.markdown("""
            <div style="background:#fff;border:1px solid #e4e4e7;border-radius:12px;padding:24px">
            """, unsafe_allow_html=True)
            st.markdown(result)
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button(
                "⬇ 下载分析报告",
                data=f"# {selected_stock['name']} 公告分析\n\n{result}",
                file_name=f"投研报告_{selected_stock['name']}.md",
                mime="text/markdown"
            )

    else:
        # 빈 상태
        st.markdown("""
        <div style="height:70vh;display:flex;flex-direction:column;
                    align-items:center;justify-content:center;text-align:center">
            <div style="width:56px;height:56px;background:#f4f4f5;border:1px solid #e4e4e7;
                        border-radius:14px;display:flex;align-items:center;justify-content:center;
                        font-size:24px;margin-bottom:20px">📊</div>
            <div style="font-size:16px;font-weight:600;color:#18181b;margin-bottom:8px">
                选择公告，开始分析
            </div>
            <div style="font-size:13px;color:#a1a1aa;line-height:1.7;max-width:280px">
                在左侧输入股票代码或公司名<br>
                选择公告后点击「开始分析」<br><br>
                <span style="font-size:12px;color:#d4d4d8">
                    支持沪深A股全部上市公司<br>数据来源：巨潮资讯
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)