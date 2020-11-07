#!/usr/bin/env python3

import pickle
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin
import subprocess

import requests
from lxml import html
from torrentool.api import Torrent
from torrentool.exceptions import TorrentoolException

domain = "https://pt.m-team.cc/"
page = "https://pt.m-team.cc/adult.php"
id_finder = re.compile(r"\bid=(?P<id>[0-9]+)").search
transmission_re = re.compile(r"\s+(?P<file>.+?) \([^)]+\)").fullmatch

torrent_dir = Path("/mnt/d/Downloads/jav/torrent")


def fetch_page(lo: int, hi: int):

    with ThreadPoolExecutor(max_workers=None) as ex:
        for future in as_completed(ex.submit(_get_link, i) for i in range(lo, hi + 1)):
            for link in future.result():
                yield link


def _get_link(n: int):

    print("Fetching page:", n)

    for _ in range(3):
        try:
            r = session.get(f"{page}?page={n}")
            r.raise_for_status()
            break
        except requests.RequestException:
            pass
    else:
        print(f"Downloading page {n} failed.")
        return ()

    return html.fromstring(r.content).xpath(
        '//*[@id="form_torrent"]/table[@class="torrents"]/'
        'tr/td[@class="torrenttr"]/table[@class="torrentname"]'
        '//a[contains(@href, "download.php")]/@href'
    )


def analyze_torrent(link: str, av_regex: re.Pattern.search):

    print("Analyzing torrent:", link)

    file = torrent_dir.joinpath(id_finder(link)["id"] + ".txt")

    try:
        with open(file, "r", encoding="utf-8") as f:
            if not any(map(av_regex, f)):
                f.seek(0)
                return tuple(filter(is_video, f))

    except FileNotFoundError:

        for _ in range(3):
            try:
                content = session.get(urljoin(domain, link)).content
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

                filelist = subprocess.check_output(("transmission-show", torrent_file), encoding="utf-8").splitlines()
                filelist = "\n".join(m["file"] for m in map(transmission_re, filelist[filelist.index("FILES") :]) if m)

                if not filelist:
                    raise ValueError

                with open(file, "w", encoding="utf-8") as f:
                    f.write(filelist.lower())
                    f.write("\n")

            except (subprocess.CalledProcessError, ValueError, OSError):
                print(f'Parsing torrent error: "{link}"')
                return

            finally:
                torrent_file.unlink(missing_ok=True)

        return analyze_torrent(link, av_regex)


def is_video(string: str):
    return string.rstrip().endswith((".mp4", ".wmv", ".avi", ".iso", ".m2ts"))


def main():

    try:
        if not all(s.isdigit() for s in sys.argv[1:]):
            raise ValueError
        if len(sys.argv) == 2:
            lo = 1
            hi = int(sys.argv[1])
        else:
            lo, hi = (int(i) for i in sys.argv[1:])
    except (IndexError, ValueError):
        print("Argument must be one or two integers.")
        sys.exit()

    try:
        if not torrent_dir.exists():
            torrent_dir.mkdir()
    except OSError as e:
        print(f'Creating "{torrent_dir}" failed: {e}')
        sys.exit()

    global session
    with open(torrent_dir.with_name("data"), "rb") as f:
        session = pickle.load(f)[4]

    with open("av_regex.txt", "r") as f:
        av_regex = re.compile(f.read().strip()).search

    sep = "-" * 80 + "\n"
    total = unmatched = 0
    unmatched_file = torrent_dir.with_name("unmatched.txt")
    freq_file = torrent_dir.with_name("freq.txt")

    id_searcher = re.compile(r"\b[0-9]*(?P<id>[a-z]{2,8})[ _-]?[0-9]{2,6}\b").search
    word_finder = re.compile(r"\w{3,}").findall
    id_count = defaultdict(set)
    word_count = Counter()

    with ProcessPoolExecutor(max_workers=None) as ex, open(unmatched_file, "w", encoding="utf-8") as f:

        for future in as_completed(ex.submit(analyze_torrent, i, av_regex) for i in fetch_page(lo, hi)):

            total += 1
            result = future.result()

            if result:
                unmatched += 1

                f.write(sep)
                f.writelines(result)
                f.write("\n")

                for m in filter(None, map(id_searcher, result)):
                    id_count[m["id"]].add(m.group())

                for r in map(word_finder, result):
                    word_count.update(r)

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


if __name__ == "__main__":
    main()
