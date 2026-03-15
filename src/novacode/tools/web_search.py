import json
import urllib.parse
import urllib.request
from langchain_core.tools import tool
from . import register

_DDG_API = "https://api.duckduckgo.com/"
_HEADERS = {"User-Agent": "NovaCode/0.1 (AI coding assistant)"}
MAX_RESULTS = 10


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return results for the given query.

    Uses the DuckDuckGo Instant Answer API. Returns a structured summary
    including an abstract (if available) and related topic links.

    Args:
        query: The search query string.
        max_results: Maximum number of related results to include (default 5).

    Returns a formatted string with the search abstract and result links.
    """
    max_results = min(max_results, MAX_RESULTS)
    params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
    url = f"{_DDG_API}?{params}"

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as e:
        return f"Error: could not reach search API: {e}"
    except Exception as e:
        return f"Error during web search: {e}"

    lines = []

    abstract = data.get("AbstractText", "").strip()
    abstract_url = data.get("AbstractURL", "").strip()
    abstract_source = data.get("AbstractSource", "").strip()
    if abstract:
        lines.append(f"Summary ({abstract_source}): {abstract}")
        if abstract_url:
            lines.append(f"Source: {abstract_url}")
        lines.append("")

    answer = data.get("Answer", "").strip()
    if answer:
        lines.append(f"Answer: {answer}")
        lines.append("")

    results = data.get("Results", [])
    topics = data.get("RelatedTopics", [])
    combined = results + topics
    count = 0
    for item in combined:
        if count >= max_results:
            break
        if isinstance(item, dict) and "Text" in item and "FirstURL" in item:
            lines.append(f"- {item['Text']}")
            lines.append(f"  {item['FirstURL']}")
            count += 1
        elif isinstance(item, dict) and "Topics" in item:
            for sub in item["Topics"]:
                if count >= max_results:
                    break
                if isinstance(sub, dict) and "Text" in sub and "FirstURL" in sub:
                    lines.append(f"- {sub['Text']}")
                    lines.append(f"  {sub['FirstURL']}")
                    count += 1

    if not lines:
        return f"No results found for: {query}"

    return "\n".join(lines)


register(web_search)
