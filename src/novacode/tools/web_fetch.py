import urllib.request
import urllib.error
from html.parser import HTMLParser
from langchain_core.tools import tool
from . import register

_HEADERS = {"User-Agent": "NovaCode/0.1 (AI coding assistant)"}
MAX_CHARS = 20_000
_SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link"}


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text converter using stdlib html.parser."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_tag_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_tag_stack.append(tag)
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        # Search from the top of the stack rather than only checking the top.
        # This correctly handles void elements (e.g. <meta>, <link>) that are
        # never closed, which would otherwise block all subsequent tags from
        # being popped and suppress the entire page body.
        for i in range(len(self._skip_tag_stack) - 1, -1, -1):
            if self._skip_tag_stack[i] == tag:
                self._skip_tag_stack.pop(i)
                break

    def handle_data(self, data):
        if not self._skip_tag_stack:
            text = data.strip()
            if text:
                self._parts.append(text + " ")

    def get_text(self) -> str:
        import re
        raw = "".join(self._parts)
        # Collapse excessive whitespace / blank lines
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


@tool
def web_fetch(url: str) -> str:
    """Fetch the content of a URL and return it as plain text.

    Retrieves the page, strips HTML tags, and returns readable text.
    Useful for reading documentation, articles, or any web page.

    Args:
        url: The fully-formed URL to fetch (http or https).

    Returns the page content as plain text, truncated if very large.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw_bytes = resp.read()
    except urllib.error.HTTPError as e:
        return f"Error: HTTP {e.code} for {url}: {e.reason}"
    except urllib.error.URLError as e:
        return f"Error: could not fetch {url}: {e.reason}"
    except Exception as e:
        return f"Error fetching {url}: {e}"

    # Detect encoding
    encoding = "utf-8"
    if "charset=" in content_type:
        encoding = content_type.split("charset=")[-1].split(";")[0].strip()

    text = raw_bytes.decode(encoding, errors="replace")

    # Convert HTML to plain text
    if "html" in content_type or text.lstrip().startswith("<"):
        extractor = _TextExtractor()
        try:
            extractor.feed(text)
            text = extractor.get_text()
        except Exception:
            pass  # fall back to raw text

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n... [truncated — {len(text)} chars total]"

    return text or "(empty page)"


register(web_fetch)
