#!/usr/bin/env python3

import argparse
import pickle
import re
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import chain, filterfalse
from operator import itemgetter
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Set, TextIO, Tuple
from urllib.parse import urljoin

import requests
from lxml import etree, html
from torrentool.api import Torrent
from torrentool.exceptions import TorrentoolException

SCRIPT_DIR = Path(__file__).parent
REPORT_DIR = Path("/mnt/d/Downloads/jav")

sys.path.insert(0, str(SCRIPT_DIR.joinpath("../../regenerator").resolve()))
from regenerator import Regen


class LastPageReached(Exception):
    pass


class MteamScraper:

    DOMAIN = "https://pt.m-team.cc/"

    def __init__(self, dir: Path = REPORT_DIR) -> None:

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

    def fetch(self, page: str, subdir: str, lo: int, hi: int) -> Iterator[TextIO]:

        page = self.DOMAIN + page
        subdir = self.base_dir.joinpath(subdir)

        with ThreadPoolExecutor(max_workers=None) as l_ex, ThreadPoolExecutor(max_workers=None) as t_ex:

            for l_ft in as_completed(l_ex.submit(self._get_link, page, i) for i in range(lo, hi + 1)):
                for t_ft in as_completed(t_ex.submit(self._fetch_torrent, i, subdir) for i in l_ft.result()):
                    try:
                        with t_ft.result().open("r", encoding="utf-8") as f:
                            yield f
                    except AttributeError:
                        pass

    def _get_link(self, page: str, n: int) -> List[str]:

        print("Fetching page:", n)
        for retry in range(3):
            try:
                r = self.session.get(page, timeout=7, params={"page": n})
                r.raise_for_status()
            except requests.RequestException:
                if retry == 2:
                    raise
            else:
                return self.link_finder(html.fromstring(r.content))

    def _fetch_torrent(self, link: str, subdir: Path) -> Path:

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


class CJKMteamScraper(MteamScraper):
    def __init__(self, *args, **kwargs) -> None:

        super().__init__(*args, **kwargs)

        self.table_finder = etree.XPath(
            '//*[@id="form_torrent"]/table[@class="torrents"]//*[@class="torrenttr"]/table[@class="torrentname"]'
        )
        self.title_finder = etree.XPath('(.//a[contains(@href, "details.php")]/@title)[1]')
        self.link_finder = etree.XPath('(.//a[contains(@href, "download.php")]/@href)[1]')

    def _get_link(self, page: str, n: int) -> List[str]:

        for retry in range(3):
            try:
                r = self.session.get(page, timeout=7, params={"page": n})
                r.raise_for_status()
            except requests.RequestException:
                if retry == 2:
                    raise
            else:
                result = []
                title_finder = self.title_finder
                link_finder = self.link_finder
                for table in self.table_finder(html.fromstring(r.content)):
                    try:
                        if contains_cjk(title_finder(table)[0]):
                            result.append(link_finder(table)[0])
                    except IndexError:
                        pass
                return result


