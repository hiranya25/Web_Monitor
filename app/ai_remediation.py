import json
import logging
import os
import re
import time
import hashlib
from collections import Counter
from dataclasses import dataclass, replace
from difflib import get_close_matches
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

try:
    import httpx
    from openai import OpenAI
except ImportError:  # AI remediation gracefully falls back to deterministic fixes.
    httpx = None
    OpenAI = None

from app.config import settings
from app.models import Issue, PageRecord

logger = logging.getLogger("ai_remediation")

CACHE_FILE = os.path.join(settings.REPORTS_DIR, "remediation_cache.json")
# 30 days TTL (in seconds)
CACHE_TTL = 30 * 24 * 60 * 60

TITLE_MIN, TITLE_MAX = 50, 60
META_DESC_MIN, META_DESC_MAX = 120, 160

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "your", "our", "you",
    "are", "was", "were", "has", "have", "had", "not", "but", "about", "into",
    "more", "all", "can", "will", "www", "https", "http", "com", "html",
}


@dataclass
class PageContext:
    url: str
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    lang: str = ""
    h1s: list[str] = None
    h2s: list[str] = None
    top_terms: list[str] = None
    visible_text: str = ""
    images: list[dict] = None
    scripts: list[str] = None
    stylesheets: list[str] = None
    resource_counts: dict = None

    def __post_init__(self):
        self.h1s = self.h1s or []
        self.h2s = self.h2s or []
        self.top_terms = self.top_terms or []
        self.images = self.images or []
        self.scripts = self.scripts or []
        self.stylesheets = self.stylesheets or []
        self.resource_counts = self.resource_counts or {}


def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
            now = time.time()
            return {k: v for k, v in cache.items() if (now - v.get("ts", 0)) < CACHE_TTL}
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as exc:
        logger.warning("Failed to save remediation cache: %s", exc)


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


def _clean_text(text: str, max_len: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:max_len].rstrip()


def _site_name(url: str) -> str:
    host = urlparse(url or settings.SITE_BASE_URL).netloc.replace("www.", "")
    name = host.split(".")[0] if host else "Website"
    return name.upper() if len(name) <= 6 else name.title()


