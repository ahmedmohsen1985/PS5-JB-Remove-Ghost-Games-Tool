# PS5 Ghost Game Remover

A small Python tool that hard-removes a stuck PS5 game when the normal uninstall fails (for example with error `0x80B21B02`).

It works by editing the PS5's app database (`/system_data/priv/mms/app.db`) directly, the same way we fixed `PPSA99078` manually.

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
   - Check that the game is still in the PS5 app database
   - Back up the original `app.db` on the console to `/data/app.db.backup_YYYYMMDD_HHMMSS`
   - Download the database to this computer
   - Remove every database row for that Title ID
   - Upload the cleaned database back to the PS5
   - Replace the original `app.db`
   - Delete leftover folders `/user/app/<TITLE_ID>` and `/user/appmeta/<TITLE_ID>`
   - Verify the Title ID is gone

## Optional flags

```powershell
# Use a specific PS5 (if you have more than one)
python remove_ghost_game.py PPSA99078 --console 192.168.1.4

# Use a different PS5Upload engine URL/port
python remove_ghost_game.py PPSA99078 --engine http://127.0.0.1:19113

# Skip the automatic backup on the console (not recommended)
python remove_ghost_game.py PPSA99078 --skip-backup
```

## Important warnings

- **This edits a system database.** A wrong Title ID will remove a different game.
- **Always double-check the Title ID** before pressing Enter.
- A backup of `app.db` is automatically created on the console before any changes.
- If something goes wrong, you can restore the backup by copying it back:

  ```text
  cp /data/app.db.backup_YYYYMMDD_HHMMSS /system_data/priv/mms/app.db
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
| Home screen looks wrong | Restore the `app.db` backup from `/data/` using the PS5Upload shell. |

## Files in this folder

- `remove_ghost_game.py` — the remover script
- `README.md` — this file
