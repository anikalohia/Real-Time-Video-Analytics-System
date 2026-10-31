import manager as manager_mod


class _FakeIngestor:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_fetch_running_returns_none_when_database_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(manager_mod, 'postgres_dsn', f"sqlite:///{tmp_path / 'missing.db'}")
    mgr = manager_mod.StreamManager()

    assert mgr.fetch_running() is None


def test_db_error_does_not_stop_existing_ingestors(monkeypatch, tmp_path):
    monkeypatch.setattr(manager_mod, 'postgres_dsn', f"sqlite:///{tmp_path / 'missing.db'}")
    mgr = manager_mod.StreamManager()
    fake = _FakeIngestor()
    mgr.ingestors['stream-1'] = fake

    def stop_after_one_poll(_seconds):
        mgr.running = False

    monkeypatch.setattr(manager_mod.time, 'sleep', stop_after_one_poll)
    mgr.run()

    assert fake.stopped is False


def test_empty_running_list_stops_existing_ingestors(monkeypatch):
    mgr = manager_mod.StreamManager()
    mgr.ingestors['stream-1'] = _FakeIngestor()
    stopped: list[str] = []

    def fake_stop(sid):
        stopped.append(sid)
        mgr.ingestors.pop(sid, None)

    monkeypatch.setattr(mgr, 'stop_stream', fake_stop)

    mgr.reconcile([])

    assert stopped == ['stream-1']
    assert 'stream-1' not in mgr.ingestors
