from dataclasses import dataclass
from typing import Any


@dataclass
class FormField:
    field_id: str
    label: str
    field_type: str
    options: list[str]
    required: bool
    confidence: float


class BrowserManager:
    """Playwright lifecycle boundary. Real platform sessions are deliberately not enabled by default."""
    def __init__(self):
        self._playwright = None
        self._browser = None

    async def start(self, *, headless: bool = True):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Install Playwright and its browser runtime to enable permitted browser workflows") from exc
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)
        return self._browser

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = self._playwright = None


class FormDetector:
    CHALLENGE_TERMS = ("captcha", "one-time password", "otp", "multi-factor", "mfa", "verify you are human")

    def detect_manual_challenge(self, visible_text: str) -> bool:
        lowered = visible_text.lower()
        return any(term in lowered for term in self.CHALLENGE_TERMS)

    def normalize_field(self, *, field_id: str, label: str = "", placeholder: str = "", name: str = "", aria_label: str = "", field_type: str = "text", options: list[str] | None = None, required: bool = False) -> FormField:
        inferred_label = next((value.strip() for value in (label, aria_label, placeholder, name.replace("_", " ")) if value.strip()), "Unknown field")
        confidence = 0.95 if label else 0.85 if aria_label else 0.7 if placeholder else 0.45 if name else 0.0
        return FormField(field_id=field_id, label=inferred_label, field_type=field_type, options=options or [], required=required, confidence=confidence)

    async def inspect_page(self, page: Any) -> dict:
        text = await page.locator("body").inner_text()
        if self.detect_manual_challenge(text):
            return {"status": "MANUAL_ACTION_REQUIRED", "reason": "CAPTCHA or identity challenge detected", "url": page.url}
        return {"status": "READY_FOR_FIELD_REVIEW", "url": page.url}
