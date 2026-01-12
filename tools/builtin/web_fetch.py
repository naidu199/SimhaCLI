from urllib.parse import urlparse

import httpx
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import BaseModel, Field


class WebFetchParams(BaseModel):
    url: str = Field(..., description="URL to fetch (must be http:// or https://)")
    timeout: int = Field(
        30,
        ge=5,
        le=120,
        description="Request timeout in seconds (default: 60)",
    )
    headers: dict[str, str] | None = Field(
        None,
        description="Optional custom headers to send with the request",
    )


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Fetch content from a URL. Returns the response body as text. "
        "Automatically uses browser-like headers to avoid being blocked by websites."
    )
    kind = ToolKind.NETWORK
    schema = WebFetchParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WebFetchParams(**invocation.params)

        parsed = urlparse(params.url)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            return ToolResult.error_result(f"Url must be http:// or https://")

        # Default browser-like headers to avoid being blocked
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

        # Merge with custom headers if provided
        headers = {**default_headers, **(params.headers or {})}

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(params.timeout),
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = await client.get(params.url)
                response.raise_for_status()
                text = response.text
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.reason_phrase}"
            should_suggest_search = False

            # Provide helpful hints for common errors
            if e.response.status_code == 403:
                error_msg += "\n💡 Tip: Website blocked the request. Try with different headers or the site may require authentication."
                should_suggest_search = True
            elif e.response.status_code == 999:
                error_msg += "\n💡 Tip: This is an anti-bot protection. The website (like LinkedIn) blocks automated requests."
                should_suggest_search = True
            elif e.response.status_code == 429:
                error_msg += (
                    "\n💡 Tip: Rate limit exceeded. Wait a moment before retrying."
                )
                should_suggest_search = True

            # Suggest web search fallback for blocking errors
            if should_suggest_search:
                # Extract domain from URL for better search query
                domain = urlparse(params.url).netloc
                search_hint = f"Try web_search to find public information about this content instead."
                error_msg += f"\n🔍 Alternative: {search_hint}"

            return ToolResult.error_result(
                error_msg,
                metadata={
                    "url": params.url,
                    "status_code": e.response.status_code,
                    "suggest_fallback": should_suggest_search,
                    "fallback_tool": "web_search" if should_suggest_search else None,
                },
            )
        except httpx.TimeoutException:
            return ToolResult.error_result(
                f"Request timed out after {params.timeout} seconds. Try increasing the timeout."
            )
        except httpx.ConnectError as e:
            return ToolResult.error_result(f"Connection failed: {e}")
        except Exception as e:
            return ToolResult.error_result(f"Request failed: {e}")

        # Truncate large responses
        original_length = len(text)
        max_size = 100 * 1024  # 100KB
        truncated = False

        if original_length > max_size:
            text = text[:max_size] + "\n\n... [content truncated]"
            truncated = True

        return ToolResult.success_result(
            text,
            metadata={
                "url": params.url,
                "status_code": response.status_code,
                "content_length": original_length,
                "truncated": truncated,
                "content_type": response.headers.get("content-type", "unknown"),
            },
        )
