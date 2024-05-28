# Queersmission

*Queer's mission... is to help Transmission.*

**Queersmission** is a [post-download script](https://github.com/transmission/transmission/blob/main/docs/Scripts.md) for the [Transmission](https://transmissionbt.com/) client. It allows users to dedicate storage for torrent uploading and to copy the finished downloads to user destinations. This ensures that file sharing continues, even if the user deletes the content, which is useful for Private Torrent (PT) users who need to maintain a sharing ratio.

### Features

- **Smart Torrent Categorization**: Categorizes downloads into `movies`, `tv-shows`, `music`, `av`, and `default`. Each category can be directed to specific locations. It utilizes the sophisticated regular expressions powered by [regen](https://github.com/libertypi/regen), and other algorithms.

- **Shallow Copy**: Utilizes copy-on-write (CoW) on file systems like Btrfs to perform lightweight copies. Data blocks are only duplicated when modified. Copies do not take double space and are instant.

- **Automatic Storage Management**: Manages space in the `download-dir` by removing the least active torrents based on quota settings.

### Configuration

Upon the first run, a blank configuration file `config.json` will be created in the same directory as this script. Edit the config file to get started.

Example:

```json
{
    "rpc-port": 9091,
    "rpc-username": "",
    "rpc-password": "",
    "watch-dir": "/path/to/watch_dir",
    "download-dir": "/path/to/download-dir",
    "download-dir-size-limit-gb": 2000,
    "download-dir-space-floor-gb": null,
    "only-seed-private": true,
    "log-level": "INFO",
    "destinations": {
        "default": "/volume1/Downloads",
        "movie": "/volume1/Videos/Movies",
        "tv": "/volume1/Videos/TV Shows",
        "music": "/volume1/Music",
        "av": "/volume1/Age Restricted Materials"
    }
}
```

- **rpc-port**: Number (default = 9091)

- **rpc-username**: String.

- **rpc-password**: String. Queersmission will obfuscate and rewrite this field after its first read.

- **watch-dir**: String. Old or zero-length ".torrent" files will be cleared from this directory.

- **download-dir**: String. The default download location, used as the dedicated seeding location. **IMPORTANT: Do NOT place any personal files in the download-dir as they will be deleted!**

- **download-dir-size-limit-gb**: Integer. Sets the maximum allowed size (in gigabytes) of the download-dir. If the total size of the files exceeds this limit, the script will remove the least active torrents to free up space. Set to null to disable.

- **download-dir-space-floor-gb**: Integer. Specifies a minimum free space threshold (in gigabytes) for the download-dir. Set to null to disable.

- **only-seed-private**: Boolean (default = true). Only seed private torrents. Public torrents will be removed from the seeding list immediately after the download completes and the files are moved to designated locations.

- **log-level**: String (default = "INFO"). Possible values are "DEBUG", "INFO", "WARNING", "ERROR", and "CRITICAL".

- **destinations:** Object. Specifies paths where categorized files should be copied after download completion. Entries include: `default`, `movies`, `tv-shows`, `music`, and `av`. The `default` must be a valid directory, and others can be left empty to use the default value.

### Usage

This script is designed to be run as a [script-torrent-done](https://github.com/transmission/transmission/blob/main/docs/Editing-Configuration-Files.md#:~:text=script%2Dtorrent%2Ddone%2Dfilename) to perform post-download copying and maintenance.

After stopping the Transmission client, edit its `settings.json`. On a Synology NAS, this file may be located at `/volume1/@appdata/transmission/settings.json`. Default locations on other platforms can be found [here](https://github.com/transmission/transmission/blob/main/docs/Configuration-Files.md). Set `script-torrent-done-enabled` to `true` and `script-torrent-done-filename` to the path of this script.

Example Transmission `settings.json`:

```json
"script-torrent-done-enabled": true,
"script-torrent-done-filename": "/volume1/path/to/queersmission/queersmission.py"
```

### Author

- David Pi
