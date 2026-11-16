"""Dev server entry point: python run.py  (production: use a WSGI server, see docs/SECURITY.md)."""
import os
from pathlib import Path


def load_env_file():
    """Minimal .env loader (no extra dependency). Real environment variables take precedence."""
    for candidate in (Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"):
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.split(" #", 1)[0].strip().strip('"').strip("'")
                if value:
                    os.environ.setdefault(key.strip(), value)
            break


load_env_file()
from docmind.app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")), threaded=True)
