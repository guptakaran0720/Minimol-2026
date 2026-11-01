import json

from bench.bench import main


def test_simulated_bench_runs_end_to_end(tmp_path):
    results = main(["--sim", "--reps", "1", "--csv-mb", "1", "--random-mb", "0.5", "--out", str(tmp_path)])
    assert results["meta"]["mode"] == "simulated"
    assert all(f["sha256_match"] for f in results["files"].values())
    assert results["delta"]["sha256_match"] and results["delta"]["v2_reused_chunks"] >= 1
    assert results["placement"]["tiered"]["slow_node_share"]["median"] == 0.0
    assert results["repair"]["healthy"] and results["repair"]["sha256_match_after"]
    saved = list(tmp_path.glob("simulated-*.json"))
    assert len(saved) == 1 and json.loads(saved[0].read_text())["meta"]["reps"] == 1
    assert "not measurements of the system" in next(tmp_path.glob("simulated-*.md")).read_text()
