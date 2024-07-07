# Queersmission

*Queer's mission... is to help Transmission.*

**Queersmission** is a [custom script](https://github.com/transmission/transmission/blob/main/docs/Scripts.md) for the [Transmission](https://transmissionbt.com/) Bittorrent client. It manages a dedicated seeding space and copies completed downloads to user-specified locations. This ensures that file sharing continues, even if the user deletes the content, which is useful for Private Torrent (PT) users who need to maintain a sharing ratio.

### Features

- **Smart Torrent Categorization**: Categorizes downloads into `movies`, `tv-shows`, `music`, `av`, and `default`. Each category can be directed to specific locations. It utilizes the sophisticated regular expressions powered by [regen](https://github.com/libertypi/regen), and millions of real world data.

- **Shallow Copy**: Utilizes copy-on-write (CoW) on file systems like Btrfs to perform lightweight copies. Data blocks are only duplicated when modified. Copies do not take double space and are instant.

- **Automatic Storage Management**: Manages space in the `seed-dir` by removing the least active torrents based on quota settings.

### Usage

Queersmission is designed to be run as a `script-torrent-added` to perform storage management, and a `script-torrent-done` to perform post-download copying.

The dedicated seeding space should be set as both `download-dir` in Transmission's `settings.json`, and `seed-dir` in Queersmision's `config.json`.

After stopping the Transmission daemon, edit its `settings.json`. On a Synology NAS, this file may be located at `/volume1/@appdata/transmission/settings.json`. Default locations on other platforms can be found [here](https://github.com/transmission/transmission/blob/main/docs/Configuration-Files.md). 

**These settings in Transmission's `settings.json` must be set correctly:**

```json
"rpc-enabled": true,
"download-dir": "/path_to/seed-dir",
"script-torrent-added-enabled": true,
"script-torrent-added-filename": "/path_to/queersmission/torrent-added.py",
"script-torrent-done-enabled": true,
"script-torrent-done-filename": "/path_to/queersmission/torrent-done.py",
```

### Configuration

After setting up transmission-daemon, you should manually run `torrent-done.py` or `torrent-added.py` once to generate the configuration file. Upon the first run, a blank `config.json` will be created in the queersmission directory. Edit the config file to get started.

Template:

```json
{
    "log-level": "INFO",
    "only-seed-private": false,
    "rpc-url": "/transmission/rpc",
    "rpc-port": 9091,
    "rpc-username": "",
    "rpc-password": "",
    "seed-dir-purge": false,
    "seed-dir-size-limit-gb": 0,
    "seed-dir-space-floor-gb": 0,
    "seed-dir": "",
    "watch-dir": "",
    "destinations": {
        "default": "",
        "movies": "",
        "tv-shows": "",
        "music": "",
        "av": ""
    }
}
```

- **log-level**: String (default = INFO). Possible values are "DEBUG", "INFO", "WARNING", "ERROR", and "CRITICAL".

- **only-seed-private**: Boolean (default = false). Only seed private torrents. Public torrents will be removed from Transmission immediately after the download completes.

- **rpc-url**: String (default = /transmission/rpc)

- **rpc-port**: Number (default = 9091)

- **rpc-username**: String.

- **rpc-password**: String. Queersmission will obfuscate and rewrite this field after its first read.

- **seed-dir-purge**: Boolean (default = false). When enabled, removes all files from the `seed-dir` that are not in Transmission's downloads list. **Avoid storing personal or unrelated files in the `seed-dir`, as they will be automatically deleted when this option is active!**

- **seed-dir-size-limit-gb**: Integer (default = 0). Sets the maximum allowed size (in gigabytes) of the seed-dir. If the total size of the files exceeds this limit, the script will remove inactive completed torrents to free up space. Set to 0 to disable.

- **seed-dir-space-floor-gb**: Integer (default = 0). Specifies a minimum free space threshold (in gigabytes) for the seed-dir. Set to 0 to disable.

- **seed-dir**: String. The default download location, used as the dedicated seeding location. This setting should be identical to Transmission's `download-dir`. If not set, the script may make an additional API call to read the setting.

- **watch-dir**: String. Path to Transmission's `watch-dir`. When set, old or empty ".torrent" files will be cleared from this directory.

- **destinations:** Object. Specifies paths where categorized files should be copied after download completion. Entries include: `default`, `movies`, `tv-shows`, `music`, and `av`. The `default` must be a valid directory, and others can be left empty to use the default value.

### Notes on Windows

While Queersmission is designed for and tested on both Linux and Windows systems, setting up custom script for Windows Transmission can be tricky. The Transmission daemon is configured to run under the Local Service account. This is a limited account that may not have access to all files on your disk, including your home directory, the Python executable, and the Queersmission script. You have to make sure these files are accessable to the daemon. Also, Windows Transmission will not call a ".py" script. You need to create two ".bat" entry scripts that call `torrent-added.py` and `torrent-done.py` respectively, and point the settings in Transmission's `settings.json` to these .bat files.

### Author

- David Pi