def _canonical_for(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _clean_canonical_for(url: str, lowercase_path: bool = False) -> str:
    parsed = urlparse(_canonical_for(url))
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if lowercase_path:
        path = path.lower()
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _humanize_path(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return "Homepage"
    last = re.sub(r"[-_]+", " ", parts[-1])
    return last.replace(".html", "").replace(".php", "").title()


def _sentence_from_context(ctx: PageContext) -> str:
    candidates = []
    candidates.extend(ctx.h1s[:1])
    candidates.extend(ctx.h2s[:2])
    if ctx.title:
        candidates.append(ctx.title)
    if ctx.top_terms:
        candidates.append(" ".join(ctx.top_terms[:4]))
    candidates.append(_humanize_path(ctx.url))
    return _clean_text(" - ".join(dict.fromkeys([c for c in candidates if c])), 180)


def _extract_context(page: Optional[PageRecord], fallback_url: str) -> PageContext:
    if not page or not page.html:
        return PageContext(url=fallback_url)

    soup = BeautifulSoup(page.html, "lxml")
    title_tag = soup.find("title")
    meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    canonical = soup.find("link", attrs={"rel": "canonical"})
    html_tag = soup.find("html")

    title = _clean_text(title_tag.get_text(" ", strip=True) if title_tag else "", 180)
    desc = _clean_text(meta_desc.get("content", "") if meta_desc else "", 240)
    canonical_href = canonical.get("href", "").strip() if canonical else ""
    lang = html_tag.get("lang", "").strip() if html_tag else ""
    h1s = [_clean_text(h.get_text(" ", strip=True), 120) for h in soup.find_all("h1")]
    h2s = [_clean_text(h.get_text(" ", strip=True), 120) for h in soup.find_all("h2")]

    images = []
    for img in soup.find_all("img")[:80]:
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if not src:
            continue
        parent_text = _clean_text(img.parent.get_text(" ", strip=True) if img.parent else "", 120)
        images.append({
            "src": src,
            "abs_src": urljoin(page.url, src),
            "alt": img.get("alt", "").strip(),
            "title": img.get("title", "").strip(),
            "nearby_text": parent_text,
            "width": img.get("width", ""),
            "height": img.get("height", ""),
        })

    scripts = []
    blocking_scripts = []
    for script in soup.find_all("script", src=True):
        src = script.get("src", "").strip()
        scripts.append(src)
        if src and not script.get("async") and not script.get("defer"):
            blocking_scripts.append(src)

    stylesheets = [link.get("href", "").strip() for link in soup.find_all("link", rel="stylesheet", href=True)]

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.extract()
    visible_text = _clean_text(soup.get_text(" ", strip=True), 900)
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9'-]{2,}\b", visible_text.lower())
    filtered = [w for w in words if w not in STOP_WORDS]
    top_terms = [term for term, _ in Counter(filtered).most_common(8)]

    resources = page.resources or []
    counts = {
        "scripts": len(scripts),
        "blocking_scripts": len(blocking_scripts),
        "stylesheets": len(stylesheets),
        "images": len(images),
        "fonts": sum(1 for r in resources if r.get("type") == "font"),
        "total": len(resources) if resources else len(scripts) + len(stylesheets) + len(images),
    }

    return PageContext(
        url=page.url,
        title=title,
        meta_description=desc,
        canonical=canonical_href,
        lang=lang,
        h1s=[h for h in h1s if h],
        h2s=[h for h in h2s if h],
        top_terms=top_terms,
        visible_text=visible_text,
        images=images,
        scripts=scripts,
        stylesheets=stylesheets,
        resource_counts=counts,
    )


def _build_page_index(pages: Optional[list[PageRecord]]) -> tuple[dict[str, PageRecord], list[str]]:
    index = {}
    urls = []
    for page in pages or []:
        if not page.url:
            continue
        key = _normalize_url(page.url)
        index.setdefault(key, page)
        urls.append(page.url)
    return index, urls


def _page_for_issue(issue: Issue, pages_by_url: dict[str, PageRecord]) -> Optional[PageRecord]:
    return pages_by_url.get(_normalize_url(issue.page_url))


def _compose_title(ctx: PageContext, issue: Issue) -> str:
    brand = _site_name(ctx.url or issue.page_url)
    primary = ""
    if ctx.h1s:
        primary = ctx.h1s[0]
    elif ctx.h2s:
        primary = ctx.h2s[0]
    elif ctx.top_terms:
        primary = " ".join(ctx.top_terms[:4]).title()
    else:
        primary = _humanize_path(ctx.url or issue.page_url)

    primary = re.sub(r"\s+", " ", primary).strip(" |-")
    title = primary
    if brand.lower() not in title.lower():
        title = f"{primary} | {brand}"

    if len(title) > TITLE_MAX:
        shortened = primary[: max(20, TITLE_MAX - len(brand) - 3)].rsplit(" ", 1)[0]
        title = f"{shortened} | {brand}" if shortened else f"{_humanize_path(ctx.url)} | {brand}"
    if len(title) < TITLE_MIN and ctx.top_terms:
        extra = " ".join(t.title() for t in ctx.top_terms[:3] if t.lower() not in title.lower())
        candidate = f"{primary} {extra} | {brand}".strip()
        if len(candidate) <= TITLE_MAX + 8:
            title = candidate
    return _clean_text(title, 70)


def _compose_meta_description(ctx: PageContext, issue: Issue) -> str:
    brand = _site_name(ctx.url or issue.page_url)
    subject = ctx.h1s[0] if ctx.h1s else (ctx.title or _humanize_path(ctx.url or issue.page_url))
    text = ctx.visible_text
    if text:
        first_sentence = re.split(r"(?<=[.!?])\s+", text)[0]
        if 80 <= len(first_sentence) <= 180:
            candidate = first_sentence
        else:
            candidate = f"Explore {subject} from {brand}, including key services, product information, and helpful details for visitors."
    elif ctx.top_terms:
        candidate = f"Explore {subject} from {brand}, including {', '.join(ctx.top_terms[:3])} insights and practical information for visitors."
    else:
        candidate = f"Explore {subject} from {brand}. Find relevant information, services, and next steps for this page."

    candidate = _clean_text(candidate.replace(" ,", ","), 180)
    if len(candidate) < META_DESC_MIN:
        candidate = _clean_text(f"{candidate} Learn what this page offers and continue to the most relevant next step.", 180)
    if len(candidate) > META_DESC_MAX:
        candidate = candidate[:META_DESC_MAX].rsplit(" ", 1)[0].rstrip(".,;:")
    return candidate


def _filename_words(src: str) -> str:
    path = urlparse(src).path or src
    name = os.path.basename(path).split("?")[0]
    name = re.sub(r"\.(png|jpe?g|webp|gif|svg|avif)$", "", name, flags=re.I)
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"\b\d{2,}\b", "", name)
    return _clean_text(name, 80)


def _find_image(ctx: PageContext, issue: Issue) -> Optional[dict]:
    target = (issue.details or issue.message or "").strip()
    if target:
        for img in ctx.images:
            if target in img.get("src", "") or target in img.get("abs_src", ""):
                return img
    return next((img for img in ctx.images if not img.get("alt")), None)


def _compose_alt_text(ctx: PageContext, issue: Issue, img: Optional[dict]) -> str:
    source = img.get("src", "") if img else (issue.details or "")
    nearby = img.get("nearby_text", "") if img else ""
    filename = _filename_words(source)
    page_subject = ctx.h1s[0] if ctx.h1s else (ctx.title or _humanize_path(ctx.url or issue.page_url))
    pieces = [nearby, filename, page_subject]
    text = next((p for p in pieces if p and len(p) >= 8), page_subject)
    text = re.sub(r"\b(image|photo|banner|img)\b", "", text, flags=re.I)
    text = _clean_text(text, 105).strip(" -_|")
    if not text:
        text = f"{page_subject} visual"
    return text[0].upper() + text[1:]


def _extract_target_url(issue: Issue) -> str:
    source = " ".join([issue.details or "", issue.message or ""])
    match = re.search(r"(https?://[^\s)]+|/[A-Za-z0-9_\-./?=&%]+)", source)
    if match:
        return match.group(1).rstrip(".,")
    return issue.page_url


def _closest_internal_url(target: str, known_urls: list[str]) -> Optional[str]:
    if not target or not known_urls:
        return None
    parsed = urlparse(target)
    target_path = parsed.path or target
    paths = {urlparse(u).path or "/": u for u in known_urls}
    match = get_close_matches(target_path, list(paths.keys()), n=1, cutoff=0.55)
    return paths[match[0]] if match else None


def _format_kb(bytes_value: int) -> str:
    if bytes_value >= 1024 * 1024:
        return f"{bytes_value / 1024 / 1024:.2f} MB"
    return f"{bytes_value / 1024:.0f} KB"


def _resources_by_type(page: Optional[PageRecord], resource_type: str, limit: int = 4) -> list[dict]:
    if not page or not page.resources:
        return []
    rows = [r for r in page.resources if r.get("type") == resource_type]
    return sorted(rows, key=lambda r: r.get("size_bytes", 0), reverse=True)[:limit]


def _security_header_fix(issue: Issue) -> str:
    missing = (issue.message or "").split(":", 1)[-1].strip() or issue.details or "security headers"
    snippets = []
    if "HSTS" in missing:
        snippets.append('Strict-Transport-Security: max-age=31536000; includeSubDomains; preload')
    if "X-Content-Type-Options" in missing:
        snippets.append("X-Content-Type-Options: nosniff")
    if "X-Frame-Options" in missing or "frame-ancestors" in missing:
        snippets.append("Content-Security-Policy: frame-ancestors 'self'")
    snippet_text = "; ".join(snippets) if snippets else "add the missing header(s) listed in the finding"
    return (
        f"On {issue.page_url}, the response is missing: {missing}. This weakens protection against clickjacking, MIME-sniffing, or HTTPS downgrade attacks. "
        f"Configure the web server/CDN to return: {snippet_text}."
    )


def _structured_data_fix(ctx: PageContext, issue: Issue) -> str:
    brand = _site_name(ctx.url or issue.page_url)
    page_name = ctx.h1s[0] if ctx.h1s else (ctx.title or _humanize_path(ctx.url or issue.page_url))
    schema_type = "Organization" if _normalize_url(issue.page_url) == _normalize_url(settings.SITE_BASE_URL) else "WebPage"
    return (
        f"{issue.page_url} has no recognized JSON-LD structured data. Add {schema_type} schema tied to this page, for example "
        f'{{"@context":"https://schema.org","@type":"{schema_type}","name":"{page_name}","url":"{_canonical_for(issue.page_url)}","publisher":{{"@type":"Organization","name":"{brand}"}}}}. '
        "This gives search engines and AI crawlers an explicit entity/page relationship instead of relying only on visible text."
    )


def _deterministic_fix(issue: Issue, ctx: PageContext, page: Optional[PageRecord], known_urls: list[str]) -> Optional[str]:
    url = issue.page_url
    issue_type = issue.issue_type

    if issue_type == "missing_title":
        title = _compose_title(ctx, issue)
        return (
            f"{url} currently has no <title> tag. Recommended title ({len(title)} characters): \"{title}\". "
            "This gives the page a specific search result headline based on its content and keeps the title close to the recommended display length."
        )

    if issue_type == "title_length_incorrect":
        current = issue.details or ctx.title or "Data Not Available"
        title = _compose_title(ctx, issue)
        return (
            f"Current title on {url}: \"{current}\" ({len(current)} characters). Recommended replacement ({len(title)} characters): \"{title}\". "
            "The replacement keeps the page topic and brand visible while moving the title closer to the 50-60 character range used in the audit."
        )

    if issue_type == "missing_meta_description":
        desc = _compose_meta_description(ctx, issue)
        return (
            f"{url} currently has no meta description. Recommended meta description ({len(desc)} characters): \"{desc}\". "
            "This summary is based on the page content and gives search/social snippets a specific value proposition instead of leaving the snippet to be auto-generated."
        )

    if issue_type == "meta_desc_length":
        current = ctx.meta_description or "Data Not Available"
        desc = _compose_meta_description(ctx, issue)
        return (
            f"Current meta description on {url}: \"{current}\" ({len(current) if current != 'Data Not Available' else 'Data Not Available'} characters). "
            f"Recommended replacement ({len(desc)} characters): \"{desc}\". This keeps the description near the 120-160 character target and aligns it with the actual page copy."
        )

    if issue_type in {"missing_canonical_tag", "repeated_slashes", "uppercase_url"}:
        canonical = _clean_canonical_for(url, lowercase_path=(issue_type == "uppercase_url"))
        return (
            f"{url} does not expose a clean preferred URL for search engines. Add or update the canonical tag to: <link rel=\"canonical\" href=\"{canonical}\">. "
            "This consolidates ranking signals and prevents duplicate URL variants from competing with this page."
        )

    if issue_type in {"missing_lang_attribute", "missing_lang_attr"}:
        return (
            f"{url} is missing the document language declaration. Current value: no lang attribute detected. "
            "Set the root element to <html lang=\"en\">, or replace \"en\" with the actual primary page language. This improves accessibility pronunciation and search engine language interpretation."
        )

    if issue_type == "missing_h1_tag":
        h1 = ctx.title or _compose_title(ctx, issue).split("|")[0].strip()
        return (
            f"{url} currently has no H1. Recommended H1: \"{h1}\". "
            "This gives users and crawlers one clear primary heading that matches the page topic instead of forcing them to infer the subject from smaller headings or navigation."
        )

    if issue_type == "multiple_h1_tags":
        current = "; ".join(ctx.h1s[:5]) if ctx.h1s else "Data Not Available"
        keep = ctx.h1s[0] if ctx.h1s else _compose_title(ctx, issue).split("|")[0].strip()
        return (
            f"{url} has multiple H1 tags. Current H1s: {current}. Keep one H1 as \"{keep}\" and change the remaining H1 elements to H2/H3 headings. "
            "This preserves the visual hierarchy while giving search engines a single primary topic for the page."
        )

    if issue_type == "missing_alt_attribute":
        img = _find_image(ctx, issue)
        src = img.get("src") if img else (issue.details or "Data Not Available")
        alt = _compose_alt_text(ctx, issue, img)
        return (
            f"Image missing ALT text on {url}: {src}. Recommended ALT text: \"{alt}\". "
            "This describes the specific image using nearby page context and filename signals, improving accessibility and image search relevance."
        )

    if issue_type == "all_images_missing_alt":
        samples = [img for img in ctx.images if not img.get("alt")][:3]
        sample_text = "; ".join(f"{img['src']} -> \"{_compose_alt_text(ctx, issue, img)}\"" for img in samples) or "Data Not Available"
        return (
            f"Every image detected on {url} is missing ALT text. Current value: blank ALT attributes across {len(ctx.images) or 'Data Not Available'} images. "
            f"Start with these replacements: {sample_text}. Use descriptive ALT text for meaningful images and alt=\"\" only for decorative assets."
        )

    if issue_type in {"broken_internal_link", "broken_external_link", "external_link_blocked", "redirect_chain", "access_denied", "blocked_by_robots_txt"}:
        target = _extract_target_url(issue)
        suggestion = ""
        if issue_type == "broken_internal_link":
            close = _closest_internal_url(target, known_urls)
            if close and close != target:
                suggestion = f" Replace the broken destination with {close}, or add a 301 redirect from {target} to that live URL."
            else:
                suggestion = f" Update the link to a live internal URL or create a 301 redirect for {target}."
        elif issue_type == "broken_external_link":
            suggestion = " Replace it with the current external destination, cite an alternative authoritative source, or remove the link if it is no longer needed."
        elif issue_type == "external_link_blocked":
            suggestion = " Because the target blocks automated checks, manually verify it in a browser; if it is not essential, replace it with a stable source that returns 200 for normal crawlers."
        elif issue_type == "blocked_by_robots_txt":
            suggestion = f" If {url} should be audited or indexed, update robots.txt to allow this path; otherwise remove it from crawl targets and XML sitemaps."
        elif issue_type == "access_denied":
            suggestion = " Confirm whether this page should be public. If yes, remove the access restriction; if no, exclude it from the sitemap and internal SEO crawl paths."
        else:
            suggestion = " Replace redirecting links with the final destination URL to reduce crawl waste and latency."
        return f"Problem detected on {url}: {issue.message}. Current target/value: {target}. {suggestion}"

    if issue_type in {"slow_response_time", "large_payload_size", "high_resource_count", "render_blocking_scripts"}:
        if issue_type == "slow_response_time":
            current = issue.message.replace(":", ": ")
            return (
                f"{url} is slow at crawl time. Current value: {current}. Cache the generated HTML for this page, reduce backend/database work for its route, and serve static assets through the CDN. "
                "The immediate target is under 1000ms response time, with critical pages ideally below 500ms."
            )
        if issue_type == "large_payload_size":
            current = issue.message.split(":", 1)[-1].strip()
            images = _resources_by_type(page, "image", 3)
            largest = ", ".join(f"{r.get('url')} ({_format_kb(int(r.get('size_bytes', 0)))})" for r in images) or "largest image resources were not available"
            return (
                f"{url} has a large page payload. Current value: {current}. Prioritize compressing/resizing the largest assets: {largest}. "
                "Convert hero and product images to WebP/AVIF, lazy-load below-the-fold media, and keep the full page transfer closer to 2 MB or less."
            )
        if issue_type == "render_blocking_scripts":
            blocking = []
            if page and page.html:
                soup = BeautifulSoup(page.html, "lxml")
                blocking = [s.get("src") for s in soup.find_all("script", src=True) if not s.get("async") and not s.get("defer")]
            sample = ", ".join(blocking[:4]) if blocking else "Data Not Available"
            return (
                f"{url} has render-blocking scripts. Current value: {issue.message}. Add defer to non-critical scripts such as {sample}, and keep only scripts required for first paint synchronous. "
                "This reduces parser blocking and improves first render/LCP timing."
            )
        counts = ctx.resource_counts
        return (
            f"{url} has too many page resources. Current value: {issue.message}; detected breakdown: {counts.get('scripts', 0)} scripts, {counts.get('stylesheets', 0)} stylesheets, {counts.get('images', 0)} images. "
            "Bundle or remove duplicate JS/CSS, lazy-load below-the-fold images, and defer non-critical third-party scripts on this page."
        )

    if issue_type in {"broken_resource", "large_third_party_script", "heavy_js_payload", "heavy_image_payload"}:
        target = _extract_target_url(issue)
        if issue_type == "broken_resource":
            return (
                f"{url} requests a missing asset: {target}. Replace the reference with the correct asset URL, restore the missing file, or remove the tag if the asset is no longer used. "
                "A 404 asset wastes requests and can break visual layout, tracking, or interactive behavior."
            )
        if issue_type == "large_third_party_script":
            return (
                f"{url} loads a large third-party script: {target}. Current value: {issue.message}. Load it after consent or interaction where possible, add defer/async, and remove it from this page if it is not required for conversion tracking or functionality."
            )
        if issue_type == "heavy_js_payload":
            scripts = _resources_by_type(page, "script", 4)
            sample = ", ".join(f"{r.get('url')} ({_format_kb(int(r.get('size_bytes', 0)))})" for r in scripts) or "Data Not Available"
            return (
                f"{url} ships too much JavaScript. Current value: {issue.message}. Review the largest scripts first: {sample}. Remove unused libraries, split page-specific code, and defer non-critical bundles."
            )
        images = _resources_by_type(page, "image", 4)
        sample = ", ".join(f"{r.get('url')} ({_format_kb(int(r.get('size_bytes', 0)))})" for r in images) or "Data Not Available"
        return (
            f"{url} has a heavy image payload. Current value: {issue.message}. Optimize the largest images first: {sample}. Resize them to displayed dimensions, compress them, and serve WebP/AVIF with lazy loading below the fold."
        )

    if issue_type in {"missing_robots_txt", "missing_sitemap_xml", "sitemap_not_in_robots", "missing_llms_txt"}:
        if issue_type == "missing_robots_txt":
            robots = urljoin(url, "/robots.txt")
            sitemap = urljoin(url, "/sitemap.xml")
            return f"{robots} is missing or inaccessible. Create it with at least: User-agent: *; Allow: /; Sitemap: {sitemap}. This helps crawlers discover allowed sections and the XML sitemap."
        if issue_type == "missing_sitemap_xml":
            sitemap = urljoin(url, "/sitemap.xml")
            return f"{sitemap} is missing or inaccessible. Generate an XML sitemap containing the canonical crawlable URLs found in this audit and submit that exact URL in Search Console."
        if issue_type == "sitemap_not_in_robots":
            sitemap = urljoin(url, "/sitemap.xml")
            return f"{url} exists but does not declare the sitemap. Add this line to robots.txt: Sitemap: {sitemap}. This gives crawlers a direct route to the canonical URL inventory."
        llms = urljoin(url, "/llms.txt")
        return f"{llms} is missing. Create an llms.txt file summarizing the site, priority pages, products/services, and preferred citation context so AI crawlers can understand the business without relying only on rendered pages."

    if issue_type in {"missing_structured_data", "missing_entity_schema"}:
        return _structured_data_fix(ctx, issue)

    if issue_type in {"mixed_content", "mixed_content_refs"}:
        target = _extract_target_url(issue)
        return (
            f"{url} references insecure HTTP resources. Current detected value: {target if target != url else issue.details or issue.message}. "
            "Replace each http:// asset with its https:// equivalent or host it securely on the same CDN. Mixed content can be blocked by browsers and weakens HTTPS trust."
        )

    if issue_type == "missing_security_headers":
        return _security_header_fix(issue)

    if issue_type in {"missing_og_title", "missing_og_desc", "missing_twitter_card"}:
        title = ctx.title or _compose_title(ctx, issue)
        desc = ctx.meta_description or _compose_meta_description(ctx, issue)
        if issue_type == "missing_og_title":
            return f"{url} is missing og:title. Add <meta property=\"og:title\" content=\"{title}\"> so shared links use the page-specific title instead of a platform-generated fallback."
        if issue_type == "missing_og_desc":
            return f"{url} is missing og:description. Add <meta property=\"og:description\" content=\"{desc}\"> so social previews explain this page's value using the same page-specific message as search snippets."
        return f"{url} is missing Twitter/X card metadata. Add <meta name=\"twitter:card\" content=\"summary_large_image\"> plus twitter:title=\"{title}\" and twitter:description=\"{desc}\" so X displays a complete preview."

    if issue_type.startswith("missing_") and issue_type.endswith("_link") and issue.category == "Social":
        platform = issue.message.replace("Missing ", "").replace(" profile link on homepage", "")
        return (
            f"{url} does not expose a {platform} profile link in the scanned homepage markup. Add the verified {platform} profile URL in the header/footer near the existing contact or brand links. "
            "Use the real profile URL only; if the company does not maintain that profile, document it as intentionally unavailable instead of linking to an empty account."
        )

    if issue_type == "missing_fb_pixel":
        return (
            f"{url} has no Meta Pixel script detected. If Facebook/Instagram ads or retargeting are active, install the site-specific Meta Pixel ID through GTM or the page template and verify the fbq('track', 'PageView') event. "
            "If paid social is not used, mark this as intentionally not applicable rather than adding tracking unnecessarily."
        )

    if issue_type in {"missing_spf", "missing_dmarc"}:
        domain = urlparse(settings.SITE_BASE_URL).netloc.replace("www.", "")
        if issue_type == "missing_spf":
            return f"{domain} has no SPF TXT record detected. Add a domain-specific SPF record such as v=spf1 include:_spf.google.com ~all, replacing the include with the actual mail provider used by this business. This reduces spoofing risk for the audited domain."
        return f"_dmarc.{domain} has no DMARC TXT record detected. Add a record such as v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}, adjusting the mailbox and policy after confirming SPF/DKIM alignment."

    if issue_type in {"unnamed_links", "unlabeled_form_controls"}:
        if issue_type == "unnamed_links":
            return (
                f"{url} contains links without accessible names. Current value: {issue.message}. Add visible text or aria-label values that describe each destination, for example aria-label=\"View {_humanize_path(url)} details\" for icon-only links. "
                "This makes the exact link purpose available to screen readers."
            )
        return (
            f"{url} contains form controls without labels. Current value: {issue.message}. Add <label for=\"field-id\">Descriptive field name</label> or aria-label on each specific input, using the field purpose visible near that control. "
            "This prevents screen reader users from encountering unnamed fields."
        )

    if issue_type in {"thin_content", "missing_h2", "thin_static_content"}:
        subject = ctx.h1s[0] if ctx.h1s else (ctx.title or _humanize_path(url))
        terms = ", ".join(ctx.top_terms[:5]) if ctx.top_terms else "Data Not Available"
        if issue_type == "missing_h2":
            return f"{url} has no H2 subheadings. Add page-specific H2s such as \"{subject} Overview\", \"Key Benefits\", and \"Frequently Asked Questions\" based on the current content terms: {terms}."
        return (
            f"{url} has thin or hard-to-read static content. Current value: {issue.message}; prominent detected terms: {terms}. "
            f"Expand the page with specific copy about {subject}, include FAQs, and add internal links to related service/product pages so both users and non-rendering crawlers understand the page."
        )

    return None


def _generate_ai_fix(issue: Issue, ctx: PageContext) -> Optional[str]:
    if not settings.AI_API_KEY:
        return None
    if not OpenAI or not httpx:
        logger.warning("AI fix generation skipped because openai/httpx dependencies are unavailable.")
        return None

    client = OpenAI(
        base_url=settings.AI_API_BASE,
        api_key=settings.AI_API_KEY,
        http_client=httpx.Client(timeout=httpx.Timeout(60.0))
    )

    prompt = f"""You are an experienced technical SEO consultant.
Write a page-specific Suggested Fix for this detected website issue. Avoid generic advice.

Issue:
- Page URL: {issue.page_url}
- Category: {issue.category}
- Issue Type: {issue.issue_type}
- Severity: {issue.severity}
- Message: {issue.message}
- Details: {issue.details or "Data Not Available"}

Detected page context:
- Current title: {ctx.title or "Data Not Available"}
- Current meta description: {ctx.meta_description or "Data Not Available"}
- H1s: {", ".join(ctx.h1s[:5]) or "Data Not Available"}
- H2s: {", ".join(ctx.h2s[:5]) or "Data Not Available"}
- Top terms: {", ".join(ctx.top_terms[:8]) or "Data Not Available"}
- Sample text: {ctx.visible_text[:700] or "Data Not Available"}
- Images missing alt: {", ".join(img["src"] for img in ctx.images if not img.get("alt"))[:500] or "Data Not Available"}

The fix must mention the exact page, detected value, why it matters, and the exact replacement content whenever possible.
Return only the recommendation text. No markdown.
"""
    for attempt in range(3):
        try:
            completion = client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.25,
                max_tokens=420,
            )
            fix_text = completion.choices[0].message.content.strip()
            if fix_text.startswith('"') and fix_text.endswith('"'):
                fix_text = fix_text[1:-1]
            return fix_text
        except Exception as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                logger.error("AI fix generation failed for %s on %s: %s", issue.issue_type, issue.page_url, exc)
                return None


