import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobServiceClient

from station import retention


class BlobStore:
    def __init__(self, client: BlobServiceClient, credential=None):
        self.client = client
        self.credential = credential
        self.private = client.get_container_client("broadcasts")
        self.web = client.get_container_client("$web")

    @classmethod
    def from_env(cls):
        connection = os.environ.get("STORAGE_CONNECTION_STRING")
        if connection:
            return cls(BlobServiceClient.from_connection_string(connection))
        credential = DefaultAzureCredential()
        return cls(BlobServiceClient(os.environ["STORAGE_ACCOUNT_URL"], credential=credential), credential)

    async def close(self):
        await self.client.close()
        if self.credential:
            await self.credential.close()

    def blob(self, name: str, public=False):
        return (self.web if public else self.private).get_blob_client(name)

    async def get_bytes(self, name: str, public=False) -> bytes | None:
        try:
            return await (await self.blob(name, public).download_blob()).readall()
        except ResourceNotFoundError:
            return None

    async def get_json(self, name: str, public=False) -> dict | None:
        raw = await self.get_bytes(name, public)
        return json.loads(raw) if raw is not None else None

    async def put_bytes(self, name: str, data: bytes, content_type: str, public=False, immutable=False):
        day = retention.blob_day(name)
        if day is not None:
            # Share the publication fence with cleanup: an upload started before
            # midnight cannot commit behind a completed deletion sweep.
            async with self.lock("publication"):
                if day != retention.today_key():
                    raise retention.BroadcastExpiredError("Refuse to recreate an expired broadcast Blob")
                await self._upload(name, data, content_type, public, immutable)
        else:
            await self._upload(name, data, content_type, public, immutable)

    async def _upload(self, name, data, content_type, public, immutable):
        try:
            await self.blob(name, public).upload_blob(
                data,
                overwrite=not immutable,
                content_settings=ContentSettings(
                    content_type=content_type,
                    cache_control="no-store"
                    if name.endswith(".mp4")
                    else ("no-cache" if name.endswith(".json") else "public,max-age=86400"),
                ),
            )
        except ResourceExistsError:
            if not immutable:
                raise

    async def put_json(self, name: str, data: dict, public=False, immutable=False):
        await self.put_bytes(
            name, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", public, immutable
        )

    @asynccontextmanager
    async def lock(self, name: str):
        blob = self.blob(f"locks/{name}.lock")
        try:
            await blob.upload_blob(b"", overwrite=False)
        except ResourceExistsError:
            pass
        # A finite renewable lease is released on graceful exit and expires after process loss.
        deadline = time.monotonic() + 600
        while True:
            try:
                lease = await blob.acquire_lease(lease_duration=60)
                break
            except HttpResponseError as exc:
                if name != "publication" or exc.error_code != "LeaseAlreadyPresent" or time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(1)

        async def renew():
            while True:
                await asyncio.sleep(20)
                await lease.renew()

        renewal = asyncio.create_task(renew())
        try:
            yield renewal
            if renewal.done():
                renewal.result()
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
            await lease.release()

    async def publish(self, edition: dict):
        catalog = "data/manual-catalog.json" if edition.get("publication_trigger") == "manual" else "data/catalog.json"
        async with self.lock("publication"):
            retention.require_current(datetime.fromisoformat(edition["slot"]))
            feed = await self.get_json(catalog, public=True) or {"editions": []}
            editions = {
                item["id"]: item
                for item in feed["editions"]
                if retention.slot_day(datetime.fromisoformat(item["slot"])) == retention.today_key()
            }
            editions[edition["id"]] = edition
            ordered = sorted(editions.values(), key=lambda x: x["slot"], reverse=True)
            # This single JSON commit reveals both language versions at once.
            await self.put_json(catalog, {"editions": ordered}, public=True)

    async def list_names(self, prefix: str, public=False):
        seen = set()
        async for blob in (self.web if public else self.private).list_blobs(
            name_starts_with=prefix, include=["versions"]
        ):
            if blob.name not in seen:
                seen.add(blob.name)
                yield blob.name

    async def delete(self, name: str, public=False):
        try:
            await self.blob(name, public).delete_blob(delete_snapshots="include")
        except ResourceNotFoundError:
            pass
        container = self.web if public else self.private
        # Versioning can retain prior versions even after deleting the base Blob.
        async for version in container.list_blobs(name_starts_with=name, include=["versions"]):
            if version.name == name and version.version_id:
                try:
                    await container.delete_blob(name, version_id=version.version_id)
                except ResourceNotFoundError:
                    pass

    async def cleanup_day(self) -> dict:
        async with self.lock("publication"):
            day = retention.today_key()
            removed = {"public": 0, "private": 0}
            for catalog in ("data/catalog.json", "data/manual-catalog.json"):
                feed = await self.get_json(catalog, public=True) or {"editions": []}
                editions = [e for e in feed["editions"] if retention.slot_day(datetime.fromisoformat(e["slot"])) == day]
                await self.put_json(
                    catalog,
                    {"editions": editions, "retention": {"day": day, "time_zone": "Asia/Shanghai"}},
                    public=True,
                )
            for public, prefixes in (
                (True, ("media/cn/", "media/en/")),
                (False, ("jobs/", "cn/", "en/", "retired/", "invocations/")),
            ):
                for prefix in prefixes:
                    async for name in self.list_names(prefix, public):
                        date = retention.blob_day(name)
                        if prefix == "invocations/":
                            value = await self.get_json(name)
                            date = retention.slot_day(datetime.fromisoformat(value["slot"])) if value else None
                        if date is not None and date < day:
                            await self.delete(name, public)
                            removed["public" if public else "private"] += 1
            result = {"status": "completed", "output": {"day": day, "time_zone": "Asia/Shanghai", "deleted": removed}}
            await self.put_json("maintenance/retention.json", result)
            return result
