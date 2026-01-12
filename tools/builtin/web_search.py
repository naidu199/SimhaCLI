from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import BaseModel, Field
from ddgs import DDGS


class WebSearchParams(BaseModel):
    query: str = Field(..., description="Search query")
    max_results: int = Field(
        10,
        ge=1,
        le=20,
        description="Maximum results to return (default: 10)",
    )
    region: str = Field(
        "wt-wt",
        description="Region for search results (default: wt-wt for worldwide, use 'us-en', 'uk-en', 'in-en', etc.)",
    )
    timelimit: str | None = Field(
        None,
        description="Time limit for results: 'd' (day), 'w' (week), 'm' (month), 'y' (year), None (all time)",
    )


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web using DuckDuckGo. Returns search results with titles, URLs and snippets. "
        "Great for finding public information when direct website access is blocked. "
        "Supports time filters and regional results."
    )
    kind = ToolKind.NETWORK
    schema = WebSearchParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WebSearchParams(**invocation.params)

        try:
            # Use DuckDuckGo for search
            results = DDGS().text(
                params.query,
                region=params.region,
                safesearch="off",
                timelimit=params.timelimit,
                max_results=params.max_results,
            )

            # Convert generator to list
            results = list(results)[: params.max_results]

        except Exception as e:
            return ToolResult.error_result(
                f"Search failed: {e}\n💡 Tip: Check your internet connection and try again."
            )

        if not results:
            return ToolResult.success_result(
                f"No results found for: '{params.query}'\n💡 Tip: Try rephrasing your query or use different keywords.",
                metadata={
                    "query": params.query,
                    "results": 0,
                },
            )

        output_lines = [
            f"🔍 Search results for: '{params.query}'",
            f"Found {len(results)} results\n",
        ]

        for i, result in enumerate(results, start=1):
            title = result.get("title", "No title")
            url = result.get("href", "")
            snippet = result.get("body", "")

            output_lines.append(f"{i}. {title}")
            output_lines.append(f"   🔗 {url}")
            if snippet:
                # Truncate very long snippets
                if len(snippet) > 200:
                    snippet = snippet[:197] + "..."
                output_lines.append(f"   📝 {snippet}")
            output_lines.append("")

        return ToolResult.success_result(
            "\n".join(output_lines),
            metadata={
                "query": params.query,
                "results": len(results),
                "region": params.region,
                "timelimit": params.timelimit,
            },
        )
