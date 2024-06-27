# Queersmission

*Queer's mission... is to help Transmission.*

**Queersmission** is a [custom script](https://github.com/transmission/transmission/blob/main/docs/Scripts.md) for the [Transmission](https://transmissionbt.com/) client. It manages a dedicated seeding space and copies completed downloads to user-specified locations. This ensures that file sharing continues, even if the user deletes the content, which is useful for Private Torrent (PT) users who need to maintain a sharing ratio.

### Features

- **Smart Torrent Categorization**: Categorizes downloads into `movies`, `tv-shows`, `music`, `av`, and `default`. Each category can be directed to specific locations. It utilizes the sophisticated regular expressions powered by [regen](https://github.com/libertypi/regen), and millions of real world data.

- **Shallow Copy**: Utilizes copy-on-write (CoW) on file systems like Btrfs to perform lightweight copies. Data blocks are only duplicated when modified. Copies do not take double space and are instant.

- **Automatic Storage Management**: Manages space in the `download-dir` by removing the least active torrents based on quota settings.

### Usage

Queersmission is designed to be run as a `script-torrent-added` to perform storage management, and a `script-torrent-done` to perform post-download copying.

`download-dir` should be set to the dedicated seeding space, both in Transmission's settings.json and the script's config.json.

After stopping the Transmission client, edit its `settings.json`. On a Synology NAS, this file may be located at `/volume1/@appdata/transmission/settings.json`. Default locations on other platforms can be found [here](https://github.com/transmission/transmission/blob/main/docs/Configuration-Files.md). 

**The bellow settings in Transmission `settings.json` must be set correctly:**

```json
"download-dir": "/path_to/download-dir",
"script-torrent-added-enabled": true,
"script-torrent-added-filename": "/path_to/queersmission/torrent-added.py",
"script-torrent-done-enabled": true,
"script-torrent-done-filename": "/path_to/queersmission/torrent-done.py",
```

### Configuration

Upon the first run, a blank configuration file `config.json` will be created in the same directory as this script. Edit the config file to get started.

Template:

```json
{
    "rpc-port": 9091,
    "rpc-url": "/transmission/rpc",
    "rpc-username": "",
    "rpc-password": "",
    "download-dir": "",
    "download-dir-cleanup-enable": false,
    "download-dir-size-limit-gb": 0,
    "download-dir-space-floor-gb": 0,
    "watch-dir": "",
    "only-seed-private": false,
    "log-level": "INFO",
    "destinations": {
        "default": "",
        "movies": "",
        "tv-shows": "",
        "music": "",
        "av": ""
    }
}
```

- **rpc-port**: Number (default = 9091)

- **rpc-url**: String (default = /transmission/rpc)

- **rpc-username**: String.

- **rpc-password**: String. Queersmission will obfuscate and rewrite this field after its first read.

- **download-dir**: String. The default download location, used as the dedicated seeding location. This setting should be identical to Transmission's 'download-dir.' If not set, the script may make an additional API call to read the download-dir setting.

- **download-dir-cleanup-enable**: Boolean (default = false). When enabled, removes all files from the `download-dir` that are not in Transmission's downloads list. **Avoid storing personal or unrelated files in the `download-dir`, as they will be automatically deleted when this option is active!**

- **download-dir-size-limit-gb**: Integer (default = 0). Sets the maximum allowed size (in gigabytes) of the download-dir. If the total size of the files exceeds this limit, the script will remove the least active torrents to free up space. Set to 0 to disable.

- **download-dir-space-floor-gb**: Integer (default = 0). Specifies a minimum free space threshold (in gigabytes) for the download-dir. Set to 0 to disable.

- **watch-dir**: String. Path to the watch-dir. When set, old or empty ".torrent" files will be cleared from this directory.

- **only-seed-private**: Boolean (default = false). Only seed private torrents. Public torrents will be removed from the seeding list immediately after the download and file-moving completes.

- **log-level**: String (default = INFO). Possible values are "DEBUG", "INFO", "WARNING", "ERROR", and "CRITICAL".

- **destinations:** Object. Specifies paths where categorized files should be copied after download completion. Entries include: `default`, `movies`, `tv-shows`, `music`, and `av`. The `default` must be a valid directory, and others can be left empty to use the default value.

### Author

- David Pi
