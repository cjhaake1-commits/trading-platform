from autotrader.options_probe import probe_adapter


class Adapter:
    def get_option_chain(self): pass


def test_options_probe_records_existing_adapter_evidence(tmp_path):
    rows = probe_adapter("test", Adapter(), output=tmp_path / "o.json")
    states = {row["capability"]: row["state"] for row in rows}
    assert states["OPTION_CHAIN"] == "SUPPORTED"
    assert states["OPTION_PAPER_EXECUTION"] == "UNSUPPORTED"
