#!/usr/bin/env python3

import argparse
import pickle
import re
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import chain
from operator import itemgetter
from pathlib import Path
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

    def fetch(self, page: str, subdir: str, lo: int, hi: int):

        page = self.DOMAIN + page
        subdir = self.base_dir.joinpath(subdir)

        with ThreadPoolExecutor(max_workers=None) as ex:

            links = as_completed(ex.submit(self._get_link, page, i) for i in range(lo, hi + 1))
            paths = as_completed(ex.submit(self._fetch_torrent, i, subdir) for f in links for i in f.result())

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
                return self.link_finder(html.fromstring(r.content))
        else:
            print(f"Downloading page {n} failed.")
            return ()

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


class CJKMteamScraper(MteamScraper):
    def __init__(self, *args, **kwargs) -> None:

        super().__init__(*args, **kwargs)

        self.table_finder = etree.XPath(
            '//*[@id="form_torrent"]/table[@class="torrents"]//*[@class="torrenttr"]/table[@class="torrentname"]'
        )
        self.title_finder = etree.XPath('(.//a[contains(@href, "details.php")]/@title)[1]')
        self.link_finder = etree.XPath('(.//a[contains(@href, "download.php")]/@href)[1]')

    def _get_link(self, page: str, n: int):

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

        result = []
        title_finder = self.title_finder
        link_finder = self.link_finder
        for table in self.table_finder(html.fromstring(r.content)):
            try:
                if self._contains_cjk(title_finder(table)[0]):
                    result.append(link_finder(table)[0])
            except IndexError:
                pass
        return result

    @staticmethod
    def _contains_cjk(string: str):
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


