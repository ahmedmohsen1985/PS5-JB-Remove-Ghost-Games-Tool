#!/usr/bin/env python3
"""
PS5 Ghost Game Remover

Removes a stuck/ghost PS5 game by editing the console's app databases directly.
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

DBS_TO_CLEAN = {
    "app.db": "/system_data/priv/mms/app.db",
    "appinfo.db": "/system_data/priv/mms/appinfo.db",
    "bgft.db": "/system_data/priv/mms/bgft.db",
}


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


def remove_title_from_db(db_path, title_id):
    """Remove all rows referencing the given title ID from a SQLite database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    local_concept_id = f"cid:local:{title_id}"
    info_key = f"nsx_content_flag_{title_id}"

    tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
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
            if "title_id" in cols:
                cur.execute(f"DELETE FROM {table} WHERE title_id = ?", (title_id,))
                deleted += cur.rowcount
            if "localConceptId" in cols:
                cur.execute(
                    f"DELETE FROM {table} WHERE localConceptId = ?", (local_concept_id,)
                )
                deleted += cur.rowcount
            if "local_concept_id" in cols:
                cur.execute(
                    f"DELETE FROM {table} WHERE local_concept_id = ?", (local_concept_id,)
                )
                deleted += cur.rowcount
            if "key" in cols:
                cur.execute(f"DELETE FROM {table} WHERE key = ?", (info_key,))
                deleted += cur.rowcount
            if "group_id" in cols:
                cur.execute(f"DELETE FROM {table} WHERE group_id = ?", (title_id,))
                deleted += cur.rowcount
            if "content_id" in cols:
                cur.execute(
                    f"DELETE FROM {table} WHERE content_id LIKE ?",
                    (f"%-{title_id}_%",),
                )
                deleted += cur.rowcount
            if "CONTENT_ID" in cols:
                cur.execute(
                    f"DELETE FROM {table} WHERE CONTENT_ID LIKE ?",
                    (f"%-{title_id}_%",),
                )
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


def clean_database(base_url, console, title_id, db_name, db_remote_path, local_work_dir, backup_dir):
    """Download, edit, upload, and replace one system database."""
    remote_tmp_name = f"ghostremover_{db_name}.tmp"
    remote_tmp = f"/data/{remote_tmp_name}"
    remote_modified = f"/data/ghostremover_{db_name}.modified"
    # transfer/download lands the file under its remote basename inside dest_dir
    local_tmp = os.path.join(local_work_dir, remote_tmp_name)

    print(f"\n--- Cleaning {db_name} ---")

    # Backup
    backup_name = f"{backup_dir}/{db_name}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shell_run(base_url, console, f"cp {db_remote_path} {backup_name}")
    print(f"  Backed up to {backup_name}")

    # Copy to downloadable location
    shell_run(base_url, console, f"cp {db_remote_path} {remote_tmp}")

    # Download
    download_file(base_url, console, remote_tmp, local_work_dir)
    print(f"  Downloaded to {local_tmp}")

    # Edit
    deleted = remove_title_from_db(local_tmp, title_id)
    print(f"  Rows removed: {deleted}")

    # Upload
    upload_file(base_url, console, local_tmp, remote_modified)
    print(f"  Uploaded modified {db_name}")

    # Replace
    shell_run(base_url, console, f"cp {remote_modified} {db_remote_path}")
    shell_run(base_url, console, f"chmod 644 {db_remote_path}")
    print(f"  Replaced {db_remote_path}")

    # Cleanup remote temp
    shell_run(base_url, console, f"rm -f {remote_tmp} {remote_modified}")

    return deleted


def delete_folder_shell(base_url, console, folder_path):
    """Delete a folder using relative-path workaround for protected system paths."""
    parent = os.path.dirname(folder_path)
    name = os.path.basename(folder_path)
    try:
        shell_run(base_url, console, f"cd {parent} && rm -rf {name}")
        return True
    except Exception as e:
        print(f"  Warning: could not delete {folder_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Hard-remove a stuck PS5 game by cleaning system databases."
    )
    parser.add_argument("title_id", help="Title ID to remove, e.g. PPSA99078")
    parser.add_argument(
        "--console",
        help="PS5 address (default: first known console)",
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
        help="Skip creating backups of system databases on the console",
    )
    parser.add_argument(
        "--keep-saves",
        action="store_true",
        help="Keep save-data folders (delete only app metadata)",
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
    print("\n[1/4] Checking app database for the title...")
    if not title_in_appdb(base_url, console, title_id):
        print(f"  {title_id} is not in the main app database.")
    else:
        print(f"  {title_id} found in main app database.")

    # Setup local work dir
    local_work_dir = tempfile.mkdtemp(prefix="ps5_ghost_remover_")
    backup_dir = "/data/ghostremover_backups"

    try:
        # Create backup dir on console
        if not args.skip_backup:
            shell_run(base_url, console, f"mkdir -p {backup_dir}")

        # Clean each database
        total_db_rows = 0
        for db_name, db_remote_path in DBS_TO_CLEAN.items():
            try:
                if args.skip_backup:
                    # still do per-db temp copies, just no persistent backup
                    deleted = clean_database(
                        base_url, console, title_id, db_name, db_remote_path, local_work_dir, "/data"
                    )
                else:
                    deleted = clean_database(
                        base_url, console, title_id, db_name, db_remote_path, local_work_dir, backup_dir
                    )
                total_db_rows += deleted
            except Exception as e:
                print(f"  ERROR cleaning {db_name}: {e}")
                raise

        print(f"\n[2/4] Total database rows removed: {total_db_rows}")

        # Delete leftover folders
        print("\n[3/4] Removing leftover folders...")
        folders_to_delete = [
            f"/user/app/{title_id}",
            f"/user/appmeta/{title_id}",
            f"/system_data/priv/appmeta/{title_id}",
            f"/system_data/httpcache/nobackup/{title_id}",
        ]

        if not args.keep_saves:
            # Find save data folders for all users
            try:
                result = shell_run(
                    base_url,
                    console,
                    f"find /user/home -type d -name {title_id}",
                    timeout_s=30,
                )
                lines = result.get("stdout", "").strip().splitlines()
                for line in lines:
                    line = line.strip()
                    if line and not line.endswith(":"):
                        folders_to_delete.append(line)
            except Exception as e:
                print(f"  Warning: could not find save folders: {e}")
        else:
            print("  --keep-saves set: save data folders will be kept.")

        for folder in folders_to_delete:
            delete_folder_shell(base_url, console, folder)

        # Delete icon caches
        try:
            shell_run(
                base_url,
                console,
                f"cd /data/shadowmount/icon-cache && rm -f {title_id}*",
                timeout_s=30,
            )
            print("  Deleted shadowmount icon caches")
        except Exception as e:
            print(f"  Warning: could not delete icon caches: {e}")

        # Verify
        print("\n[4/4] Verifying...")
        time.sleep(1)
        if title_in_appdb(base_url, console, title_id):
            print("  WARNING: title still appears in main app database.")
        else:
            print(f"  OK: {title_id} is not in the main app database.")

        print("\nDone.")
        print("If the tile is still on the PS5 home screen, restart the console.")

    finally:
        shutil.rmtree(local_work_dir)


if __name__ == "__main__":
    main()
