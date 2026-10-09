from pathlib import Path

import pytest

from scripts import prepare_netlify


def test_netlify_build_requires_https_api_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_netlify, "STATIC", tmp_path / "static")
    monkeypatch.setattr(prepare_netlify, "OUTPUT", tmp_path / "netlify-dist")
    prepare_netlify.STATIC.mkdir()
    (prepare_netlify.STATIC / "index.html").write_text("Taj", encoding="utf-8")

    for api_url in ("", "http://taj-api.onrender.com", "https://taj-api.onrender.com/path", "https://user:secret@taj-api.onrender.com"):
        monkeypatch.setenv("TAJ_API_URL", api_url)
        with pytest.raises(SystemExit, match="HTTPS origin"):
            prepare_netlify.main()
        assert not prepare_netlify.OUTPUT.exists()


def test_netlify_build_copies_site_and_creates_api_proxy_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_netlify, "STATIC", tmp_path / "static")
    monkeypatch.setattr(prepare_netlify, "OUTPUT", tmp_path / "netlify-dist")
    prepare_netlify.STATIC.mkdir()
    (prepare_netlify.STATIC / "index.html").write_text("Taj UI", encoding="utf-8")
    monkeypatch.setenv("TAJ_API_URL", "https://taj-api.onrender.com/")

    prepare_netlify.main()

    assert (prepare_netlify.OUTPUT / "index.html").read_text(encoding="utf-8") == "Taj UI"
    assert (prepare_netlify.OUTPUT / "_redirects").read_text(encoding="utf-8") == (
        "https://taj-api.onrender.com/v1/*  /v1/:splat  200\n"
        "https://taj-api.onrender.com/health  /health  200\n"
    )


def test_render_blueprint_keeps_database_and_redis_private():
    blueprint = Path("render.yaml").read_text(encoding="utf-8")
    assert "name: taj-api" in blueprint
    assert "runtime: docker" in blueprint
    assert "healthCheckPath: /health" in blueprint
    assert "name: taj-redis" in blueprint
    assert "ipAllowList: []" in blueprint
    assert "name: taj-postgres" in blueprint
    assert "key: OPENAI_API_KEY\n        sync: false" in blueprint
    assert "generateValue: true" in blueprint
