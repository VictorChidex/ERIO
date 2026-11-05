import pytest

from erio_core.normalize.text import clean_title, html_to_text, sanitize_html


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Senior Backend Engineer", "Senior Backend Engineer"),
        ("🚀 Senior Backend Engineer 🚀", "Senior Backend Engineer"),
        ("URGENT: Product Designer", "Product Designer"),
        ("Hiring Now - Data Analyst!!", "Data Analyst"),
        ("Software Engineer (R123456)", "Software Engineer"),
        ("Account Executive [REQ-20931]", "Account Executive"),
        ("Data Engineer - JR104512", "Data Engineer"),
        ("Product Manager, Req ID: 88213", "Product Manager"),
        ("Softwareentwickler (m/w/d)", "Softwareentwickler"),
        ("Ingénieur Logiciel (H/F)", "Ingénieur Logiciel"),
        ("Staff Engineer, Payments", "Staff Engineer, Payments"),
        ("Engineer II", "Engineer II"),
        ("Head of Finance (PCF 11)", "Head of Finance (PCF 11)"),
        ("Lead SEC Analyst", "Lead SEC Analyst"),
    ],
)
def test_clean_title(raw: str, clean: str) -> None:
    assert clean_title(raw) == clean


def test_sanitize_keeps_structure_and_drops_scripts() -> None:
    dirty = (
        '<h2>About</h2><p onclick="steal()">Build <strong>payments</strong>.</p>'
        "<script>alert(1)</script><img src=x onerror=alert(1)>"
        '<a href="javascript:alert(1)">x</a><a href="https://example.com">apply</a>'
    )
    clean = sanitize_html(dirty)

    assert "<h2>About</h2>" in clean
    assert "<strong>payments</strong>" in clean
    assert "script" not in clean and "onclick" not in clean and "onerror" not in clean
    assert "<img" not in clean and "javascript:" not in clean
    assert 'href="https://example.com"' in clean
    assert "noopener" in clean


def test_html_to_text() -> None:
    assert html_to_text("<p>Build &amp; ship</p><ul><li>Go</li></ul>") == "Build & ship Go"


def test_trade_words_match_whole_words_only() -> None:
    from erio_core.normalize.roles import classify_role

    assert classify_role("Mechanic") == "other"
    assert classify_role("Senior Mechanical and Industrial Design Engineer") == "engineering"
    assert classify_role("Registered Nurse") == "other"
