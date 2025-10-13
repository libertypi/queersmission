# Queersmission

*Queer's mission… is to help Transmission.*

**Queersmission** is a [custom script](https://github.com/transmission/transmission/blob/main/docs/Scripts.md) for the [Transmission](https://transmissionbt.com/) BitTorrent client. It maintains a dedicated **seeding space** and copies completed downloads to user-chosen destinations. This keeps sharing alive even if you delete your personal copy — ideal for Private Torrent (PT) users who must maintain ratio.

> **Runtime:** Python 3.8+  
> **Target:** transmission-daemon with RPC enabled

## Features

- **Smart storage management** — Enforces `seed-dir` quotas/reserves and removes the least valuable finished torrents first.
- **Smart categorization** — Classifies to `movies`, `tv-shows`, `music`, `av`, or `default`. Uses sophisticated regular expressions powered by [regen](https://github.com/libertypi/regen) and large real-world data.
- **Shallow copy (CoW)** — On CoW filesystems (e.g., Btrfs), copies are instant and space-efficient.

## How it runs

Configure Queersmission as **both**:
- `script-torrent-added` — handles storage management on add.
- `script-torrent-done` — performs post-download copying.

Use the **same directory** for:
- Transmission `download-dir`
- Queersmission `seed-dir`

This keeps seeding data canonical and manageable.

## Transmission settings

Stop `transmission-daemon`, then edit `settings.json`.  
On Synology NAS it is often at: `/volume1/@appdata/transmission/settings.json`.  
Default locations for other systems: [Configuration Files](https://github.com/transmission/transmission/blob/main/docs/Configuration-Files.md).

Set **all** of the following:

```json
"rpc-enabled": true,
"download-dir": "/path_to/seed-dir",
"script-torrent-added-enabled": true,
"script-torrent-added-filename": "/path_to/queersmission/torrent-added.py",
"script-torrent-done-enabled": true,
"script-torrent-done-filename": "/path_to/queersmission/torrent-done.py"
````

## First run & config

After enabling RPC and scripts, run `torrent-done.py` **once** manually to generate `config.json` (created blank in the Queersmission directory). Edit it.

### `config.json` template

```json
{
  "log-level": "INFO",
  "public-upload-limit-kbps": 0,
  "remove-public-on-complete": false,
  "rpc-path": "/transmission/rpc",
  "rpc-port": 9091,
  "rpc-username": "",
  "rpc-password": "",
  "seed-dir-purge": false,
  "seed-dir-quota-gib": 0,
  "seed-dir-reserve-space-gib": 0,
  "seed-dir": "",
  "watch-dir": "",
  "dest-dir-default": "",
  "dest-dir-movies": "",
  "dest-dir-tv-shows": "",
  "dest-dir-music": "",
  "dest-dir-av": ""
}
```

### Keys

* **log-level** (string, default `INFO`): `DEBUG` | `INFO` | `WARNING` | `ERROR` | `CRITICAL`.
* **public-upload-limit-kbps** (int, default `0`): Max upload for **public** torrents in KB/s. `0` disables limiting.
* **remove-public-on-complete** (bool, default `false`): If `true`, remove public torrents when they finish; only private torrents continue seeding.
* **rpc-path** (string, default `/transmission/rpc`)
* **rpc-port** (number, default `9091`)
* **rpc-username**, **rpc-password** (strings): Password is obfuscated after first read.
* **seed-dir-purge** (bool, default `false`): If `true`, delete **any file** in `seed-dir` not known to Transmission.
  **Warning:** Do not store personal files in `seed-dir` when this is on.
* **seed-dir-quota-gib** (int, default `0`): Upper size limit for `seed-dir` in GiB. `0` disables.
* **seed-dir-reserve-space-gib** (int, default `0`): Minimum free space to keep in GiB. `0` disables.
* **seed-dir** (string): Canonical seeding location. Should equal Transmission’s `download-dir`. If empty, Queersmission can read it from Transmission.
* **watch-dir** (string): Transmission’s `watch-dir`. If set, old/empty `.torrent` files are cleaned up.
* **dest-dir-* ** (strings): Post-copy destinations.

  * **Required:** `dest-dir-default`
  * Optional (fallback to default if empty): `dest-dir-movies`, `dest-dir-tv-shows`, `dest-dir-music`, `dest-dir-av`

## Notes on Windows

Windows’ Transmission service runs as **Local Service**, which may not read your home directory, Python, or Queersmission files. Ensure the service account can access:

* The Python interpreter
* The Queersmission directory
* The destination and seed directories

Windows Transmission won’t invoke `.py` directly. Create two `.bat` wrappers that call:

* `torrent-added.py`
* `torrent-done.py`

Then point the corresponding `settings.json` script paths to those `.bat` files.

## Author

* **David Pi**
