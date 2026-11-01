"""Upload only the public frontend files, preserving generated audio and catalogue."""

import asyncio
import json
import mimetypes
import os
import subprocess
import sys
from pathlib import Path

from azure.storage.blob import ContentSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/resilient-research"))


async def main():
    result = await asyncio.to_thread(
        subprocess.run,
        ["azd", "env", "get-values", "--output", "json"],
        cwd=ROOT,
        env={**os.environ, "AZURE_DEV_USER_AGENT": "microsoft_foundry_skill"},
        check=True,
        capture_output=True,
        text=True,
    )
    os.environ.update(
        {key: str(value) for key, value in json.loads(result.stdout).items()}
    )
    from station.storage import BlobStore

    store = BlobStore.from_env()
    try:
        for path in (ROOT / "web").iterdir():
            if path.suffix in (".html", ".css", ".js"):
                mime = (
                    "application/javascript"
                    if path.suffix == ".js"
                    else mimetypes.guess_type(path.name)[0]
                )
                await store.web.upload_blob(
                    path.name,
                    path.read_bytes(),
                    overwrite=True,
                    content_settings=ContentSettings(
                        content_type=mime + "; charset=utf-8", cache_control="no-cache"
                    ),
                )
        print(os.environ["WEBSITE_URL"])
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
