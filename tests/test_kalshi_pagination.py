from autotrader.kalshi.client import KalshiReadOnlyClient


def test_paginated_history_follows_cursor_and_deduplicates(monkeypatch):
    client = object.__new__(KalshiReadOnlyClient)
    pages = iter([
        {"fills": [{"fill_id": "a"}, {"fill_id": "b"}], "cursor": "next"},
        {"fills": [{"fill_id": "b"}, {"fill_id": "c"}], "cursor": ""},
    ])
    calls = []

    def fake_get(path, params, **kwargs):
        calls.append(dict(params))
        return next(pages)

    monkeypatch.setattr(client, "_get", fake_get)
    rows = client.paginate_read_only("portfolio/fills", params={"limit": "100"}, max_pages=3)
    assert [row["fill_id"] for row in rows] == ["a", "b", "c"]
    assert calls == [{"limit": "100"}, {"limit": "100", "cursor": "next"}]


def test_pagination_is_bounded():
    client = object.__new__(KalshiReadOnlyClient)
    try:
        client.paginate_read_only("fills", max_pages=0)
    except ValueError as exc:
        assert "max_pages" in str(exc)
    else:
        raise AssertionError("invalid pagination bound accepted")
