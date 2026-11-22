# PS5 Ghost Game Remover

A Python tool that fully removes a stuck/ghost PS5 game when the normal uninstall fails (for example with error `0x80B21B02`).

It cleans:
- `app.db` — main app database
- `appinfo.db` — app metadata database
- `bgft.db` — background download/install task database
- Leftover folders in `/user/app/`, `/user/appmeta/`, `/system_data/priv/appmeta/`, `/system_data/httpcache/nobackup/`
- ShadowMount icon caches in `/data/shadowmount/icon-cache/`
- Save-data folders (unless you use `--keep-saves`)

## What you need

- Python 3.x installed on this computer
- PS5Upload engine running
- A jailbroken PS5 already added to PS5Upload

## How to use

1. Open PowerShell or Command Prompt.
2. Go to this folder:

   ```powershell
   cd "$env:USERPROFILE\Desktop\PS5_Ghost_Game_Remover"
   ```

3. Run the script with the Title ID you want to remove:

   ```powershell
   python remove_ghost_game.py PPSA99078
   ```

   Replace `PPSA99078` with the actual Title ID of the stuck game.

4. The script will:
   - Back up the three system databases on the console
   - Download them to this computer
   - Remove every database row for that Title ID
   - Upload the cleaned databases back to the PS5
   - Replace the originals
   - Delete leftover app/meta/icon-cache folders
   - Verify the Title ID is gone from the main app database

## Optional flags

```powershell
# Use a specific PS5 (if you have more than one)
python remove_ghost_game.py PPSA99078 --console 192.168.1.4

# Use a different PS5Upload engine URL/port
python remove_ghost_game.py PPSA99078 --engine http://127.0.0.1:19113

# Skip database backups on the console (not recommended)
python remove_ghost_game.py PPSA99078 --skip-backup

# Keep save-data folders
python remove_ghost_game.py PPSA99078 --keep-saves
```

## Important warnings

- **This edits system databases.** A wrong Title ID will remove a different game.
- **Always double-check the Title ID** before pressing Enter.
- Backups of the three databases are automatically created on the console under `/data/ghostremover_backups/`.
- If something goes wrong, you can restore a backup by copying it back, for example:

  ```text
  cp /data/ghostremover_backups/app.db.backup_YYYYMMDD_HHMMSS /system_data/priv/mms/app.db
  chmod 644 /system_data/priv/mms/app.db
  ```

## After running

The game tile may still appear on the PS5 home screen until the UI refreshes. If it does not disappear on its own, restart the console.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `No PS5 consoles known to PS5Upload` | Make sure the PS5Upload app/engine is running and the PS5 is listed. |
| `Failed to connect` | Check that the PS5Upload engine is running and the URL/port is correct (default: `http://127.0.0.1:19113`). |
| Title still shows on home screen | Restart the PS5 to refresh the UI. |
| Home screen looks wrong | Restore the database backups from `/data/ghostremover_backups/` using the PS5Upload shell. |

## Files in this folder

- `remove_ghost_game.py` — the remover script
- `README.md` — this file
