"""PSI repository parsers and real-ground-truth metadata tests (offline)."""

from __future__ import annotations

import pytest

import psi_repo

TABLE = """Test Type,Test Day*,Year,Month,Date,Atmosphere*,Fuel Bottle,Flames Ignited*,Notes
First round of tests with nitrogen-diluted fuel and oxygen,19308,2019,Nov.,4,~30% O2 with N2,45% CH4 with N3,21,
Second round of tests with helium-diluted fuel and oxygen,20190,2020,July,8,~30% and ~21% O2 with He,35% H2 with He,21,
"""

TP_LOG = """Test Point: 19308A2

Script start: 2019-11-04 15:49:19
Ignition and retraction: 2019-11-04 15:50:06
MFCs off: 2019-11-04 15:50:21
Extinction detected: 2019-11-04 15:50:21
Test Point Failure: 2019-11-04 15:50:21
Reason: EXTINCTION DETECTED
"""

DATA = """2019-11-04 308 15:49:19:580 ,Experiment: 2,Test Point: 19308A2
Time,PTA3,IonCurrent,PMT1,PMT2,PMT3,RadiometerCenter,MFCA3FuelFlow
15:49:50:000,0.921,0.1,1.0,1.0,1.0,2.0,1.0
15:50:10:000,0.921,0.5,4.0,4.0,4.0,4.5,2.0
15:50:20:000,0.921,0.2,2.0,2.0,2.0,3.0,1.5
15:50:30:000,0.921,0.0,0.1,0.1,0.1,1.5,0.0
"""


def test_experimental_table_maps_days_to_conditions():
    table = psi_repo.parse_experimental_table(TABLE)
    assert set(table) == {"19308", "20190"}
    assert table["19308"]["fuel_bottle"] == "45% CH4 with N3"
    assert table["19308"]["atmosphere"] == "~30% O2 with N2"
    assert table["20190"]["fuel_bottle"] == "35% H2 with He"


def test_conditions_parse_oxygen_and_diluent():
    table = psi_repo.parse_experimental_table(TABLE)
    cond = psi_repo._conditions_for("20190", table)
    assert cond["oxygen_pct"] == 30.0
    assert cond["diluent"] == "He"
    assert psi_repo.fuel_from_blend(cond["fuel_bottle"]) == "H2"
    # Dominant species wins in blends, not the first hydrocarbon mentioned.
    assert psi_repo.fuel_from_blend("66.7% H2 with CH4") == "H2"
    assert psi_repo.fuel_from_blend("20% H2, 25% CH4, with He") == "CH4"
    assert psi_repo.fuel_from_blend("45% CH4 with N3") == "CH4"


def test_tp_log_burn_duration_and_extinction():
    log = psi_repo.parse_tp_log(TP_LOG)
    assert log["ignition"] is not None
    assert log["extinction_detected"] is True
    assert log["burn_duration_s"] == 15.0
    assert log["failure_reason"] == "EXTINCTION DETECTED"
    assert log["aborted"] is False


def test_sflame_csv_parses_metadata_and_columns():
    data = psi_repo.parse_sflame_data(DATA)
    assert data["start"] is not None
    assert len(data["times"]) == 4
    assert data["columns"]["PMT1"][1] == 4.0
    assert data["columns"]["PTA3"][0] == pytest.approx(0.921)


def test_summary_reduces_one_test_point_to_real_payload():
    table = psi_repo.parse_experimental_table(TABLE)
    conditions = psi_repo._conditions_for("19308", table)
    log = psi_repo.parse_tp_log(TP_LOG)
    data = psi_repo.parse_sflame_data(DATA)
    result = psi_repo.summarize_test_point(
        {"test_point": "19308A2", "test_day": "19308"}, conditions, data, log
    )

    payload = result["payload"]
    assert payload.source == "psi"
    assert payload.accession == "PSI-23"
    assert payload.test_point == "19308A2"
    assert payload.investigation == "ACME s-Flame"
    assert payload.fuel == "CH4"
    assert payload.oxygen_pct == 30.0
    assert payload.gravity_mode == "iss_micro_g"
    assert payload.burn_duration_s == 15.0
    assert payload.quench_time_s == 15.0
    assert payload.extinction is True
    assert payload.ambient_pressure_bar == pytest.approx(1.053, abs=2e-3)
    assert payload.peak_pmt_ua == pytest.approx(4.0)
    assert payload.peak_ion_current_ua == pytest.approx(0.5)
    assert payload.peak_radiometer_v == pytest.approx(4.5)
    # No invented image-derived fields.
    assert payload.peak_temp_k is None
    assert payload.max_radius_mm is None
    assert payload.profile_r == [] and payload.profile_t == []


