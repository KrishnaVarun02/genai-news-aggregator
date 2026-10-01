import json
import os
import subprocess
import sys


def run(*args):
    env = {**os.environ, "PYTHONUTF8": "1", "ALLOW_PAID_API": "false"}
    return subprocess.run([sys.executable, "-m", "news_aggregator", *map(str, args)], text=True, capture_output=True, encoding="utf-8", env=env)


def test_actual_cli_demo_and_inspect(tmp_path):
    database = f"sqlite:///{tmp_path / 'cli.db'}"
    demo = run("demo", "--database-url", database, "--preview-dir", tmp_path / "preview")
    assert demo.returncode == 0, demo.stderr
    report = json.loads(demo.stdout)
    assert report["mode"] == "fixture" and report["selected"] == 3
    assert "FIXTURE" in (tmp_path / "preview" / f"{report['digest']}.html").read_text()
    checked = run("inspect", "--database-url", database)
    assert json.loads(checked.stdout) == {"articles": 4, "summaries": 3, "digests": 1}


def test_live_api_stops_without_spending_optin(tmp_path):
    result = run("run", "--mode", "live", "--database-url", f"sqlite:///{tmp_path / 'live.db'}")
    assert result.returncode == 2 and "ALLOW_PAID_API" in result.stderr
