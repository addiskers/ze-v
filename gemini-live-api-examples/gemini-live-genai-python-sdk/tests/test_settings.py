"""Admin-tunable settings — storage (eo_db), precedence (eo_api.effective_settings),
and the consumers that read them (campaign_runner pacing, callbacks window)."""

import eo_api


def test_settings_storage_roundtrip(fresh_eo_db):
    eo_db = fresh_eo_db
    eo_db.init()
    assert eo_db.get_setting("agent_voice") is None
    assert eo_db.get_setting("agent_voice", "Aoede") == "Aoede"
    eo_db.set_settings({"agent_voice": "Kore", "campaign_max_per_tick": 3})
    assert eo_db.get_setting("agent_voice") == "Kore"
    assert eo_db.all_settings() == {"agent_voice": "Kore", "campaign_max_per_tick": "3"}
    eo_db.set_settings({"agent_voice": "Aoede"})     # upsert overwrites
    assert eo_db.get_setting("agent_voice") == "Aoede"


def test_effective_settings_precedence_stored_env_default(fresh_eo_db, monkeypatch):
    eo_db = fresh_eo_db
    eo_db.init()
    # default (nothing stored, no env)
    monkeypatch.delenv("EO_CAMPAIGN_MAX_CONCURRENT", raising=False)
    s = eo_api.effective_settings()
    assert s["campaign_max_concurrent"] == 2
    assert s["agent_voice"] == "Aoede" and s["agent_language"] == "hi-IN"
    assert s["campaign_call_start"] == "09:00" and s["campaign_max_per_day"] == 3
    # env beats default
    monkeypatch.setenv("EO_CAMPAIGN_MAX_CONCURRENT", "7")
    assert eo_api.effective_settings()["campaign_max_concurrent"] == 7
    # stored beats env
    eo_db.set_settings({"campaign_max_concurrent": 4})
    assert eo_api.effective_settings()["campaign_max_concurrent"] == 4
    # garbage stored int falls back to the code default (never crashes)
    eo_db.set_settings({"campaign_days": "banana"})
    assert eo_api.effective_settings()["campaign_days"] == 1


def test_campaign_runner_pacing_reads_settings(fresh_eo_db, monkeypatch):
    import campaign_runner
    eo_db = fresh_eo_db
    eo_db.init()
    monkeypatch.setenv("EO_CAMPAIGN_MAX_PER_TICK", "5")
    # env fallback while nothing is stored
    assert campaign_runner._cfg_int("EO_CAMPAIGN_MAX_PER_TICK", 1) == 5
    # stored setting wins over env
    eo_db.set_settings({"campaign_max_per_tick": 2})
    assert campaign_runner._cfg_int("EO_CAMPAIGN_MAX_PER_TICK", 1) == 2
    # non-pacing keys stay env-only
    monkeypatch.setenv("EO_CAMPAIGN_DIAL_TIMEOUT", "45")
    assert campaign_runner._cfg_int("EO_CAMPAIGN_DIAL_TIMEOUT", 60) == 45


def test_callbacks_global_window_reads_settings(fresh_eo_db, monkeypatch):
    import callbacks
    eo_db = fresh_eo_db
    eo_db.init()
    monkeypatch.delenv("EO_CALL_WINDOW_START", raising=False)
    monkeypatch.delenv("EO_CALL_WINDOW_END", raising=False)
    assert callbacks.global_window() == (540, 1260)          # 09:00–21:00 defaults
    eo_db.set_settings({"campaign_call_start": "10:30", "campaign_call_end": "19:00"})
    assert callbacks.global_window() == (630, 1140)
