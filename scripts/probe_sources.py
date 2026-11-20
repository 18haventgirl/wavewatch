"""Read-only source feasibility probe. This is not a production collector."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 4 * 1024 * 1024


def inspect_content(source: dict, body: bytes) -> dict:
    mode = source["mode"]
    if mode == "cn_json":
        try:
            content = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Try legacy Chinese encoding without silently replacing invalid bytes.
            content = body.decode("gb18030")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return {"status": "invalid_content", "reason": "栏目 JSON 顶层不是对象"}
        page = payload.get("pageInfo")
        if str(payload.get("show")) != "1" or not isinstance(page, dict) or not isinstance(page.get("rows"), list):
            return {"status": "invalid_content", "reason": "栏目 JSON 格式或成功标志不符"}
        rows = page["rows"]
        if any(not isinstance(x, dict) or not x.get("title") or not x.get("url") for x in rows):
            return {"status": "invalid_content", "reason": "文章标题或链接缺失"}
        return {"status": "candidate_content" if rows else "needs_review", "items": len(rows), "reported_total": page.get("total"), "reported_pages": page.get("maxPageNum")}
    if mode == "json":
        payload = json.loads(body)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return {"status": "invalid_content", "reason": "JSON results 数组缺失"}
        items = payload["results"]
        if any(not isinstance(x, dict) or not x.get("title") or not x.get("document_number") for x in items):
            return {"status": "invalid_content", "reason": "法规记录缺少标题或文号"}
        return {"status": "candidate_content" if items else "needs_review", "items": len(items)}
    if mode == "rss":
        root = ET.fromstring(body)
        if root.tag not in ("rss", "{http://www.w3.org/2005/Atom}feed", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"):
            return {"status": "invalid_content", "reason": "非 RSS/Atom XML"}
        items = root.findall(".//item") + root.findall("{http://www.w3.org/2005/Atom}entry")
        valid = [x for x in items if x.findtext("title") or x.findtext("{http://www.w3.org/2005/Atom}title")]
        return {"status": "candidate_content" if valid else "needs_review", "items": len(valid)}
    soup = BeautifulSoup(body, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if any(s in (title + " " + text[:1000]).lower() for s in
           ("just a moment", "verify you are human", "access denied", "captcha", "please wait", "checking your browser")):
        return {"status": "challenge", "title": title, "reason": "疑似访问挑战页，未判定为成功"}
    if mode == "browser":
        return {"status": "needs_browser", "title": title, "visible_characters": len(text), "reason": "本探测不执行浏览器渲染，不能验证地图数据"}
    nodes = soup.select(source["selector"])
    selected = " ".join(n.get_text(" ", strip=True) for n in nodes)
    if len(nodes) < source.get("minimum_items", 1) or len(selected) < 30:
        return {"status": "invalid_content", "items": len(nodes), "title": title, "reason": "未发现预期内容区域或内容不足"}
    if any(term.lower() not in selected.lower() for term in source.get("required_text", [])):
        return {"status": "invalid_content", "title": title, "reason": "预期内容词缺失"}
    return {"status": "candidate_content", "items": len(nodes), "title": title, "visible_characters": len(selected)}


def probe(source: dict) -> dict:
    result = {"id": source["id"], "group": source["group"], "url": source["url"],
              "role": source["role"], "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        form_data = source.get("form_data")
        data = urllib.parse.urlencode(form_data).encode() if form_data else None
        request = urllib.request.Request(source.get("fetch_url", source["url"]), data=data, headers={"User-Agent": "ExportWatch-Feasibility/0.1", "Accept": "*/*"})
        with urllib.request.urlopen(request, timeout=25, context=ssl.create_default_context()) as response:
            body = response.read(MAX_BYTES + 1)
            result.update(http_status=response.status, final_url=response.url,
                          content_type=response.headers.get("Content-Type"), bytes=len(body))
        if len(body) > MAX_BYTES:
            return result | {"status": "size_limit", "reason": "响应超过探测大小上限"}
        result["sha256"] = hashlib.sha256(body).hexdigest()
        return result | inspect_content(source, body)
    except urllib.error.HTTPError as error:
        return result | {"status": "http_error", "http_status": error.code, "reason": str(error)}
    except (OSError, ValueError, ET.ParseError) as error:
        return result | {"status": "fetch_or_parse_error", "reason": str(error)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "source-probe.json")
    args = parser.parse_args()
    sources = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(probe, sources))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"purpose": "feasibility_only_not_collector_acceptance", "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in results:
        print(f"{item['id']}: {item['status']} HTTP={item.get('http_status', '-')} items={item.get('items', '-')}")


if __name__ == "__main__":
    main()
