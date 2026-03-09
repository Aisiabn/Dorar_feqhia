"""
explore.py
----------
يتصفح فهرس الموسوعة الفقهية من dorar.net/feqhia
ويبني شجرة هرمية كاملة مع حفظها في data/toc.json
"""

import json
import time
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dorar.net"
TOC_URL  = f"{BASE_URL}/feqhia"
OUT_PATH = Path(__file__).parent.parent / "data" / "toc.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DorarResearch/1.0)",
    "Accept-Language": "ar,en;q=0.9",
}

# مستويات الهرم حسب عمق الـ ul في القائمة
LEVEL_NAMES = ["كتاب", "باب", "فصل", "مبحث", "مطلب", "فرع"]


# ─── هيكل البيانات ───────────────────────────────────────────────────────────

@dataclass
class Node:
    title: str
    url: Optional[str]          # None للعقد التي بدون رابط مباشر
    page_id: Optional[int]      # الرقم في /feqhia/{id}
    level: int                  # 0=كتاب، 1=باب، ...
    level_name: str
    children: list = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["children"] = [c.to_dict() for c in self.children]
        return d


# ─── الجلب والتحليل ──────────────────────────────────────────────────────────

def fetch(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    return BeautifulSoup(r.text, "html.parser")


def extract_id(href: str) -> Optional[int]:
    """استخرج الرقم من /feqhia/123"""
    m = re.search(r"/feqhia/(\d+)", href or "")
    return int(m.group(1)) if m else None


def parse_li(li_tag, depth: int) -> Node:
    """
    حوّل عنصر <li> إلى Node مع أبنائه.
    المنطق:
      - أول <a> مباشر = العنوان والرابط
      - أول <ul> داخلي = الأبناء (بشكل تكراري)
    """
    # ── العنوان والرابط ──
    a = li_tag.find("a", recursive=False)
    if not a:
        # بعض العناصر لها span بدل a
        a = li_tag.find(["a", "span"], recursive=False)

    title = a.get_text(strip=True) if a else "—"
    href  = a.get("href") if a and a.name == "a" else None
    url   = (BASE_URL + href) if href and href.startswith("/") else href
    pid   = extract_id(href)

    level_name = LEVEL_NAMES[depth] if depth < len(LEVEL_NAMES) else f"مستوى-{depth}"
    node = Node(title=title, url=url, page_id=pid, level=depth, level_name=level_name)

    # ── الأبناء ──
    child_ul = li_tag.find("ul", recursive=False)
    if child_ul:
        for child_li in child_ul.find_all("li", recursive=False):
            node.children.append(parse_li(child_li, depth + 1))

    return node


def build_toc(soup: BeautifulSoup) -> list[Node]:
    """
    ابحث عن القائمة الجانبية الرئيسية (أعمق ul في nav أو sidebar)
    وابنِ منها شجرة الكتب.
    """
    # القائمة الرئيسية في الصفحة تبدأ بعناصر "كتاب ..."
    # نبحث عن كل li يحتوي نصه على "كتاب" كمستوى أعلى
    roots = []

    # الـ ul الرئيسية هي الأولى داخل div.panel أو قسم الفهرس
    # — نجرب عدة selectors ─
    container = (
        soup.select_one("ul.jq-accordion")          # قائمة accordion إن وُجدت
        or soup.select_one("div.faq-accordion ul")
        or soup.select_one("nav ul")
    )

    if container is None:
        # fallback: أي ul تحتوي مباشرةً على روابط /feqhia/
        all_uls = soup.find_all("ul")
        for ul in all_uls:
            links = ul.find_all("a", href=re.compile(r"^/feqhia/\d+"))
            if len(links) > 10:          # القائمة الحقيقية طويلة
                container = ul
                break

    if container is None:
        raise RuntimeError("لم أتمكن من إيجاد قائمة الفهرس في الصفحة")

    for li in container.find_all("li", recursive=False):
        roots.append(parse_li(li, depth=0))

    return roots


# ─── الإحصاء والطباعة ────────────────────────────────────────────────────────

def count_nodes(nodes: list) -> dict:
    counts = {name: 0 for name in LEVEL_NAMES}
    counts["إجمالي"] = 0

    def walk(node_list):
        for n in node_list:
            lname = n.level_name if n.level_name in counts else "فرع"
            counts[lname] = counts.get(lname, 0) + 1
            counts["إجمالي"] += 1
            walk(n.children)

    walk(nodes)
    return counts


def print_tree(nodes: list, indent: int = 0, max_depth: int = 2):
    """اطبع الشجرة بشكل مقروء حتى عمق معين"""
    for n in nodes:
        prefix = "  " * indent + ("📖 " if n.level == 0 else "• ")
        pid_str = f"  [id={n.page_id}]" if n.page_id else ""
        print(f"{prefix}{n.title}{pid_str}")
        if indent < max_depth:
            print_tree(n.children, indent + 1, max_depth)


# ─── الحفظ ───────────────────────────────────────────────────────────────────

def save_toc(nodes: list[Node]):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": TOC_URL,
        "total_books": len(nodes),
        "nodes": [n.to_dict() for n in nodes]
    }
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ تم الحفظ في: {OUT_PATH}")


# ─── نقطة الدخول ─────────────────────────────────────────────────────────────

def main():
    print(f"⏳ جاري جلب: {TOC_URL}")
    soup = fetch(TOC_URL)
    time.sleep(1)   # احترام للسيرفر

    print("🔍 تحليل الفهرس...")
    toc = build_toc(soup)

    print(f"\n📚 الهيكل (حتى مستوى 2):")
    print_tree(toc, max_depth=2)

    stats = count_nodes(toc)
    print("\n📊 إحصاء:")
    for k, v in stats.items():
        print(f"   {k}: {v}")

    save_toc(toc)


if __name__ == "__main__":
    main()
