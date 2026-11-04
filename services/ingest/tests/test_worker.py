from erio_ingest.worker import app, ping


def test_ping_task_runs() -> None:
    app.conf.task_always_eager = True
    try:
        assert ping.delay().get(timeout=1) == "pong"
    finally:
        app.conf.task_always_eager = False


def test_tasks_go_to_crawl_queue() -> None:
    assert app.conf.task_default_queue == "crawl"
