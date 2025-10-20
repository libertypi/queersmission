# Queersmission

*Queer's mission… is to help Transmission.*

**Queersmission** is a [custom script](https://github.com/transmission/transmission/blob/main/docs/Scripts.md) for the [Transmission](https://transmissionbt.com/) BitTorrent client. It was primarily designed for users of **Private Torrent (PT)** trackers or those who need to maintain a good upload ratio. It maintains a dedicated **seeding space** and copies completed downloads to user-chosen destinations. This keeps sharing alive even if you delete your personal copy.

> **Runtime:** Python 3.8+  
> **Target:** transmission-daemon with RPC enabled

## Features

- **Smart storage management** — Enforces `seed-dir` quotas/reserves and removes the least valuable finished torrents when necessary. Maintains a healthy swarm and your seeding ratio.
- **Public torrent upload limiting** — Limit upload speed for public torrents, and remove them when they finish.
- **Smart categorization** — Automatically classifies torrents to `movies`, `tv-shows`, `music`, `av`, or `default`, and copies them to corresponding destinations after download. Powered by [regen](https://github.com/libertypi/regen) and large real-world data.
- **Shallow copy (CoW)** — On CoW filesystems (e.g., Btrfs), copies are instant and space-efficient.

## How it runs

Configure Queersmission as **both**:
- `script-torrent-added` — handles storage management on add.
- `script-torrent-done` — performs post-download copying.

Use the **same directory** for:
- Transmission `download-dir`
- Queersmission `seed-dir`

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

After enabling RPC and scripts, run `torrent-done.py` once manually to generate `profile/config.json` (created blank in the program directory). Edit it.

### `config.json` template

```json
{
  "log-level": "INFO",
  "public-upload-limited": false,
  "public-upload-limit-kbps": 20,
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
* **public-upload-limited** (bool, default `false`): If `true`, limit upload speed for **public** torrents.
* **public-upload-limit-kbps** (int, default `20`): Max upload speed per **public** torrents (kB/s).
* **remove-public-on-complete** (bool, default `false`): If `true`, remove public torrents when they finish; only private torrents continue seeding.
* **rpc-path** (string, default `/transmission/rpc`)
* **rpc-port** (number, default `9091`)
* **rpc-username** (string)
* **rpc-password** (string): Password is obfuscated after first read.
* **seed-dir-purge** (bool, default `false`): If `true`, delete **any file** in `seed-dir` not associated with Transmission.
  **Warning:** Do not store personal files in `seed-dir` when this is on.
* **seed-dir-quota-gib** (int, default `0`): Maximum size limit for all the torrents in `seed-dir` (GiB). Set to `0` to disable.
* **seed-dir-reserve-space-gib** (int, default `0`): Minimum free space to keep in `seed-dir` (GiB). Set to `0` to disable.
* **seed-dir** (string): Transmission’s `download-dir`. If not set, Queersmission can read it from Transmission.
* **watch-dir** (string): Transmission’s `watch-dir`. Transmission sometimes fails to delete old/empty `.torrent` files in watch-dir when `trash-original-torrent-files` is enabled. Queersmission will clean them up if this is set.
* **dest-dir-* ** (strings): Post-download copying destinations.

  * **Required:** `dest-dir-default`: The default destination where finished torrents are copied.
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