class JavREBuilder:
    def __init__(
        self, report_dir: Path, remove_rare: bool = False, deep_fetch: bool = False, rare_thresh: int = 5
    ) -> None:

        self.kw_file = report_dir.joinpath("keyword.txt")
        self.prefix_file = report_dir.joinpath("id_prefix.txt")
        self.whitelist_file = report_dir.joinpath("id_whitelist.txt")
        self.rare_file = report_dir.joinpath("id_rare.txt")
        self.output_file = report_dir.joinpath("regex.txt")

        self.remove_rare = remove_rare
        if deep_fetch:
            self.limit = {"mteam": 500, "javbus": float("inf"), "javdb": 80}
        else:
            self.limit = {"mteam": 20, "javbus": 50, "javdb": 20}
        self.rare_thresh = rare_thresh

        self.mtscraper = CJKMteamScraper()
        self.session = self.mtscraper.session
        self.session.cookies.set_cookie(
            requests.cookies.create_cookie(domain="www.javbus.com", name="existmag", value="all")
        )

    def run(self):

        self.kw_regex = self._read_file(self.kw_file, "Keywords", self._keyword_strategy, True)
        self.fromweb = self._web_scrape(re.compile(self.kw_regex).fullmatch)
        self.prefix_regex = self._read_file(self.prefix_file, "ID Prefix", self._prefix_strategy, False)

        self.regex = f"(^|[^a-z0-9])({self.kw_regex}|[0-9]{{,3}}{self.prefix_regex}[ _-]?[0-9]{{2,6}})([^a-z0-9]|$)\n"
        self._write_file(self.output_file, self.regex)

    def _read_file(self, file: Path, name: str, strategy, omitParen: bool):

        with file.open("r+", encoding="utf-8") as f:
            old_list = f.read().splitlines()
            new_list = strategy(old_list)

            if old_list != new_list:
                f.seek(0)
                f.writelines(i + "\n" for i in new_list)
                f.truncate()
                print(f"{name} updated.")

        return self._get_regex(new_list, name, omitParen)

    def _keyword_strategy(self, old_list: list) -> list:
        return sorted(self._normalize_file(old_list))

    def _prefix_strategy(self, old_list: list) -> list:

        new_set = set(Regen(self._normalize_file(old_list)).to_text())
        new_set.difference_update(self.fromweb)

        try:
            with self.whitelist_file.open("r", encoding="utf-8") as f:
                whitelist = self._normalize_file(f)
            new_set.difference_update(whitelist)
            self.fromweb.difference_update(whitelist)

            self._write_file(self.whitelist_file, "\n".join(sorted(whitelist)) + "\n")
        except FileNotFoundError:
            pass

        thresh = self.rare_thresh
        get_count = self.prefix_counter.get
        rare = [(i, k) for k in new_set if (i := get_count(k, 0)) < thresh]
        rare.sort(reverse=True)

        if rare and self.remove_rare:
            new_set.difference_update(map(itemgetter(1), rare))
        self._write_file(self.rare_file, "".join(f"{i}: {k}\n" for i, k in rare))

        new_list = list(new_set)
        new_list.extend(self.fromweb)
        new_list.sort()
        return new_list

    @staticmethod
    def _normalize_file(wordlist):
        return set(map(str.lower, filter(None, map(str.strip, wordlist))))

    @staticmethod
    def _get_regex(wordlist: list, name: str, omitOuterParen: bool) -> str:

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

    def _web_scrape(self, kw_filter: re.Pattern.fullmatch) -> set:

        result = set(self._scrape_mteam())
        result.update(self._normalize_id(chain(self._scrape_javbus(), self._scrape_javdb(), self._scrape_github())))

        thresh = self.rare_thresh
        self.prefix_counter = Counter(map(itemgetter(0), result))
        final = {k for k, v in self.prefix_counter.items() if v >= thresh and not kw_filter(k)}

        print(f"Uniq ID: {len(result)}. Unid prefix: {len(self.prefix_counter)}. Final: {len(final)}.")
        return final

    @staticmethod
    def _normalize_id(wordlist):

        matcher = re.compile(r"\s*([a-z]{3,7})[ _-]?0*([0-9]{2,5})(?:[^0-9]|$)").match
        for m in filter(None, map(matcher, map(str.lower, wordlist))):
            yield m.group(1, 2)

    def _scrape_mteam(self):

        page = "adult.php?cat410=1&cat429=1&cat426=1&cat437=1&cat431=1&cat432=1"
        print(f'Scraping MTeam... limit: {self.limit["mteam"]}')

        matcher = re.compile(
            r"(?:^|/)(?:[0-9]{3})?([a-z]{3,6})-0*([0-9]{2,4})(?:hhb[0-9]?)?\b.*\.(?:mp4|wmv|avi|iso|m2ts)$",
            flags=re.MULTILINE,
        ).search

        files = self.mtscraper.fetch(page, "av", 1, self.limit["mteam"])
        for m in filter(None, map(matcher, chain.from_iterable(files))):
            yield m.group(1, 2)

    def _scrape_javbus(self):

        print(f'Scraping javbus... limit: {self.limit["javbus"]}')
        xpath = etree.XPath('//div[@id="waterfall"]//a[@class="movie-box"]//span/date[1]/text()')
        step = min(self.limit["javbus"], 500)

        for base in ("page", "uncensored/page", "genre/hd", "uncensored/genre/hd"):
            idx = 1

            with ThreadPoolExecutor(max_workers=None) as ex:

                while idx < self.limit["javbus"]:

                    if self.limit["javbus"] == float("inf"):
                        print(f"Page: {base}/{idx}")

                    product = ((f"https://www.javbus.com/{base}/{i}", xpath) for i in range(idx, idx + step))
                    try:
                        yield from chain.from_iterable(filter(None, ex.map(self._scrap_jav, product)))
                    except LastPageReached:
                        ex.shutdown(wait=False)
                        break

                    idx += step

    def _scrape_javdb(self):

        print(f'Scraping javdb... limit: {self.limit["javdb"]}')
        xpath = etree.XPath('//*[@id="videos"]//a/div[@class="uid"]/text()')

        for base in ("https://javdb.com/uncensored", "https://javdb.com/"):
            with ThreadPoolExecutor(max_workers=3) as ex:
                product = ((f"{base}?page={i}", xpath) for i in range(1, self.limit["javdb"] + 1))
                try:
                    yield from chain.from_iterable(filter(None, ex.map(self._scrap_jav, product)))
                except LastPageReached:
                    ex.shutdown(wait=False)

    def _scrap_jav(self, arg) -> list:

        url, xpath = arg

        for _ in range(3):
            try:
                res = self.session.get(url, timeout=7)
                if res.status_code == 404:
                    raise LastPageReached
                res.raise_for_status()
            except requests.RequestException:
                pass
            else:
                return xpath(html.fromstring(res.content))
        else:
            print("Downloading page error:", url)
            raise requests.RequestException

    def _scrape_github(self):

        url = "https://raw.githubusercontent.com/imfht/fanhaodaquan/master/data/codes.json"
        print("Downloading github database...")

        for _ in range(3):
            try:
                return self.session.get(url).json()
            except requests.RequestException:
                pass
        else:
            raise requests.RequestException

    @staticmethod
    def _write_file(file: Path, string: str):

        try:
            with file.open(mode="r+", encoding="utf-8") as f:
                if f.read() == string:
                    return
                f.seek(0)
                f.write(string)
                f.truncate()

        except FileNotFoundError:
            with file.open(mode="w", encoding="utf-8") as f:
                f.write(string)

        print(f"{file.name} updated.")


