"""Arsenal V1 Phase F: browser automation with read/extract/mutate/submit permit classes.

    READ_BROWSER        navigate, screenshot, accessibility snapshot
    EXTRACT_BROWSER     read page text or element contents
    MUTATE_BROWSER      click, fill, select, press (strong: Jev basis)
    SUBMIT_TRANSACTION  submit forms, pay, purchase, send, publish (strong: Jev basis)

A click whose target looks like a submit/pay/buy/send/publish control is
escalated to SUBMIT_TRANSACTION regardless of how the caller labelled it.
`BrowserSession` drives a Playwright-style page object injected by the host;
`launch_playwright` is an optional helper used only when Playwright is installed.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from capability_permits import PermitAuthority, digest, require

ACTIONS = {
    "goto": "browser.read", "screenshot": "browser.read", "snapshot": "browser.read",
    "text": "browser.extract", "inner_text": "browser.extract", "get_attribute": "browser.extract",
    "click": "browser.mutate", "fill": "browser.mutate", "select_option": "browser.mutate",
    "press": "browser.mutate", "check": "browser.mutate",
    "submit": "browser.submit_transaction",
}
TRANSACTIONAL = re.compile(
    r"\b(submit|pay|purchase|buy|checkout|check out|place order|order now|confirm|send|publish|post|"
    r"delete|transfer|subscribe|sign up|register|donate)\b", re.I)


def classify(action: str, target: str | None = None) -> str:
    require(action in ACTIONS, "unknown_browser_action")
    capability = ACTIONS[action]
    if capability == "browser.mutate" and action in ("click", "press") and target and TRANSACTIONAL.search(target):
        return "browser.submit_transaction"
    if action == "press" and target and target.strip().lower() == "enter":
        return "browser.submit_transaction"  # Enter in a form submits it
    return capability


def action_scope(action: str, url: str | None, target: str | None, value: str | None) -> dict:
    origin = None
    if url:
        parts = urlsplit(url)
        require(parts.scheme in ("http", "https"), "browser_url_must_be_http")
        origin = parts.scheme + "://" + parts.netloc
    return {"action": action, "origin": origin, "target": target, "value_hash": digest(value) if value else None}


class BrowserSession:
    """Permit-gated wrapper over an injected Playwright-like `page`."""

    def __init__(self, page, authority: PermitAuthority, *, allowed_origins: list[str]):
        require(allowed_origins and all(o.startswith(("http://", "https://")) for o in allowed_origins),
                "allowed_origins_required")
        self.page, self.authority, self.allowed = page, authority, set(allowed_origins)
        self.receipts: list[dict] = []

    def _current_origin(self) -> str | None:
        url = getattr(self.page, "url", None)
        if not url or url == "about:blank":
            return None
        parts = urlsplit(url)
        return parts.scheme + "://" + parts.netloc

    def perform(self, action: str, permit_id: str, *, url: str | None = None, target: str | None = None,
                value: str | None = None):
        capability = classify(action, target)
        origin_url = url if action == "goto" else getattr(self.page, "url", None)
        scope = action_scope(action, origin_url if origin_url not in (None, "about:blank") else None, target, value)
        require(scope["origin"] is None or scope["origin"] in self.allowed, "browser_origin_not_allowed")
        self.authority.consume(permit_id, capability, scope)
        outcome = {"status": "failed", "action": action, "capability": capability, "origin": scope["origin"]}
        try:
            if action == "goto":
                self.page.goto(url)
                require(self._current_origin() in self.allowed, "browser_redirected_outside_allowlist")
                result = None
            elif action == "screenshot":
                result = self.page.screenshot()
            elif action == "snapshot":
                result = self.page.accessibility.snapshot()
            elif action in ("text", "inner_text"):
                result = self.page.inner_text(target or "body")
            elif action == "get_attribute":
                name, _, attribute = (target or "").partition("@")
                result = self.page.get_attribute(name, attribute)
            elif action in ("click", "check"):
                result = getattr(self.page, action)(target)
            elif action == "fill":
                result = self.page.fill(target, value or "")
            elif action == "select_option":
                result = self.page.select_option(target, value)
            elif action == "press":
                result = self.page.keyboard.press(target)
            else:  # submit
                result = self.page.click(target)
            outcome = {**outcome, "status": "ok",
                       "result_hash": digest(result if isinstance(result, (str, dict, list, type(None)))
                                             else repr(type(result)))}
            return result
        finally:
            self.receipts.append(outcome)
            self.authority.receipt(permit_id, outcome)


def launch_playwright(*, headless: bool = True):
    """Optional: start Chromium via Playwright when it is installed."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("playwright_not_installed; pip install playwright && playwright install chromium") from error
    manager = sync_playwright().start()
    browser = manager.chromium.launch(headless=headless)
    return manager, browser, browser.new_page()
