import hashlib
from pathlib import Path

import pytest

from scripts.deploy_reviewed_income import check_reviewed_files, preserve


def test_only_exact_reviewed_source_is_eligible(tmp_path):
    path = tmp_path / 'dashboard_simple.py'
    path.write_text('original\n')
    manifest = {'dashboard_simple.py': hashlib.sha256(path.read_bytes()).hexdigest()}
    assert check_reviewed_files(tmp_path, ['dashboard_simple.py', 'var/report.json'], manifest) == ['dashboard_simple.py']
    path.write_text('new local edit\n')
    with pytest.raises(ValueError):
        check_reviewed_files(tmp_path, ['dashboard_simple.py'], manifest)
    with pytest.raises(ValueError):
        check_reviewed_files(tmp_path, ['other.py'], manifest)


def test_preserve_is_private_and_does_not_change_source(tmp_path, monkeypatch):
    from scripts import deploy_reviewed_income as repair
    (tmp_path / 'example.py').write_text('safe\n')
    monkeypatch.setattr(repair, 'git', lambda *args: 'example.py')
    backup = tmp_path / 'private-backup'
    hashes = preserve(tmp_path, backup, [])
    assert hashes['example.py'] == hashlib.sha256(b'safe\n').hexdigest()
    assert (tmp_path / 'example.py').read_text() == 'safe\n'
    assert backup.stat().st_mode & 0o777 == 0o700
    assert (backup / 'source-backup.tar.gz').stat().st_mode & 0o777 == 0o600


def test_deployment_never_resets_trades_or_discards_remote_history():
    source = Path('scripts/deploy_reviewed_income.py').read_text()
    assert '"--ff-only"' in source
    assert '"stash", "push"' in source
    assert 'reset", "--hard' not in source
    assert 'DELETE FROM' not in source
