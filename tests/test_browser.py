import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import pytest


@pytest.mark.skipif(
    not os.environ.get("CP_BROWSER_TESTS"),
    reason="enable CP_BROWSER_TESTS with a local Chromium installation",
)
def test_management_browser_plan_execute_and_mobile(managed):
    from playwright.sync_api import sync_playwright
    from control_plane.config import get_settings
    from control_plane.caddy_protection import create_session_cookie

    c, rt, fake = managed
    settings = get_settings()
    settings.portal_roles = json.dumps(
        {"marco": {"role": "administrator", "services": ["*"]}}
    )
    c.headers.pop("Authorization")
    origin = "https://protected.marcosudau.com"
    screenshots = Path(
        os.environ.get("CP_BROWSER_ARTIFACT_DIR", "/tmp/ctpl-browser-evidence")
    )
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        candidates = list(
            (Path.home() / ".cache/ms-playwright").glob(
                "chromium_headless_shell-*/chrome-linux/headless_shell"
            )
        ) + list(
            (Path.home() / ".cache/ms-playwright").glob(
                "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"
            )
        )
        browser = p.chromium.launch(
            headless=True,
            executable_path=str(candidates[0]) if candidates else None,
            args=["--no-sandbox"],
        )
        context = browser.new_context(viewport={"width": 1400, "height": 1000})
        context.add_cookies(
            [
                {
                    "name": settings.caddy_protection_cookie_name,
                    "value": create_session_cookie("marco"),
                    "url": origin,
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def intercept(route):
            request = route.request
            assert request.url.startswith(origin + "/"), (
                "unexpected external browser request"
            )
            parsed = urlsplit(request.url)
            headers = {
                k: v
                for k, v in request.all_headers().items()
                if k not in {"host", "content-length"}
            }
            assert "authorization" not in headers
            response = c.request(
                request.method,
                parsed.path + ("?" + parsed.query if parsed.query else ""),
                headers=headers,
                content=request.post_data_buffer,
                follow_redirects=False,
            )
            route.fulfill(
                status=response.status_code,
                headers={
                    k: v
                    for k, v in response.headers.items()
                    if k not in {"content-length", "content-encoding"}
                },
                body=response.content,
            )

        page.route("**/*", intercept)
        page.goto(origin + "/management")
        page.get_by_role("button", name="Sample App · active").click()
        page.get_by_role("button", name="Stop planen", exact=True).click()
        page.get_by_role("dialog").wait_for(state="visible")
        page.get_by_role("button", name="Diesen Plan freigeben und ausführen").click()
        page.get_by_text("Ausführung und Prüfung abgeschlossen.", exact=True).wait_for(
            timeout=15000
        )
        assert fake.state == "exited"
        page.get_by_role("button", name="Schließen", exact=True).click()
        assert "test-token" not in page.content()
        assert page.evaluate("document.cookie") == ""
        page.screenshot(
            path=str(screenshots / "management-desktop.png"), full_page=True
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(screenshots / "management-mobile.png"), full_page=True)
        assert not errors
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        browser.close()