class JavREBuilder:
    def __init__(self, report_dir: Path, fetch: bool = False):

        self.kw_file = report_dir.joinpath("keyword.txt")
        self.prefix_file = report_dir.joinpath("id_prefix.txt")
        self.whitelist_file = report_dir.joinpath("id_whitelist.txt")
        self.blacklist_file = report_dir.joinpath("id_blacklist.txt")
        self.output_file = report_dir.joinpath("regex.txt")

        self.fetch = fetch

    def run(self):

        kw_regex = self._get_regex(
            wordlist=self._update_file(self.kw_file, self._filter_strategy),
            name="Keywords",
            omitOuterParen=True,
        )
        self._kw_filter = re.compile(kw_regex).fullmatch

        prefix_regex = self._get_regex(
            wordlist=self._update_file(self.prefix_file, self._prefix_strategy),
            name="ID Prefix",
            omitOuterParen=False,
        )

        if not (kw_regex and prefix_regex):
            print("Generating regex failed.")
            return

        self.regex = f"(^|[^a-z0-9])({kw_regex}|[0-9]{{,3}}{prefix_regex}[ _-]?[0-9]{{2,6}})([^a-z0-9]|$)"
        return self._update_file(self.output_file, lambda _: (self.regex,))[0]

    @staticmethod
    def _update_file(file: Path, stragety: Callable[[Iterable[str]], Iterable[str]]) -> List[str]:

        try:
            f = file.open(mode="r+", encoding="utf-8")
            old_list = f.read().splitlines()
        except FileNotFoundError:
            f = file.open(mode="w", encoding="utf-8")
            old_list = []
        finally:
            result = sorted(stragety(old_list))
            if old_list != result:
                f.seek(0)
                f.writelines(i + "\n" for i in result)
                f.truncate()
                print(f"{file.name} updated.")
            f.close()
        return result

    def _prefix_strategy(self, old_list: Iterable[str]) -> Iterator[str]:

        if self.fetch:
            result = self._web_scrape()
        else:
            result = self._filter_strategy(old_list)

        result.update(self._update_file(self.whitelist_file, self._extract_strategy))
        result.difference_update(self._update_file(self.blacklist_file, self._extract_strategy))

        return filterfalse(self._kw_filter, result)

    def _extract_strategy(self, old_list: Iterable[str]) -> Iterator[str]:
        return Regen(self._filter_strategy(old_list)).to_text()

    @staticmethod
    def _filter_strategy(wordlist: Iterable[str]) -> Set[str]:
        return set(map(str.lower, filter(None, map(str.strip, wordlist))))

    def _web_scrape(self) -> Set[str]:

        mtscraper = CJKMteamScraper()
        self.session = mtscraper.session
        self.session.cookies.set_cookie(
            requests.cookies.create_cookie(domain="www.javbus.com", name="existmag", value="all")
        )

        uniq_id = set(self._scrape_mteam(mtscraper))
        uniq_id.update(self._normalize_id(chain(self._scrape_javbus(), self._scrape_javdb(), self._scrape_github())))

        prefix_counter = Counter(map(itemgetter(0), uniq_id))
        final = {k for k, v in prefix_counter.items() if v >= 5}

        print(f"Uniq ID: {len(uniq_id)}. Uniq prefix: {len(prefix_counter)}. Final: {len(final)}.")
        return final

    @staticmethod
    def _normalize_id(wordlist: Iterable[str]) -> Iterator[Tuple[str, str]]:

        matcher = re.compile(r"\s*([a-z]{3,7})[ _-]?0*([0-9]{2,6})\s*").fullmatch
        for m in filter(None, map(matcher, map(str.lower, wordlist))):
            yield m.group(1, 2)

    @staticmethod
    def _scrape_mteam(mtscraper: CJKMteamScraper) -> Iterator[Tuple[str, str]]:

        page = "adult.php?cat410=1&cat429=1&cat426=1&cat437=1&cat431=1&cat432=1"
        limit = 500

        print(f"Scanning MTeam... limit: {limit} pages")

        matcher = re.compile(
            r"(?:^|/)(?:[0-9]{3})?([a-z]{3,6})-0*([0-9]{2,4})(?:hhb[0-9]?)?\b.*\.(?:mp4|wmv|avi|iso)$",
            flags=re.MULTILINE,
        ).search

        for m in filter(None, map(matcher, chain.from_iterable(mtscraper.fetch(page, "av", 1, limit)))):
            yield m.group(1, 2)

    def _scrape_javbus(self) -> Iterator[str]:

        print("Scanning javbus...")
        xpath = etree.XPath('//div[@id="waterfall"]//a[@class="movie-box"]//span/date[1]/text()')
        step = 500

        for base in ("page", "uncensored/page", "genre/hd", "uncensored/genre/hd"):
            idx = 1
            print(f"  /{base}: ", end="", flush=True)
            with ThreadPoolExecutor(max_workers=None) as ex:
                while True:
                    print(f"{idx}:{idx+step}...", end="", flush=True)
                    args = ((f"https://www.javbus.com/{base}/{i}", xpath) for i in range(idx, idx + step))
                    try:
                        yield from chain.from_iterable(ex.map(self._scrap_jav, args))
                    except LastPageReached:
                        break
                    idx += step
            print()

    def _scrape_javdb(self) -> Iterator[str]:

        limit = 80
        print(f"Scanning javdb...")
        xpath = etree.XPath('//*[@id="videos"]//a/div[@class="uid"]/text()')

        for base in ("https://javdb.com/uncensored", "https://javdb.com/"):
            with ThreadPoolExecutor(max_workers=3) as ex:
                args = ((f"{base}?page={i}", xpath) for i in range(1, limit + 1))
                try:
                    yield from chain.from_iterable(ex.map(self._scrap_jav, args))
                except LastPageReached:
                    pass

    def _scrap_jav(self, args: Tuple) -> List[str]:

        url, xpath = args

        for _ in range(3):
            try:
                res = self.session.get(url, timeout=7)
                res.raise_for_status()
            except requests.HTTPError as e:
                if e.response.status_code == 404:
                    raise LastPageReached
            except requests.RequestException:
                pass
            else:
                return xpath(html.fromstring(res.content))

        raise requests.RequestException(f"Connection error: {url}")

    def _scrape_github(self) -> List[str]:

        url = "https://raw.githubusercontent.com/imfht/fanhaodaquan/master/data/codes.json"
        print("Downloading github database...")

        for retry in range(3):
            try:
                return self.session.get(url).json()
            except requests.RequestException:
                if retry == 2:
                    raise

    @staticmethod
    def _get_regex(wordlist: List[str], name: str, omitOuterParen: bool) -> str:

        regen = Regen(wordlist)
        computed = regen.to_regex(omitOuterParen=omitOuterParen)

        concat = "|".join(wordlist)
        if not omitOuterParen and len(wordlist) > 1:
            concat = f"({concat})"

        diff = len(computed) - len(concat)
        if diff > 0:
            print(f"{name}: Computed regex is {diff} characters longer than concatenation, use the latter.")
            return concat

        regen.verify_result()
        print(f"{name}: Regex test passed. Characters saved: {-diff}.")
        return computed


