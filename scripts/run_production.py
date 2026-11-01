"""Run or resume the exact production pipeline locally, using the private azd environment."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/resilient-research"))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--slot",
        help="Beijing ISO timestamp aligned to :00 or :30; defaults to current slot",
    )
    parser.add_argument("--check-services", action="store_true")
    args = parser.parse_args()
    result = await asyncio.to_thread(
        subprocess.run,
        ["azd", "env", "get-values", "--output", "json"],
        cwd=ROOT,
        env={**os.environ, "AZURE_DEV_USER_AGENT": "microsoft_foundry_skill"},
        check=True,
        capture_output=True,
        text=True,
    )
    env = json.loads(result.stdout)
    os.environ.update({key: str(value) for key, value in env.items()})
    from station.pipeline import produce
    from station.storage import BlobStore
    from station.timeutil import current_slot, parse_slot

    store = BlobStore.from_env()
    try:
        if args.check_services:
            from station.audio import synthesize
            from station.news import collect

            package = await collect()
            print(
                "Fresh agency evidence:",
                len(package["evidence"]),
                "Source gaps:",
                package["missing_agencies"],
            )
            for language, text in (
                ("cn", "这是语音接口验证。"),
                ("en", "This is a speech service check."),
            ):
                for speaker in ("male", "female"):
                    wav = await synthesize(text, language, speaker)
                    print("Verified voice:", language, speaker, "WAV bytes:", len(wav))
            return
        slot = parse_slot(args.slot) if args.slot else current_slot()
        if slot > current_slot():
            raise ValueError("Cannot generate a future slot")
        await store.cleanup_day()
        result = await produce(store, slot)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
