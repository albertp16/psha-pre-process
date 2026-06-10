"""Endpoint smoke tests against the bundled PHIVOLCS catalogue.

Guards the analysis routes end-to-end: pipeline steps run, responses carry
the documented keys, and error contracts use HTTP 400 (CODE_REVIEW B3).
Requires data/catalog.json (run scripts/convert_catalogue.py first).
"""
import json
from pathlib import Path

import pytest

import web_app

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "data" / "catalog.json").exists(),
    reason="data/catalog.json missing - run scripts/convert_catalogue.py")


@pytest.fixture()
def client():
    web_app.app.config["TESTING"] = True
    with web_app.app.test_client() as c:
        yield c


def test_catalog_info_unified_depth_classes(client):
    d = client.get("/api/catalog_info").get_json()
    assert d["available"]
    assert set(d["depth_classes"]) == {"shallow", "intermediate", "deep", "unknown"}
    assert "depth_class_labels" in d
    # one unified taxonomy: counts must sum to the catalogue size
    assert sum(d["depth_classes"].values()) == d["total_events"]


def test_declustering_runs_pipeline_steps(client):
    r = client.post("/api/declustering",
                    data={"use_default": "1", "use_gk": "1",
                          "use_gr": "0", "use_uh": "0"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["n_input"] >= d["n_total"]          # dedup may remove rows
    assert any("Step 2 duplicates" in n for n in d["pipeline_notes"])
    s = d["method_stats"]["gk"]
    assert s["mainshocks"] + s["aftershocks"] == d["n_total"]


def test_declustering_dedup_can_be_disabled(client):
    r = client.post("/api/declustering",
                    data={"use_default": "1", "use_gk": "1", "use_gr": "0",
                          "use_uh": "0", "dedup": "0"})
    d = r.get_json()
    assert d["n_input"] == d["n_total"]


def test_gutenberg_richter_default(client):
    r = client.post("/api/gutenberg_richter", data={"use_default": "1"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["b_value"] > 0
    assert d["b_stderr"] > 0
    assert not d["completeness_used"]
    assert any("not declustered" in w for w in d["warnings"])


def test_gutenberg_richter_full_pipeline(client):
    r = client.post("/api/gutenberg_richter",
                    data={"use_default": "1", "decluster_first": "1",
                          "mc": "4.5", "compl_whole": "1965,4.5\n1907,6.0"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["completeness_used"]
    assert any("Step 3 declustering" in n for n in d["pipeline_notes"])


def test_gutenberg_richter_mc_below_completeness_is_400(client):
    r = client.post("/api/gutenberg_richter",
                    data={"use_default": "1", "mc": "4.0",
                          "compl_whole": "1965,4.5"})
    assert r.status_code == 400
    assert "below the lowest completeness level" in r.get_json()["error"]


def test_mfd_default(client):
    r = client.post("/api/mfd", data={"use_default": "1"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["b_value"] > 0
    assert len(d["depth_plots"]) >= 1
    assert "truncGutenbergRichterMFD" in d["oq_truncated_gr"]


def test_max_magnitude_kijko_sellevoll(client):
    r = client.post("/api/max_magnitude",
                    data={"use_default": "1", "m_min": "4.5"})
    assert r.status_code == 200
    res = r.get_json()["results"]
    assert res["mmax_kijko_sellevoll"] >= res["observed_mmax"]
    assert res["b_source"] == "Aki MLE"
    assert "mmax_plus_05" not in res        # uncited placeholder removed (A3)


def test_max_magnitude_moment_is_mw_aligned(client):
    r = client.post("/api/max_magnitude",
                    data={"use_default": "1", "m_min": "4.5"})
    d = r.get_json()
    src = d["moment_sources"]
    # mixed-scale catalogue: reported Mw events plus Scordilis conversions
    assert src.get("mw", 0) > 0
    assert src.get("ms2mw", 0) > 0
    assert sum(src.values()) == d["results"]["n_events"]
    assert any("Mw" in n for n in d["pipeline_notes"])


def test_step1_homogenization_default_on_and_range_gated(client):
    r = client.post("/api/max_magnitude",
                    data={"use_default": "1", "m_min": "4.5"})
    d = r.get_json()
    assert any("Step 1 homogenization to Mw" in n for n in d["pipeline_notes"])
    # the Ms 8.3 maxima are outside the Scordilis range and must stay 8.3
    assert d["results"]["observed_mmax"] == 8.3


def test_step1_homogenization_can_be_disabled(client):
    r = client.post("/api/max_magnitude",
                    data={"use_default": "1", "m_min": "4.5", "homogenize": "0"})
    d = r.get_json()
    assert any("disabled by user" in n for n in d["pipeline_notes"])
    # moment sum still aligns to Mw on its own (display-level fallback)
    assert any("Moment input aligned to Mw" in n for n in d["pipeline_notes"])


def test_moment_magnitude_page_step1(client):
    r = client.post("/api/moment_magnitude", data={"use_default": "1"})
    assert r.status_code == 200
    d = r.get_json()
    c = d["counts"]
    assert c["mw"] > 0 and c["ms2mw"] > 0 and c["mb2mw"] > 0
    assert sum(c.values()) == d["total_events"]
    assert len(d["events_detail"]) == d["total_events"]
    # no dedup/decluster on this page: it is step 1 only
    assert d["total_events"] == d["n_input"]
    # homogenized CSV carries the provenance columns
    header = d["csv"].splitlines()[0]
    assert "mag_mw" in header and "mag_mw_src" in header


def test_moment_magnitude_user_coeffs_override(client):
    r = client.post("/api/moment_magnitude",
                    data={"use_default": "1",
                          "harmonize_coeffs": "Ms,0.67,2.07\nMb,1.38,-1.79"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["counts"].get("user_coeffs", 0) > 0


def test_max_magnitude_events_detail_computations(client):
    r = client.post("/api/max_magnitude",
                    data={"use_default": "1", "m_min": "4.5"})
    d = r.get_json()
    ev = d["events_detail"]
    assert len(ev) == d["results"]["n_events"]
    # the Ms 8.3 maxima are kept as reported (range-gated)
    big = max(ev, key=lambda e: e["mw_used"])
    assert big["mw_used"] == 8.3
    assert big["src"] == "raw"
    assert big["ms"] == 8.3
    # a converted event's stored M0 must equal the cited formula exactly
    one = next(e for e in ev if e["src"] == "ms2mw")
    assert one["m0"] == pytest.approx(10 ** (1.5 * one["mw_used"] + 9.05), rel=1e-9)
    # relation constants shipped for the client-side LaTeX rendering
    rel = d["moment_relations"]
    assert (rel["ms"]["a"], rel["ms"]["b"]) == (0.67, 2.07)
    assert (rel["mb"]["a"], rel["mb"]["b"]) == (0.85, 1.03)


def test_max_magnitude_user_b(client):
    r = client.post("/api/max_magnitude",
                    data={"use_default": "1", "m_min": "4.5", "b_value": "1.0"})
    assert r.status_code == 200
    res = r.get_json()["results"]
    assert res["b_source"] == "user"
    assert res["b_used"] == 1.0


def test_max_magnitude_errors_are_400(client):
    r = client.post("/api/max_magnitude", data={})
    assert r.status_code == 400              # error contract (B3)
    assert "error" in r.get_json()
