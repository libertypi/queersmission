#!/usr/bin/env python3

import argparse
import pickle
import re
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests
from lxml import html
from torrentool.api import Torrent
from torrentool.exceptions import TorrentoolException

BASE_DIR = Path("/mnt/d/Downloads/jav")
DOMAIN = "https://pt.m-team.cc/"
link_id_finder = re.compile(r"\bid=(?P<id>[0-9]+)").search
transmission_split = re.compile(r"^\s+(.+?) \([^)]+\)$", flags=re.MULTILINE).findall


def fetch(page: str, dir: Path, lo: int, hi: int):
    with ThreadPoolExecutor(max_workers=None) as tex, ProcessPoolExecutor(max_workers=None) as pex:
        links = as_completed(tex.submit(_get_link, page, i) for i in range(lo, hi + 1))
        for future in as_completed(pex.submit(_fetch_torrent, link, dir) for f in links for link in f.result()):
            yield future.result()


def _get_link(page: str, n: int):

    print("Fetching page:", n)

    for _ in range(3):
        try:
            r = session.get(f"{page}?page={n}", timeout=7)
            r.raise_for_status()
        except requests.RequestException:
            pass
        else:
            break
    else:
        print(f"Downloading page {n} failed.")
        return ()

    return html.fromstring(r.content).xpath(
        '//*[@id="form_torrent"]/table[@class="torrents"]/'
        'tr/td[@class="torrenttr"]/table[@class="torrentname"]'
        '//a[contains(@href, "download.php")]/@href'
    )


def _fetch_torrent(link: str, dir: Path):

    file = dir.joinpath(link_id_finder(link)["id"] + ".txt")

    if not file.exists():
        print("Fetching torrent:", link)

        for _ in range(3):
            try:
                content = session.get(urljoin(DOMAIN, link), timeout=7).content
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
                filelist = transmission_split(filelist, filelist.index("\n\nFILES\n\n"))

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


def analyze_av(dir: Path, lo: int, hi: int):

    page = DOMAIN + "adult.php"
    unmatched_file = BASE_DIR / "unmatched.txt"
    freq_file = BASE_DIR / "freq.txt"
    total = unmatched = 0
    sep = "-" * 80 + "\n"

    prefix_searcher = re.compile(r"\b[0-9]*(?P<id>[a-z]{2,8})[ _-]?[0-9]{2,6}(hhb[0-9]?)?\b").search
    word_finder = re.compile(r"\w{3,}").findall
    id_count = defaultdict(set)
    word_count = Counter()

    with unmatched_file.open("w", encoding="utf-8") as f:

        for file in fetch(page, dir, lo, hi):

            try:
                with file.open("r", encoding="utf-8") as t:
                    total += 1
                    if any(map(av_regex, t)):
                        continue
                    t.seek(0)
                    result = tuple(filter(is_video, t))

            except AttributeError:
                continue

            if result:
                unmatched += 1
                f.write(sep)
                f.writelines(result)
                f.write("\n")

                for m in filter(None, map(prefix_searcher, result)):
                    id_count[m["id"]].add(m.group())

                for m in map(word_finder, result):
                    word_count.update(m)

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


def analyze_non_av(dir: Path, lo: int, hi: int):

    page = DOMAIN + "torrents.php"
    mismatched_file = BASE_DIR / "mismatched.txt"
    count = defaultdict(list)
    word_searcher = re.compile(r"[a-z]+").search

    for file in fetch(page, dir, lo, hi):
        try:
            with file.open("r", encoding="utf-8") as f:
                for m in filter(None, map(av_regex, f)):
                    m = m.group()
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
        "-m", "--mismatch", dest="mismatch", action="store_true", help="test mismatch via regular torrents"
    )
    parser.add_argument(
        "range", nargs=2, action="store", type=int, help="range of pages to be scaned, should be 2 integers"
    )
    return parser.parse_args()


def main():

    args = parse_arguments()

    av_dir = BASE_DIR / "av"
    non_av_dir = BASE_DIR / "non_av"
    for dir in (av_dir, non_av_dir):
        if not dir.exists():
            try:
                dir.mkdir(parents=True)
            except OSError as e:
                print(f'Creating "{dir}" failed: {e}')
                sys.exit()

    global session
    global av_regex
    with open(BASE_DIR / "data", "rb") as f:
        session = pickle.load(f)[4]
    with open("av_regex.txt", "r", encoding="utf-8") as f:
        av_regex = re.compile(f.read().strip()).search

    if args.mismatch:
        analyze_non_av(non_av_dir, *args.range)
    else:
        analyze_av(av_dir, *args.range)


if __name__ == "__main__":
    main()
