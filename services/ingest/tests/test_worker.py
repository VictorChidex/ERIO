import pytest

from erio_ingest.worker import app, ping


def test_ping_task_runs() -> None:
    app.conf.task_always_eager = True
    try:
        assert ping.delay().get(timeout=1) == "pong"
    finally:
        app.conf.task_always_eager = False


def test_tasks_go_to_crawl_queue() -> None:
    assert app.conf.task_default_queue == "crawl"


def test_normalizing_and_indexing_have_their_own_queue() -> None:
    def queue(task: str) -> str:
        return str(app.amqp.router.route({}, task)["queue"].name)

    assert queue("erio.normalize_pending") == "pipeline"
    assert queue("erio.index_changed") == "pipeline"
    assert queue("erio.crawl_board") == "crawl"  # board crawls keep the default queue


class FakeCrawl:
    def __init__(self, new: int = 0, changed: int = 0, error: Exception | None = None) -> None:
        self.new, self.changed, self.error = new, changed, error
        self.calls: list[str] = []

    def __call__(self, *args: object) -> object:
        self.calls.append("crawl")
        if self.error:
            raise self.error
        return type("Result", (), {"new_postings": self.new, "changed_postings": self.changed})()


def run_live(monkeypatch: pytest.MonkeyPatch, crawl: FakeCrawl) -> list[tuple[int, int]]:
    from erio_ingest import worker

    counted: list[tuple[int, int]] = []
    monkeypatch.setattr(worker, "engine", lambda: None)
    monkeypatch.setattr(worker, "fetcher", lambda: None)
    monkeypatch.setattr(worker, "store", lambda: None)
    monkeypatch.setattr(worker, "crawl_board", crawl)
    monkeypatch.setattr(worker, "normalize_pending", lambda *a: crawl.calls.append("normalize"))
    monkeypatch.setattr(worker, "index_changed_task", lambda: crawl.calls.append("index"))
    monkeypatch.setattr(worker.Redis, "from_url", staticmethod(lambda url: object()))
    monkeypatch.setattr(
        worker.live, "board_done", lambda r, rid, new, changed: counted.append((new, changed))
    )
    return counted


def test_a_live_crawl_makes_new_jobs_searchable_and_counts_the_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from erio_ingest.worker import crawl_board_live_task

    crawl = FakeCrawl(new=2, changed=1)
    counted = run_live(monkeypatch, crawl)

    result = crawl_board_live_task(7, "r1")

    assert crawl.calls == ["crawl", "normalize", "index"]
    assert counted == [(2, 1)]
    assert result == {"board_id": 7, "new_postings": 2, "changed_postings": 1}


def test_a_live_crawl_that_finds_nothing_new_does_not_reindex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from erio_ingest.worker import crawl_board_live_task

    crawl = FakeCrawl()
    counted = run_live(monkeypatch, crawl)

    crawl_board_live_task(7, "r1")

    assert crawl.calls == ["crawl"]
    assert counted == [(0, 0)]


def test_a_live_crawl_that_fails_still_counts_the_board(monkeypatch: pytest.MonkeyPatch) -> None:
    from erio_ingest.worker import crawl_board_live_task

    crawl = FakeCrawl(error=RuntimeError("board down"))
    counted = run_live(monkeypatch, crawl)

    with pytest.raises(RuntimeError):
        crawl_board_live_task(7, "r1")

    assert counted == [(0, 0)]  # the page polling this refresh is never left waiting
