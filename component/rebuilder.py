#!/usr/bin/env python3

import argparse
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from operator import itemgetter
from pathlib import Path

import requests
from lxml import etree, html

scriptDir = Path(__file__).parent
sys.path.insert(0, str(scriptDir.joinpath("../../regenerator").resolve()))

from regenerator import Regen

from mteam_analyzer import MteamScraper


class LastPageReached(Exception):
    pass


class MtCJKScraper(MteamScraper):
    def __init__(self, *args, **kwargs) -> None:

        super().__init__(*args, **kwargs)

        self.table_finder = etree.XPath(
            '//*[@id="form_torrent"]/table[@class="torrents"]//*[@class="torrenttr"]/table[@class="torrentname"]'
        )
        self.title_finder = etree.XPath('(.//a[contains(@href, "details.php")]/@title)[1]')
        self.link_finder = etree.XPath('.//a[contains(@href, "download.php")]/@href')

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
            except (TypeError, IndexError):
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


class JavReBuilder:
    def __init__(self, basedir: Path, remove_rare: bool = False, deep_fetch: bool = False) -> None:

        self.kw_file = basedir.joinpath("keyword.txt")
        self.prefix_file = basedir.joinpath("id_prefix.txt")
        self.whitelist_file = basedir.joinpath("id_whitelist.txt")
        self.rare_file = basedir.joinpath("id_rare.txt")
        self.output_file = basedir.joinpath("regex.txt")

        self.remove_rare = remove_rare
        if deep_fetch:
            self.limit = {"mteam": 500, "javbus": float("inf"), "javdb": 80}
        else:
            self.limit = {"mteam": 20, "javbus": 50, "javdb": 20}

        self.mtscraper = MtCJKScraper()
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

    @staticmethod
    def _keyword_strategy(old_list: list) -> list:

        return sorted(set(map(str.lower, filter(None, old_list))))

    def _prefix_strategy(self, old_list: list) -> list:

        new_set = set(Regen(tuple(map(str.lower, filter(None, old_list)))).to_text())
        new_set.difference_update(self.fromweb)

        try:
            with self.whitelist_file.open("r", encoding="utf-8") as f:
                whitelist = set(filter(None, map(str.strip, f)))
            new_set.difference_update(whitelist)
            self.fromweb.difference_update(whitelist)

            self._write_file(self.whitelist_file, "\n".join(sorted(whitelist)) + "\n")
        except FileNotFoundError:
            pass

        rare = [(i, k) for k in new_set if (i := self.prefix_counter.get(k, 0)) <= 3]
        rare.sort(reverse=True)

        if rare and self.remove_rare:
            new_set.difference_update(map(itemgetter(1), rare))
        self._write_file(self.rare_file, "".join(f"{i}: {k}\n" for i, k in rare))

        new_list = list(new_set)
        new_list.extend(self.fromweb)
        new_list.sort()
        return new_list

    @staticmethod
    def _get_regex(wordlist, name: str, omitOuterParen: bool) -> str:

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

        self.prefix_counter = Counter(map(itemgetter(0), result))
        final = {k for k, v in self.prefix_counter.items() if v >= 5 and not kw_filter(k)}

        print(f"Uniq ID: {len(result)}. Unid prefix: {len(self.prefix_counter)}. Final: {len(final)}.")
        return final

    @staticmethod
    def _normalize_id(wordlist):

        matcher = re.compile(r"\s*([a-z]{3,6})[ _-]?0*([0-9]{2,4})").match
        matches = map(matcher, map(str.lower, wordlist))
        for m in filter(None, matches):
            yield m.group(1, 2)

    def _scrape_mteam(self):

        page = "adult.php?cat410=1&cat429=1&cat426=1&cat437=1&cat431=1&cat432=1"
        print(f'Scraping MTeam... limit: {self.limit["mteam"]}')

        matcher = re.compile(
            r"(?:^|/)(?:[0-9]{3})?([a-z]{3,6})-0*([0-9]{2,4})(?:hhb[0-9]?)?\b.*\.(?:mp4|wmv|avi|iso|m2ts)$",
            flags=re.MULTILINE,
        ).search

        for f in self.mtscraper.fetch(page, "av", 1, self.limit["mteam"]):
            for m in filter(None, map(matcher, f)):
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
                        for result in filter(None, ex.map(self._scrap_jav, product)):
                            for uid in result:
                                yield uid
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
                    for result in filter(None, ex.map(self._scrap_jav, product)):
                        for uid in result:
                            yield uid
                except LastPageReached:
                    ex.shutdown(wait=False)

    def _scrap_jav(self, arg):

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

        print(f"{file} updated.")


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-r",
        "--remove-rare",
        dest="remove_rare",
        action="store_true",
        help="remove rare id prefix (less than 5 occurrence)",
    )
    parser.add_argument(
        "-d",
        "--deep-fetch",
        dest="deep_fetch",
        action="store_true",
        help="fetch more torrents from web (slower)",
    )
    return parser.parse_args()


def main():

    args = parse_arguments()

    builder = JavReBuilder(scriptDir, args.remove_rare, args.deep_fetch)
    builder.run()

    print("Regex:")
    print(builder.regex)
    print("Length:", len(builder.regex))


if __name__ == "__main__":
    main()
