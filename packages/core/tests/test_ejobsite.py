from erio_core.connectors.ejobsite import EJobSiteConnector

BOARD = "https://www.jobs.example.org/industry_rss.php"


def feed(*links: str) -> bytes:
    items = "".join(
        f"<item><title>Job {n}</title><link>{link}</link><description>x</description></item>"
        for n, link in enumerate(links)
    )
    return f"<rss><channel>{items}</channel></rss>".encode()


def test_only_links_on_the_board_itself_become_postings() -> None:
    body = feed(
        "https://jobs.example.org/101/nurse",
        "http://192.168.1.2/applicant_tracking5/job_details.php?q=1",
        "https://evil.example.net/102/nurse",
    )

    postings = EJobSiteConnector().extract(body, BOARD)

    assert [p.external_id for p in postings] == ["101"]


def test_a_link_is_upgraded_to_https() -> None:
    (posting,) = EJobSiteConnector().extract(feed("http://jobs.example.org/7/x"), BOARD)

    assert str(EJobSiteConnector().parse(posting).apply_url).startswith("https://jobs.example.org/")
