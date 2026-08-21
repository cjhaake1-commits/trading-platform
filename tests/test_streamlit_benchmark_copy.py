from pathlib import Path


def test_streamlit_benchmark_copy_mentions_reporting_only_and_cash_benchmark():
    text = Path("streamlit_app.py").read_text(encoding="utf-8")
    assert "20%-40% DAILY RETURN is a STRETCH BENCHMARK - REPORTING ONLY." in text
    assert "$20-$305 DAILY REALIZED CASH is an OPERATING BENCHMARK - REPORTING ONLY." in text
    assert "Live trading remains disabled." in text
    assert "unrealized gains do not count toward realized-cash success" in text.lower()
