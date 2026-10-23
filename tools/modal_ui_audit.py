#!/usr/bin/env python3
"""Capture and measure every rendered dialog at desktop and phone sizes.

The script is intentionally read-only: it reveals existing dialogs in the DOM
without submitting their forms.  Credentials and the base URL are supplied by
environment variables so it can run against an isolated local data directory.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("MODAL_AUDIT_URL", "http://127.0.0.1:5052").rstrip("/")
USERNAME = os.environ.get("MODAL_AUDIT_USERNAME", "")
PASSWORD = os.environ.get("MODAL_AUDIT_PASSWORD", "")
OUTPUT = Path(os.environ.get("MODAL_AUDIT_OUTPUT", "/tmp/personnel-modal-audit-shots"))

ROUTES = (
    "/", "/officers", "/personnel", "/duty", "/duty/stats", "/board",
    "/counts", "/afraad", "/service-catalog", "/officer-log", "/changes",
    "/audit", "/activity-stats", "/users", "/missions", "/vehicles",
    "/drivers", "/campaign", "/leaves", "/leaves/stats", "/leaves/monthly",
    "/leaves/suspension", "/courses", "/register",
)

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "phone": {"width": 390, "height": 844},
}


def safe_name(value: str) -> str:
    value = value.strip("/") or "dashboard"
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value)


def login(page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
    page.locator('input[name="loginRole"][value="admin"]').check()
    page.locator("#loginUsername").fill(USERNAME)
    page.locator("#loginPassword").fill(PASSWORD)
    page.locator("#loginForm button[type=submit]").click()
    page.wait_for_url(re.compile(r"^(?!.*\/login(?:\?|$)).*$"))


def reveal(page, modal_id: str) -> None:
    page.evaluate(
        """modalId => {
          document.querySelectorAll('.modal').forEach(modal => {
            modal.classList.add('hidden');
            modal.setAttribute('aria-hidden', 'true');
          });
          const modal = document.getElementById(modalId);
          if (typeof _enhanceModalFrame === 'function') _enhanceModalFrame(modal);
          modal.classList.remove('hidden');
          modal.removeAttribute('aria-hidden');
          document.body.classList.add('modal-open');
          const card = modal.querySelector('.modal-card');
          if (card) card.scrollTop = 0;
        }""",
        modal_id,
    )


def measure(page, route: str, viewport: str, modal_id: str) -> dict:
    return page.evaluate(
        """({route, viewport, modalId}) => {
          const modal = document.getElementById(modalId);
          const card = modal.querySelector('.modal-card');
          const rect = card.getBoundingClientRect();
          const scrollbox = card.querySelector(':scope > .modal-body') || card;
          const title = card.querySelector('h2')?.textContent.trim() || modalId;
          const close = card.querySelector('.close')?.getBoundingClientRect();
          const footer = card.querySelector('.modal-foot, .dialog-actions')?.getBoundingClientRect();
          const controls = [...card.querySelectorAll('input:not([type=hidden]), select, textarea, button, a[href]')];
          const escaped = controls.filter(el => {
            const r = el.getBoundingClientRect();
            return r.right > rect.right + 1 || r.left < rect.left - 1;
          }).map(el => el.id || el.name || el.textContent.trim().slice(0, 30));
          const smallTargets = controls.filter(el => {
            const r = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              (r.width < 40 || r.height < 40);
          }).map(el => el.id || el.getAttribute('aria-label') || el.textContent.trim().slice(0, 30));
          const smallInputText = controls.filter(el =>
            el.matches('input, select, textarea') && parseFloat(getComputedStyle(el).fontSize) < 16
          ).map(el => el.id || el.name);
          return {
            route, viewport, id: modalId, title,
            card: {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
              width: rect.width, height: rect.height, clientWidth: scrollbox.clientWidth,
              scrollWidth: scrollbox.scrollWidth, clientHeight: scrollbox.clientHeight,
              scrollHeight: scrollbox.scrollHeight},
            overflowX: scrollbox.scrollWidth > scrollbox.clientWidth + 1,
            overflowY: scrollbox.scrollHeight > scrollbox.clientHeight + 1,
            outsideViewport: rect.left < 0 || rect.right > innerWidth || rect.top < 0 || rect.bottom > innerHeight,
            closeOutside: close ? close.left < rect.left || close.right > rect.right || close.top < rect.top : true,
            footerOutside: footer ? footer.left < rect.left - 1 || footer.right > rect.right + 1 : false,
            escapedControls: escaped,
            smallTargets,
            smallInputText,
          };
        }""",
        {"route": route, "viewport": viewport, "modalId": modal_id},
    )


def run() -> list[dict]:
    if not USERNAME or not PASSWORD:
        raise SystemExit("Set MODAL_AUDIT_USERNAME and MODAL_AUDIT_PASSWORD")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--disable-dev-shm-usage"],
        )
        for viewport_name, viewport in VIEWPORTS.items():
            shot_dir = OUTPUT / viewport_name
            shot_dir.mkdir(parents=True, exist_ok=True)
            context = browser.new_context(viewport=viewport, device_scale_factor=1)
            page = context.new_page()
            login(page)
            seen: set[str] = set()
            for route in ROUTES:
                page.goto(f"{BASE_URL}{route}", wait_until="networkidle")
                page.wait_for_timeout(150)
                modal_ids = page.locator(".modal[id]").evaluate_all(
                    "nodes => nodes.map(node => node.id).filter(Boolean)"
                )
                for modal_id in modal_ids:
                    signature = f"{viewport_name}:{modal_id}"
                    if signature in seen:
                        continue
                    seen.add(signature)
                    reveal(page, modal_id)
                    row = measure(page, route, viewport_name, modal_id)
                    results.append(row)
                    base = f"{safe_name(route)}--{safe_name(modal_id)}"
                    page.screenshot(path=shot_dir / f"{base}--top.png")
                    if row["overflowY"]:
                        page.evaluate(
                            "id => { const card = document.querySelector(`#${CSS.escape(id)} .modal-card`); const box = card.querySelector(':scope > .modal-body') || card; box.scrollTop = box.scrollHeight; }",
                            modal_id,
                        )
                        page.screenshot(path=shot_dir / f"{base}--bottom.png")
            context.close()
        browser.close()
    (OUTPUT / "report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


if __name__ == "__main__":
    rows = run()
    problems = [row for row in rows if any((
        row["overflowX"], row["outsideViewport"], row["closeOutside"],
        row["footerOutside"], row["escapedControls"],
        row["viewport"] == "phone" and row["smallInputText"],
    ))]
    print(json.dumps({"dialogs": len(rows), "problems": problems}, ensure_ascii=False, indent=2))