def analyze_av(lo: int, hi: int, av_matcher: Callable):

    page = "adult.php"
    unmatched_file = REPORT_DIR / "unmatched.txt"
    freq_file = REPORT_DIR / "freq.txt"
    total = unmatched = 0
    sep = "-" * 80 + "\n"

    prefix_searcher = re.compile(r"\b[0-9]*([a-z]{2,8})[ _-]?[0-9]{2,6}(?:hhb[0-9]?)?\b").search
    word_finder = re.compile(r"\w{3,}").findall

    flat_counter = defaultdict(set)
    prefix_counter = Counter()
    word_counter = Counter()
    videos = []
    prefix_tmp = set()
    word_tmp = set()

    with unmatched_file.open("w", encoding="utf-8") as f:

        for t in MteamScraper().fetch(page, "av", lo, hi):
            total += 1
            if any(map(av_matcher, t)):
                continue

            t.seek(0)
            videos.extend(filter(is_video, t))
            if not videos:
                continue

            unmatched += 1
            f.write(sep)
            f.writelines(videos)
            f.write("\n")

            for m in filter(None, map(prefix_searcher, videos)):
                prefix = m.group(1)
                flat_counter[prefix].add(m.group())
                prefix_tmp.add(prefix)
            prefix_counter.update(prefix_tmp)

            word_tmp.update(chain.from_iterable(map(word_finder, videos)))
            word_counter.update(word_tmp)

            videos.clear()
            prefix_tmp.clear()
            word_tmp.clear()

        f.write(f"{sep}Total: {total}. Unmatched: {unmatched}.\n")

    prefixes = [(i, len(v), k, v) for k, v in flat_counter.items() if (i := prefix_counter[k]) >= 3]
    words = [(v, k) for k, v in word_counter.items() if v >= 3]
    prefixes.sort(reverse=True)
    words.sort(reverse=True)

    with open(freq_file, "w", encoding="utf-8") as f:
        f.write("Potential ID Prefixes:\n\n")
        f.write("{:>6}  {:>6}  {:15}  {}\n{:->80}\n".format("uniq", "occur", "word", "strings", ""))
        f.writelines(f"{i:6d}  {j:6d}  {k:15}  {s}\n" for i, j, k, s in prefixes)

        f.write("\n\nPotential Keywords:\n\n")
        f.write("{:>6}  {}\n{:->80}\n".format("uniq", "word", ""))
        f.writelines(f"{i:6d}  {j}\n" for i, j in words)

    print(f"Done. Results saved to: \n{unmatched_file}\n{freq_file}")