def _contextual_fallback(issue: Issue, ctx: PageContext) -> str:
    current = issue.details or issue.message or "Data Not Available"
    page_hint = _sentence_from_context(ctx) or _humanize_path(issue.page_url)
    existing = issue.how_to_fix
    if existing:
        return (
            f"On {issue.page_url}, the detected value is: {current}. {existing} "
            f"Apply this specifically to the {page_hint} page context, and verify the updated page no longer triggers {issue.issue_type}."
        )
    return (
        f"On {issue.page_url}, the detected value is: {current}. Review the affected element in the {page_hint} page context and replace it with a page-specific implementation. "
        "Exact replacement content is Data Not Available because the audit did not capture enough element-level context for this issue type."
    )


def _cache_key(issue: Issue, ctx: PageContext) -> str:
    payload = {
        "issue_type": issue.issue_type,
        "category": issue.category,
        "page_url": issue.page_url,
        "message": issue.message,
        "details": issue.details,
        "title": ctx.title,
        "meta": ctx.meta_description,
        "h1s": ctx.h1s[:3],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"personalized_{digest}"


def enrich_issues_with_remediation(
    issues: list[Issue],
    pages: Optional[list[PageRecord]] = None,
    lab_metrics: Optional[dict] = None,
    stats: Optional[dict] = None,
) -> list[Issue]:
    """Attach page-specific, issue-specific remediation text to each finding."""
    del lab_metrics, stats  # Reserved for Lighthouse/GTmetrix context without changing callers.

    cache = _load_cache()
    updated_cache = False
    pages_by_url, known_urls = _build_page_index(pages)
    context_cache: dict[str, PageContext] = {}
    enriched: list[Issue] = []
    total = len(issues)

    logger.info("Starting remediation enrichment for %d issues.", total)

    for idx, issue in enumerate(issues, start=1):
        if idx == 1 or idx % 250 == 0 or idx == total:
            logger.info("Remediation enrichment progress: %d/%d issues", idx, total)

        page = _page_for_issue(issue, pages_by_url)
        context_key = _normalize_url(page.url if page else issue.page_url)
        ctx = context_cache.get(context_key)
        if ctx is None:
            ctx = _extract_context(page, issue.page_url)
            context_cache[context_key] = ctx

        fix_text = _deterministic_fix(issue, ctx, page, known_urls)
        if not fix_text:
            key = _cache_key(issue, ctx)
            cached = cache.get(key)
            if cached:
                fix_text = cached["fix"]
                logger.debug("Cache hit for personalized remediation: %s", issue.issue_type)
            else:
                fix_text = _generate_ai_fix(issue, ctx)
                if fix_text:
                    cache[key] = {"fix": fix_text, "ts": time.time()}
                    updated_cache = True
                    logger.info("AI generated personalized fix for %s on %s", issue.issue_type, issue.page_url)

        if not fix_text:
            fix_text = _contextual_fallback(issue, ctx)
            logger.info("Using contextual fallback fix for %s on %s", issue.issue_type, issue.page_url)

        enriched.append(replace(issue, how_to_fix=fix_text))

    if updated_cache:
        _save_cache(cache)

    logger.info("Finished remediation enrichment for %d issues.", total)
    return enriched
