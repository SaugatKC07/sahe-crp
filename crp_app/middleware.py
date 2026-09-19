import json
import re


class HtmxPortalMiddleware:
    """Expose HTMX requests to templates and synchronize the persistent shell."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.htmx = request.headers.get("HX-Request") == "true"
        response = self.get_response(request)
        if request.htmx and response.status_code == 200:
            body = response.content.decode(response.charset or "utf-8", errors="ignore")
            match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
            if match:
                title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group(1))).strip()
                response["HX-Trigger"] = json.dumps({"sahe:page-title": {"title": title}})
        return response
