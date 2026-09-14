from helpers import make_env

from cc.preflight import FAIL, PASS, WARN, config_checks, run


def by_name(env) -> dict:
    return {check.name: check for check in config_checks(env)}


def test_local_defaults_pass_without_a_token():
    checks = by_name(make_env(dev_mode=True))
    assert checks["Access token"].status == PASS and "Dev mode" not in checks


def test_a_server_without_a_token_fails():
    for env in (make_env(host="0.0.0.0"), make_env(cors_origins=("https://x.vercel.app",)), make_env(dev_mode=False)):
        assert by_name(env)["Access token"].status == FAIL


def test_a_configured_server_has_no_failures(monkeypatch):
    monkeypatch.setenv("CC_TEST_AI_KEY", "configured")
    checks = by_name(make_env(host="0.0.0.0", access_token="a" * 32, cors_origins=("https://x.vercel.app",), dev_mode=False))
    assert all(check.status != FAIL for check in checks.values())
    assert checks["Dev mode"].status == PASS and checks["AI API key"].status == PASS
    assert by_name(make_env(access_token="short", dev_mode=True, host="0.0.0.0"))["Dev mode"].status == WARN


def test_run_exits_non_zero_on_failure(capsys):
    assert run(make_env(host="0.0.0.0"), network=False) == 1
    output = capsys.readouterr().out
    assert "FAIL  Access token" in output and "server mode" in output


def test_check_flag_runs_the_preflight(monkeypatch):
    import cc.__main__ as entry
    import cc.preflight as preflight

    monkeypatch.setattr(entry, "load_environment", lambda: None)
    monkeypatch.setattr(preflight, "run", lambda env: 0)
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("server must not start")))
    try:
        entry.main(["--check"])
    except SystemExit as exit_:
        assert exit_.code == 0
    else:
        raise AssertionError("--check must exit")
