#!/usr/bin/env python3
"""
PS5 Ghost Game Remover

Removes a stuck/ghost PS5 game by editing the console's app database directly.
Use this when the normal uninstall fails with errors like 0x80B21B02.

Requires:
    - Python 3.x
    - PS5Upload engine running on this computer
    - A jailbroken PS5 reachable by PS5Upload
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import urllib.request
import urllib.error


DEFAULT_ENGINE_URL = "http://127.0.0.1:19113"
APP_DB_PATH = "/system_data/priv/mms/app.db"


def api_request(base_url, method, path, body=None):
    """Make a JSON request to the PS5Upload engine API."""
    url = urljoin(base_url, path)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8")
        try:
            err_body = json.loads(body_text)
        except json.JSONDecodeError:
            err_body = {"error": body_text}
        return e.code, err_body
    except Exception as e:
        return -1, {"error": str(e)}


def get_console_list(base_url):
    """Get the list of known PS5 consoles from the engine."""
    status, data = api_request(base_url, "GET", "/api/consoles")
    if status != 200:
        raise RuntimeError(f"Failed to list consoles: {data}")
    return data


def pick_console(base_url, console_addr=None):
    """Pick a console. If not specified, use the first known console."""
    if console_addr:
        return console_addr

    consoles = get_console_list(base_url)
    items = consoles.get("consoles", [])
    if not items:
        raise RuntimeError("No PS5 consoles known to PS5Upload. Add one first.")
    return items[0]["host"]


def shell_run(base_url, console, cmd, timeout_s=60):
    """Run a shell command on the PS5 via PS5Upload."""
    status, data = api_request(
        base_url,
        "POST",
        "/api/ps5/shell/run",
        {"addr": console, "cmd": cmd, "timeout_s": timeout_s},
    )
    if status != 200:
        raise RuntimeError(f"Shell command failed: {data}")
    if data.get("exit_code", 0) != 0:
        raise RuntimeError(
            f"Shell command exited {data.get('exit_code')}: {data.get('stdout')} {data.get('err')}"
        )
    return data


def wait_for_job(base_url, job_id, timeout_s=300):
    """Poll a transfer/job until it finishes or times out."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, data = api_request(base_url, "GET", f"/api/jobs/{job_id}")
        if status != 200:
            raise RuntimeError(f"Job status check failed: {data}")

        job_status = data.get("status")
        if job_status == "done":
            return data
        if job_status == "failed":
            raise RuntimeError(f"Job failed: {data.get('error', data)}")

        time.sleep(0.5)

    raise RuntimeError(f"Job timed out after {timeout_s}s")


def download_file(base_url, console, src_path, dest_dir, kind="file"):
    """Download a file from the PS5 to this computer."""
    status, data = api_request(
        base_url,
        "POST",
        "/api/transfer/download",
        {"addr": console, "src_path": src_path, "dest_dir": dest_dir, "kind": kind},
    )
    if status != 202:
        raise RuntimeError(f"Download request failed: {data}")
    return wait_for_job(base_url, data["job_id"])


def upload_file(base_url, console, src_path, dest_path):
    """Upload a file from this computer to the PS5."""
    status, data = api_request(
        base_url,
        "POST",
        "/api/transfer/file",
        {"addr": console, "src": src_path, "dest": dest_path},
    )
    if status != 202:
        raise RuntimeError(f"Upload request failed: {data}")
    return wait_for_job(base_url, data["job_id"])


def get_tables(conn):
    """Return all table names in the SQLite database."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cur.fetchall()]


def remove_title_from_db(db_path, title_id):
    """Remove all rows referencing the given title ID from the app database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    local_concept_id = f"cid:local:{title_id}"
    info_key = f"nsx_content_flag_{title_id}"

    tables = get_tables(conn)
    total_deleted = 0

    for table in tables:
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({table})").fetchall()]
        if not cols:
            continue

        deleted = 0
        try:
            if "titleId" in cols:
                cur.execute(f"DELETE FROM {table} WHERE titleId = ?", (title_id,))
                deleted += cur.rowcount
            if "localConceptId" in cols:
                cur.execute(
                    f"DELETE FROM {table} WHERE localConceptId = ?", (local_concept_id,)
                )
                deleted += cur.rowcount
            if "key" in cols:
                cur.execute(f"DELETE FROM {table} WHERE key = ?", (info_key,))
                deleted += cur.rowcount
        except sqlite3.Error as e:
            print(f"  Warning: could not clean table {table}: {e}")

        if deleted:
            print(f"  Deleted {deleted} row(s) from {table}")
            total_deleted += deleted

    conn.commit()
    conn.close()
    return total_deleted