def test_test_point_index_joins_data_and_log_files():
    detail = {
        "added": [
            {"file_name": "PSI-23_Raw Data_19308A2_data.csv", "file_size": 123},
            {"file_name": "PSI-23_Raw Data_19308A2_TP.txt"},
            {"file_name": "PSI-23_Raw Data_19308A2_mfcSetpoints.csv"},
        ]
    }
    points = psi_repo._test_point_index(detail)
    assert points["19308A2"]["data_file"].endswith("_data.csv")
    assert points["19308A2"]["tp_file"].endswith("_TP.txt")
    assert points["19308A2"]["test_day"] == "19308"


def test_curated_dataset_is_real_or_absent():
    curated = psi_repo.load_curated_ground_truth()
    if not curated:
        pytest.skip("curated s-Flame dataset not built in this checkout")
    first = curated[0]
    assert first["payload"]["source"] == "psi"
    assert first["payload"]["accession"] == "PSI-23"
    assert first["payload"]["test_point"]
    assert first["payload"]["burn_duration_s"] is not None
    assert first["payload"].get("peak_temp_k") is None
    # Every curated run must carry its conditions for auditability.
    assert first["provenance"]["atmosphere"]
    assert first["provenance"]["fuel_bottle"]


def test_load_ground_truth_prefers_curated_real_data():
    from s3_ingest import load_ground_truth

    runs = load_ground_truth()
    assert runs
    sources = {entry["payload"].get("source") for entry in runs}
    assert sources <= {"psi", "synthetic"}
    if psi_repo.load_curated_ground_truth():
        assert "psi" in sources


@pytest.mark.asyncio
async def test_nearest_ground_truth_prefers_real_flight_data():
    if not psi_repo.load_curated_ground_truth():
        pytest.skip("curated s-Flame dataset not built in this checkout")
    from schema import UnifiedPayload
    from server import _nearest_ground_truth

    sim = UnifiedPayload(
        source="sim",
        fuel="CH4",
        oxygen_pct=21.0,
        ambient_pressure_bar=1.05,
        gravity_mode="zero_g",
        peak_temp_k=1800.0,
    )
    match = await _nearest_ground_truth(sim)
    gt = match.payload
    assert gt is not None
    assert gt.source == "psi"
    assert gt.accession == "PSI-23"
    assert gt.test_point
    # zero_g simulations are allowed to match ISS microgravity flight data.
    assert gt.gravity_mode == "iss_micro_g"

    # The selection rationale is auditable, not just the winning payload.
    info = match.info
    assert info["matched"] is True
    assert info["pool"] == "real"
    assert info["selected"]["test_point"] == gt.test_point
    assert info["real_candidates"] >= 1
    assert info["candidates"] == info["real_candidates"] + info["synthetic_candidates"]
    assert set(info["components"]) == {
        "oxygen",
        "pressure",
        "velocity",
        "extinction_penalty",
    }
    assert info["distance"] == pytest.approx(
        sum(info["components"].values()), abs=1e-3
    )
    # CH4 has four curated flight runs, so a runner-up must be reported.
    assert info["runner_up"] is not None
    assert info["runner_up"]["test_point"] != gt.test_point
    assert info["runner_up"]["distance"] >= info["distance"]


@pytest.mark.asyncio
async def test_nearest_ground_truth_reports_no_match_without_fabricating():
    from schema import UnifiedPayload
    from server import _nearest_ground_truth

    sim = UnifiedPayload(
        source="sim",
        fuel="C3H8",
        oxygen_pct=21.0,
        ambient_pressure_bar=1.0,
        gravity_mode="mars_g",
        peak_temp_k=1800.0,
    )
    match = await _nearest_ground_truth(sim)
    assert match.payload is None
    assert match.info["matched"] is False
    assert match.info["candidates"] == 0
    assert "C3H8" in match.info["reason"]
    assert "mars_g" in match.info["reason"]


@pytest.mark.asyncio
async def test_nearest_ground_truth_marks_surrogate_pool():
    from schema import UnifiedPayload
    from server import _nearest_ground_truth

    # C2H4 has curated ISS runs only; a 1G request can still use the archive's
    # labelled surrogate, and the rationale must say so.
    sim = UnifiedPayload(
        source="sim",
        fuel="C2H4",
        oxygen_pct=21.0,
        ambient_pressure_bar=1.0,
        gravity_mode="earth_1g",
    )
    match = await _nearest_ground_truth(sim)
    assert match.payload is not None
    assert match.payload.source == "synthetic"
    assert match.info["pool"] == "synthetic"
    assert match.info["real_candidates"] == 0
    assert match.info["synthetic_candidates"] >= 1


@pytest.mark.asyncio
async def test_triage_without_ground_truth_withholds_comparison(monkeypatch):
    from jev_client import triage_pair
    from schema import UnifiedPayload

    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    sim = UnifiedPayload(
        source="sim",
        fuel="C3H8",
        oxygen_pct=21.0,
        ambient_pressure_bar=1.0,
        gravity_mode="earth_1g",
        peak_temp_k=1900.0,
        stability=70.0,
    )
    verdict = await triage_pair(None, sim)
    assert verdict.engine == "local"
    assert verdict.nasa_experiment_profile_match == "NONE"
    assert "No matching PSI" in verdict.notes
