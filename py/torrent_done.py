#!/usr/bin/env python3

import os
import shutil
from collections import defaultdict
import re
import os.path as op

# Configurations
SEED_DIR = '/volume2/@transmission'
WATCH_DIR = '/volume1/video/Torrents'
LOG_FILE = 'transmission.log'
REGEX_FILE = 'regex.txt'
API_BASE = 'http://localhost:9091/transmission/rpc'


class Torrent_Handler:

    SIZE_THRESH = 80 * 1024**2
    OUTPUT = {
        "av": "/volume1/driver/Temp",
        "film": "/volume1/video/Films",
        "tv": "/volume1/video/TV Series",
        "music": "/volume1/music/Download",
        "adobe": "/volume1/homes/admin/Download/Adobe",
        "default": "/volume1/homes/admin/Download"
    }

    def __init__(self, torrent_dir: str, torrent_name: str) -> None:
        self.torrent_name = torrent_name
        self.torrent_path = f = op.join(torrent_dir, torrent_name)
        self.is_dir = op.isdir(f)

        try:
            with open(REGEX_FILE, "r", encoding="utf-8") as f:
                f = next(f).strip()
            if not f:
                raise ValueError("regex file empty")
            self.av_matcher = re.compile(f).search
        except Exception as e:
            import warnings
            warnings.warn(f"Reading regex error: {e}")
            self.av_matcher = lambda _: None

        if self.is_dir:
            self.files = self._walk_dir()
        else:
            self.files = (torrent_name.lower())

    def classify(self):
        matcher = re.compile(
            r"\.(3gp|asf|avi|bdmv|flv|iso|m(2?ts|4p|[24kop]v|p2|p4|pe?g|xf)|rm|rmvb|ts|vob|webm|wmv)$"
        )
        av_matcher = self.av_matcher
        videos = []
        for file in self.files:
            if matcher(file):
                if av_matcher(file):
                    return self._output("av")
                elif re.search(
                        r"\b([es]|ep[ _-]?|s([1-9][0-9]|0?[1-9])e)([1-9][0-9]|0?[1-9])\b",
                        file):
                    return self._output('tv')

    def _walk_dir(self) -> list:
        stack = [self.torrent_path]
        files = defaultdict(int)
        size_reached = False
        offset = len(self.torrent_path) + 1
        while stack:
            root = stack.pop()
            with os.scandir(root) as it:
                for entry in it:
                    if entry.name[0] in ".#@":
                        continue
                    if entry.is_dir():
                        stack.append(entry.path)
                        continue
                    size = entry.stat().st_size
                    if size >= self.SIZE_THRESH:
                        if not size_reached:
                            files.clear()
                            size_reached = True
                    elif size_reached:
                        continue
                    path = entry.path[offset:].lower()
                    if "/bdmv/stream/" in path:
                        path = re.sub(r'/bdmv/stream/[^/]+\.m2ts$',
                                      r"/bdmv/index.bdmv", path)
                    elif "/video_ts/" in path:
                        path = re.sub(r'/video_ts/[^/]+\.vob$',
                                      r"/video_ts/video_ts.vob", path)
                    files[path] += size
        return sorted(files, key=files.get, reverse=True)

    def _output(self, _type):
        root = self.OUTPUT[_type]
        if self.is_dir:
            dest = root
        else:
            dest = op.join(root, op.splitext(self.torrent_name))
        return root, dest