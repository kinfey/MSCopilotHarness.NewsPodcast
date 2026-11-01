"""Prepare the static website and server-only credentials; never print secrets."""

import json
import os
import secrets
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
AZD_ENV = {**os.environ, "AZURE_DEV_USER_AGENT": "microsoft_foundry_skill"}


def run(*args, json_output=False):
    result = subprocess.run(
        args, cwd=ROOT, env=AZD_ENV, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} {args[1]} failed (exit {result.returncode}); inspect Azure permissions"
        )
    return json.loads(result.stdout) if json_output else result.stdout.strip()


def set_env(key, value):
    run("azd", "env", "set", key, value)


def main():
    env = run("azd", "env", "get-values", "--output", "json", json_output=True)
    # Extension versions can return either JSON object or key-value records.
    if not isinstance(env, dict):
        raise TypeError("Expected azd environment JSON object")
    project_id = env["AZURE_AI_PROJECT_ID"]
    parts = project_id.split("/")
    account = parts[parts.index("accounts") + 1]
    project_rg = parts[parts.index("resourceGroups") + 1]
    location = env["AZURE_LOCATION"]
    storage_rg = f"rg-{env['AZURE_ENV_NAME']}-foundry"
    run(
        "az",
        "group",
        "create",
        "--name",
        storage_rg,
        "--location",
        location,
        "-o",
        "none",
    )
    name = env.get("NEWS_STORAGE_NAME") or "meridian24" + secrets.token_hex(4)
    set_env("NEWS_STORAGE_NAME", name)
    account_info = run(
        "az",
        "storage",
        "account",
        "create",
        "--name",
        name,
        "--resource-group",
        storage_rg,
        "--location",
        location,
        "--sku",
        "Standard_LRS",
        "--kind",
        "StorageV2",
        "--min-tls-version",
        "TLS1_2",
        "--allow-blob-public-access",
        "false",
        "--https-only",
        "true",
        "-o",
        "json",
        json_output=True,
    )
    connection = run(
        "az",
        "storage",
        "account",
        "show-connection-string",
        "--name",
        name,
        "--resource-group",
        storage_rg,
        "--query",
        "connectionString",
        "-o",
        "tsv",
    )
    # SDK connection-string auth is server-side only, never copied to $web.
    child_env = {**AZD_ENV, "AZURE_STORAGE_CONNECTION_STRING": connection}

    def storage(*args):
        result = subprocess.run(
            ["az", "storage", *args, "-o", "none"],
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Storage setup failed; check storage network policy")

    storage(
        "blob",
        "service-properties",
        "update",
        "--static-website",
        "--index-document",
        "index.html",
        "--404-document",
        "index.html",
    )
    storage("container", "create", "--name", "broadcasts", "--public-access", "off")
    storage(
        "blob",
        "upload-batch",
        "--destination",
        "$web",
        "--source",
        "web",
        "--overwrite",
        "--content-cache-control",
        "no-cache",
    )
    speech_key = run(
        "az",
        "cognitiveservices",
        "account",
        "keys",
        "list",
        "--name",
        account,
        "--resource-group",
        project_rg,
        "--query",
        "key1",
        "-o",
        "tsv",
    )
    webiq_key = dotenv_values(ROOT / ".env").get("WEBIQ_API_KEY") or env.get(
        "WEBIQ_API_KEY"
    )
    if not webiq_key:
        raise RuntimeError("WEBIQ_API_KEY must be supplied in the ignored .env file")
    values = {
        "STORAGE_CONNECTION_STRING": connection,
        "STORAGE_ACCOUNT_URL": account_info["primaryEndpoints"]["blob"],
        "WEBSITE_URL": account_info["primaryEndpoints"]["web"],
        "WEBIQ_API_KEY": webiq_key,
        "SPEECH_KEY": speech_key,
        "SPEECH_REGION": location,
    }
    for key, value in values.items():
        set_env(key, value)
    print(f"Static website ready: {values['WEBSITE_URL']}")
    print(
        "Server-only secrets stored in the ignored azd environment; no secrets uploaded to the website."
    )


if __name__ == "__main__":
    main()
