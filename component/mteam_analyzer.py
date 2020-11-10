#!/usr/bin/env python3

import argparse
import pickle
import re
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import chain
from pathlib import Path
from urllib.parse import urljoin

import requests
from lxml import etree, html
from torrentool.api import Torrent
from torrentool.exceptions import TorrentoolException

BASE_DIR = Path("/mnt/d/Downloads/jav")


class MteamScraper:

    DOMAIN = "https://pt.m-team.cc/"

    def __init__(self, dir: Path = BASE_DIR) -> None:

        self.base_dir = dir if isinstance(dir, Path) else Path(dir)
        self.id_searcher = re.compile(r"\bid=(?P<id>[0-9]+)").search
        self.transmission_split = re.compile(r"^\s+(.+?) \([^)]+\)$", flags=re.MULTILINE).findall
        self.link_finder = etree.XPath(
            '//*[@id="form_torrent"]/table[@class="torrents"]'
            '//*[@class="torrenttr"]/table[@class="torrentname"]'
            '//a[contains(@href, "download.php")]/@href'
        )

        with open(self.base_dir.joinpath("data"), "rb") as f:
            self.session: requests.Session = pickle.load(f)[4]

    def fetch(self, page: str, subdir: str, lo: int, hi: int):

        page = self.DOMAIN + page
        subdir = self.base_dir.joinpath(subdir)

        with ThreadPoolExecutor(max_workers=None) as ex:

            links = as_completed(ex.submit(self._get_link, page, i) for i in range(lo, hi + 1))
            paths = as_completed(ex.submit(self._fetch_torrent, link, subdir) for f in links for link in f.result())

            for future in paths:
                try:
                    with future.result().open("r", encoding="utf-8") as f:
                        yield f
                except AttributeError:
                    pass

    def _get_link(self, page: str, n: int):

        print("Fetching page:", n)
        for _ in range(3):
            try:
                r = self.session.get(page, timeout=7, params={"page": n})
                r.raise_for_status()
            except requests.RequestException:
                pass
            else:
                break
        else:
            print(f"Downloading page {n} failed.")
            return ()

        return self.link_finder(html.fromstring(r.content))

    def _fetch_torrent(self, link: str, subdir: Path):

        file = subdir.joinpath(self.id_searcher(link)["id"] + ".txt")

        if not file.exists():
            print("Fetching torrent:", link)

            for _ in range(3):
                try:
                    content = self.session.get(urljoin(self.DOMAIN, link), timeout=7).content
                except (requests.RequestException, AttributeError):
                    pass
                else:
                    break
            else:
                print(f"Downloading torrent failed: {link}")
                return

            try:
                filelist = Torrent.from_string(content).files
                with open(file, "w", encoding="utf-8") as f:
                    f.writelines(i[0].lower() + "\n" for i in filelist)

            except (TorrentoolException, OSError, TypeError):

                torrent_file = file.with_suffix(".torrent")

                try:
                    with open(torrent_file, "wb") as f:
                        f.write(content)

                    filelist = subprocess.check_output(("transmission-show", torrent_file), encoding="utf-8")
                    filelist = self.transmission_split(filelist, filelist.index("\n\nFILES\n\n"))

                    if not filelist:
                        raise ValueError

                    with open(file, "w", encoding="utf-8") as f:
                        f.writelines(s.lower() + "\n" for s in filelist)

                except (subprocess.CalledProcessError, ValueError, OSError):
                    print(f'Parsing torrent error: "{link}"')
                    return

                finally:
                    torrent_file.unlink(missing_ok=True)

        return file


def analyze_av(lo: int, hi: int):

    page = "adult.php"
    unmatched_file = BASE_DIR / "unmatched.txt"
    freq_file = BASE_DIR / "freq.txt"
    total = unmatched = 0
    sep = "-" * 80 + "\n"

    prefix_searcher = re.compile(r"\b[0-9]*(?P<id>[a-z]{2,8})[ _-]?[0-9]{2,6}(hhb[0-9]?)?\b").search
    word_finder = re.compile(r"\w{3,}").findall
    id_count = defaultdict(set)
    word_count = Counter()

    with unmatched_file.open("w", encoding="utf-8") as f:

        for t in MteamScraper().fetch(page, "av", lo, hi):
            total += 1
            if any(map(av_regex, t)):
                continue

            t.seek(0)
            result = tuple(filter(is_video, t))
            if result:
                unmatched += 1
                f.write(sep)
                f.writelines(result)
                f.write("\n")

                for m in filter(None, map(prefix_searcher, result)):
                    id_count[m["id"]].add(m.group())

                word_count.update(chain.from_iterable(map(word_finder, result)))

        f.write(f"Total: {total}. Unmatched: {unmatched}.\n")

    print("Calculating frequencies...")

    id_count = [(i, k, v) for k, v in id_count.items() if (i := len(v)) > 1]
    id_count.sort(reverse=True)

    word_count = [(v, k) for k, v in word_count.items() if v > 2]
    word_count.sort(reverse=True)

    with open(freq_file, "w", encoding="utf-8") as f:
        f.writelines(f"{l:6d}: {k:20}  {v}\n" for l, k, v in id_count)
        f.write("\n" + sep)
        f.writelines(f"{v:6d}: {k}\n" for v, k in word_count)

    print("Done.")


def analyze_non_av(lo: int, hi: int):

    page = "torrents.php"
    mismatched_file = BASE_DIR / "mismatched.txt"
    count = defaultdict(list)
    word_searcher = re.compile(r"[a-z]+").search

    files = MteamScraper().fetch(page, "non_av", lo, hi)
    for m in filter(None, map(av_regex, chain.from_iterable(files))):
        m = m.group()
        try:
            count[word_searcher(m).group()].append(m)
        except AttributeError:
            pass

    count = [(i, k, set(v)) for k, v in count.items() if (i := len(v)) > 1]
    count.sort(reverse=True)

    with mismatched_file.open("w", encoding="utf-8") as f:
        f.writelines(f"{l:6d}: {k:20}  {v}\n" for l, k, v in count)


def is_video(string: str):
    return string.rstrip().endswith((".mp4", ".wmv", ".avi", ".iso", ".m2ts"))


def parse_arguments():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-m",
        "--mismatch",
        dest="mismatch",
        action="store_true",
        help="test mismatch via regular torrents",
    )
    parser.add_argument(
        "range",
        nargs="+",
        action="store",
        type=int,
        help="range of pages to be scaned, should be 1 or 2 integers",
    )

    args = parser.parse_args()
    if len(args.range) == 1:
        args.range.insert(0, 0)
    elif len(args.range) != 2 or args.range[0] >= args.range[1]:
        parser.error("Ranges should be 1 or 2 integers (low to high)")
    return args


def main():

    args = parse_arguments()

    for dir in "av", "non_av":
        dir = BASE_DIR.joinpath(dir)
        if not dir.exists():
            try:
                dir.mkdir(parents=True)
            except OSError as e:
                print(f'Creating "{dir}" failed: {e}')
                sys.exit()

    global av_regex
    with open("regex.txt", "r", encoding="utf-8") as f:
        av_regex = re.compile(f.read().strip()).search

    if args.mismatch:
        analyze_non_av(*args.range)
    else:
        analyze_av(*args.range)


if __name__ == "__main__":
    main()
