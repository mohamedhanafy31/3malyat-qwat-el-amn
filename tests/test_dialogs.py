"""سمات الإتاحة الأساسية لكل النوافذ في الصفحات المرسومة."""
from html.parser import HTMLParser

import pytest


PAGE_URLS = [
    "/", "/officers", "/personnel", "/duty", "/duty/stats", "/board",
    "/counts", "/afraad", "/service-catalog", "/officer-log", "/changes",
    "/missions", "/courses", "/register", "/register/OFF-001", "/leaves",
    "/leaves/stats", "/leaves/monthly", "/leaves/suspension",
]


class DialogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.dialogs = []
        self.close_buttons = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        classes = set(attributes.get("class", "").split())
        if "modal-card" in classes:
            self.dialogs.append(attributes)
        if tag == "button" and "close" in classes:
            self.close_buttons.append(attributes)


@pytest.mark.parametrize("url", PAGE_URLS)
def test_every_modal_has_accessible_dialog_markup(client, url):
    response = client.get(url)
    assert response.status_code == 200

    parser = DialogParser()
    parser.feed(response.get_data(as_text=True))

    for dialog in parser.dialogs:
        assert dialog.get("role") == "dialog"
        assert dialog.get("aria-modal") == "true"
        labelled_by = dialog.get("aria-labelledby")
        assert labelled_by
        assert labelled_by in parser.ids

    for button in parser.close_buttons:
        assert button.get("type") == "button"
        assert button.get("aria-label", "").strip()