def title_in_appdb(base_url, console, title_id):
    """Check whether the title is still listed in the console app database."""
    status, data = api_request(
        base_url, "GET", f"/api/ps5/appdb?console={console}"
    )
    if status != 200:
        raise RuntimeError(f"Could not read appdb: {data}")
    apps = data.get("apps", [])
    return any(a.get("title_id") == title_id for a in apps)


def main():
    parser = argparse.ArgumentParser(
        description="Hard-remove a stuck PS5 game by cleaning the app database."
    )
    parser.add_argument("title_id", help="Title ID to remove, e.g. PPSA99078")
    parser.add_argument(
        "--console",
        help="PS5 address (default: engine's default console)",
        default=None,
    )
    parser.add_argument(
        "--engine",
        help="PS5Upload engine URL",
        default=DEFAULT_ENGINE_URL,
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip creating a backup of app.db on the console",
    )
    args = parser.parse_args()

    title_id = args.title_id.upper()
    if not re.fullmatch(r"[A-Z0-9]{9}", title_id):
        print(f"Warning: '{title_id}' does not look like a standard Title ID.")
        response = input("Continue anyway? (yes/no): ")
        if response.lower() != "yes":
            sys.exit(0)

    base_url = args.engine.rstrip("/")
    console = pick_console(base_url, args.console)
    print(f"Using console: {console}")
    print(f"Target title:  {title_id}")

    # Pre-check
    print("\n[1/6] Checking app database for the title...")
    if not title_in_appdb(base_url, console, title_id):
        print(f"  {title_id} is not in the app database. Nothing to do.")
        sys.exit(0)
    print(f"  {title_id} found in app database.")

    # Backup original app.db on console
    if not args.skip_backup:
        backup_name = f"/data/app.db.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"\n[2/6] Backing up app.db to {backup_name}...")
        shell_run(base_url, console, f"cp {APP_DB_PATH} {backup_name}")
        print("  Backup created.")

    # Copy app.db to a downloadable location
    remote_tmp = "/data/app_db_cleanup_tmp.db"
    print(f"\n[3/6] Copying app.db to {remote_tmp}...")
    shell_run(base_url, console, f"cp {APP_DB_PATH} {remote_tmp}")
    print("  Copied.")

    # Download to local temp dir
    print("\n[4/6] Downloading app.db to this computer...")
    local_work_dir = tempfile.mkdtemp(prefix="ps5_ghost_remover_")
    local_db_path = os.path.join(local_work_dir, "app_db_cleanup_tmp.db")
    try:
        download_file(base_url, console, remote_tmp, local_work_dir)
    except Exception as e:
        shell_run(base_url, console, f"rm -f {remote_tmp}")
        raise
    print(f"  Downloaded to {local_db_path}")

    # Edit database
    print("\n[5/6] Removing title from database...")
    deleted = remove_title_from_db(local_db_path, title_id)
    print(f"  Total rows removed: {deleted}")

    if deleted == 0:
        print("  No rows were removed. Aborting.")
        shell_run(base_url, console, f"rm -f {remote_tmp}")
        shutil.rmtree(local_work_dir)
        sys.exit(0)

    # Upload modified db
    remote_modified = "/data/app_db_cleanup_modified.db"
    print(f"\n[6/6] Uploading modified app.db to {remote_modified}...")
    upload_file(base_url, console, local_db_path, remote_modified)
    print("  Uploaded.")

    # Replace original and clean folders
    print("\nReplacing app.db on console...")
    shell_run(base_url, console, f"cp {remote_modified} {APP_DB_PATH}")
    shell_run(base_url, console, f"chmod 644 {APP_DB_PATH}")
    print("  app.db replaced.")

    print("\nRemoving leftover game folders...")
    shell_run(base_url, console, f"rm -rf /user/app/{title_id}")
    shell_run(base_url, console, f"rm -rf /user/appmeta/{title_id}")
    print("  Folders removed.")

    # Clean up remote temp files
    shell_run(base_url, console, f"rm -f {remote_tmp} {remote_modified}")

    # Verify
    print("\nVerifying...")
    time.sleep(1)
    if title_in_appdb(base_url, console, title_id):
        print("  WARNING: title still appears in app database.")
        print("  You may need to restart the PS5 for the change to take effect.")
    else:
        print(f"  SUCCESS: {title_id} is no longer in the app database.")

    # Clean local temp
    shutil.rmtree(local_work_dir)
    print("\nDone.")


if __name__ == "__main__":
    main()
