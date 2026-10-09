import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "static"
OUTPUT = ROOT / "netlify-dist"


def main() -> None:
    backend = os.environ.get("TAJ_API_URL", "").strip().rstrip("/")
    parsed = urlsplit(backend)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in backend)
    ):
        raise SystemExit(
            "Set TAJ_API_URL to the HTTPS origin of the deployed Render service, "
            "for example https://taj-api.onrender.com."
        )

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    shutil.copytree(STATIC, OUTPUT)
    (OUTPUT / "_redirects").write_text(
        f"{backend}/v1/*  /v1/:splat  200\n"
        f"{backend}/health  /health  200\n",
        encoding="utf-8",
    )
    print(f"Prepared Netlify static site with API proxy to {parsed.netloc}.")


if __name__ == "__main__":
    main()
