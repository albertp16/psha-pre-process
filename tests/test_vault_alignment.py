"""Cross-check the repo pipeline against the psha-mind vault Day 16 module.

The vault note `notes/code/16 - Moment magnitude.md` (and its
`16_moment_magnitude.py`) is the reference of record for the Mw scale and the
cited Ms/mb->Mw conversions (Hanks & Kanamori 1979 Eq. 7 p. 2349; BBS Eq. 2.5
pp. 35/57; Lamessa et al. 2019 p. 5). These tests assert the repo's
`pipeline.homogenize_to_mw` / `pipeline.seismic_moment_nm` reproduce the vault
implementation exactly. Skipped on machines without the vault.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from psha_preprocess.catalogue import pipeline as pl

VAULT_DAY16 = (Path.home() / "Desktop" / "PSHA" / "PSHA Project" /
               "notes" / "code" / "16_moment_magnitude.py")

pytestmark = pytest.mark.skipif(
    not VAULT_DAY16.exists(),
    reason="psha-mind vault not present on this machine")


def _load_vault():
    spec = importlib.util.spec_from_file_location("vault_day16", VAULT_DAY16)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_relation_tables_match_vault():
    v = _load_vault()
    assert pl.MS_RELATIONS == v._MS_RELATIONS
    assert pl.MB_RELATIONS == v._MB_RELATIONS


def test_ms_conversion_matches_vault():
    v = _load_vault()
    for ms in (3.0, 3.5, 4.2, 5.0, 5.7, 6.0, 6.1):   # inside Scordilis Eq. 8 range
        repo, _ = pl.homogenize_to_mw(ms=[ms], fallback=[ms])
        assert repo[0] == pytest.approx(v.ms_to_mw(ms), rel=1e-12)


def test_mb_conversion_matches_vault():
    v = _load_vault()
    for mb in (3.5, 4.0, 4.7, 5.5, 6.0, 6.2):        # inside Scordilis Eq. 1 range
        repo, _ = pl.homogenize_to_mw(mb=[mb], fallback=[mb])
        assert repo[0] == pytest.approx(v.mb_to_mw(mb), rel=1e-12)


def test_seismic_moment_inverts_vault_mw_from_moment():
    # Repo forward: M0 = 10^(1.5 Mw + 9.05) (HK Eq. 7 exact, dyne-cm 16.05 -> SI).
    # Vault inverse uses the rounded N·m constant 6.03 (= 9.045/1.5), so the
    # round trip agrees to the 0.0033 magnitude units that rounding implies.
    v = _load_vault()
    for mw in (4.5, 6.0, 7.0, 8.3):
        m0 = float(pl.seismic_moment_nm(mw))
        assert v.mw_from_moment(m0, units="Nm") == pytest.approx(mw, abs=5e-3)


def test_priority_matches_vault_homogenize():
    # Reported Mw preferred, then Ms, then mb — same ordering as the vault's
    # homogenize_to_mw default priority ("Mw", "Ms", "mb").
    repo, src = pl.homogenize_to_mw(
        mw=[7.2, np.nan, np.nan], ms=[6.5, 6.0, np.nan],
        mb=[5.0, 5.5, 5.0], fallback=[7.2, 6.0, 5.0])
    assert src.tolist() == ["mw", "ms2mw", "mb2mw"]
    assert repo[0] == 7.2