def analyze_av(lo: int, hi: int, av_matcher: re.Pattern.search):

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


def is_video(string: str):
    return string.rstrip().endswith((".mp4", ".wmv", ".avi", ".iso", ".m2ts"))


def analyze_non_av(lo: int, hi: int, av_matcher: re.Pattern.search):

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


def parse_arguments():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "build and test regex.\n"
            "\nbuild:\n"
            "   %(prog)s\n"
            "   %(prog)s -r -d\n"
            "\ntest:\n"
            "   %(prog)s -m match\n"
            "   %(prog)s -m match 100\n"
            "   %(prog)s -m miss 500 600\n"
        ),
    )

    parser.add_argument(
        "-m",
        "--mode",
        dest="mode",
        action="store",
        default="build",
        choices=("build", "match", "miss"),
        help=(
            "build: build and save regex to file (default)\n"
            "match: test regex with av torrents\n"
            "miss: test regex with non-av torrents"
        ),
    )
    parser.add_argument(
        "-r",
        "--remove-rare",
        dest="remove_rare",
        action="store_true",
        help="when building regex, remove rare id prefixes",
    )
    parser.add_argument(
        "-d",
        "--deep-fetch",
        dest="deep_fetch",
        action="store_true",
        help="when building regex, fetch more torrents from web",
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
        if len(args.range) == 1:
            args.range.insert(0, 0)
        elif len(args.range) != 2 or args.range[0] >= args.range[1]:
            parser.error("Ranges should be 1 or 2 integers (low to high)")

    return args


def main():

    args = parse_arguments()

    if args.mode == "build":

        builder = JavREBuilder(SCRIPT_DIR, args.remove_rare, args.deep_fetch)
        builder.run()

        print("Regex:")
        print(builder.regex)
        print("Length:", len(builder.regex))

    else:

        for dir in "av", "non_av":
            dir = REPORT_DIR.joinpath(dir)
            try:
                if not dir.exists():
                    dir.mkdir(parents=True)
            except OSError as e:
                print(f'Creating "{dir}" failed: {e}')
                sys.exit()

        with open(SCRIPT_DIR.joinpath("regex.txt"), "r", encoding="utf-8") as f:
            av_matcher = re.compile(f.read().strip(), flags=re.MULTILINE).search

        if args.mode == "match":
            analyze_av(*args.range, av_matcher)
        else:
            analyze_non_av(*args.range, av_matcher)


if __name__ == "__main__":
    main()