def analyze_non_av(lo: int, hi: int, av_matcher: Callable):

    page = "torrents.php"
    mismatched_file = REPORT_DIR / "mismatched.txt"
    word_searcher = re.compile(r"[a-z]+").search

    flat_counter = defaultdict(list)
    torrent_counter = Counter()
    tmp = set()

    for f in MteamScraper().fetch(page, "non_av", lo, hi):

        for m in filter(None, map(av_matcher, f)):
            m = m.group()
            try:
                word = word_searcher(m).group()
            except AttributeError:
                pass
            else:
                flat_counter[word].append(m)
                tmp.add(word)

        torrent_counter.update(tmp)
        tmp.clear()

    result = [(torrent_counter[k], len(v), k, set(v)) for k, v in flat_counter.items()]
    result.sort(reverse=True)

    with mismatched_file.open("w", encoding="utf-8") as f:
        f.write("{:>6}  {:>6}  {:15}  {}\n{:->80}\n".format("uniq", "occur", "word", "strings", ""))
        f.writelines(f"{i:6d}  {j:6d}  {k:15}  {s}\n" for i, j, k, s in result)

    print(f"Done. Result saved to: {mismatched_file}")


def is_video(string: str):
    return string.rstrip().endswith((".mp4", ".wmv", ".avi", ".iso", ".m2ts"))


def contains_cjk(string: str):
    return any(
        i <= c <= j
        for c in map(ord, string)
        for i, j in (
            (4352, 4607),
            (11904, 42191),
            (43072, 43135),
            (44032, 55215),
            (63744, 64255),
            (65072, 65103),
            (65381, 65500),
            (131072, 196607),
        )
    )


def parse_arguments():
    parser = argparse.ArgumentParser(description="build and test regex.")

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-b",
        "--build",
        dest="mode",
        action="store_const",
        const="build",
        help="build and save regex to file (default)",
    )
    group.add_argument(
        "-t",
        "--test-match",
        dest="mode",
        action="store_const",
        const="test_match",
        help="test regex with av torrents",
    )
    group.add_argument(
        "-m",
        "--test-miss",
        dest="mode",
        action="store_const",
        const="test_miss",
        help="test regex with non-av torrents",
    )
    group.set_defaults(mode="build")

    parser.add_argument(
        "-f",
        "--fetch",
        dest="fetch",
        action="store_true",
        help="fetch id prefixes from web",
    )
    parser.add_argument(
        "range",
        nargs="*",
        action="store",
        type=int,
        help="range of mteam pages for testing, 1 or 2 integers",
        default=(0, 20),
    )

    args = parser.parse_args()

    if args.mode != "build":
        if len(args.range) == 1 and args.range[0] > 0:
            args.range.insert(0, 0)
        elif len(args.range) != 2 or args.range[0] >= args.range[1]:
            parser.error("Ranges should be 1 or 2 integers (low to high)")

    return args


def main():

    args = parse_arguments()

    if args.mode == "build":

        regex = JavREBuilder(SCRIPT_DIR, args.fetch).run()
        if regex is not None:
            print(f"\nResult ({len(regex)} chars):")
            print(regex)

    else:

        for dir in "av", "non_av":
            dir = REPORT_DIR.joinpath(dir)
            try:
                if not dir.exists():
                    dir.mkdir(parents=True)
            except OSError as e:
                print(f'Creating "{dir}" failed: {e}')
                return

        with open(SCRIPT_DIR.joinpath("regex.txt"), "r", encoding="utf-8") as f:
            av_matcher = re.compile(f.read().strip(), flags=re.MULTILINE).search

        if args.mode == "test_match":
            analyze_av(*args.range, av_matcher)
        else:
            analyze_non_av(*args.range, av_matcher)


if __name__ == "__main__":
    main()
