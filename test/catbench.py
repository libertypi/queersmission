#!/usr/bin/env python3
"""
Benchmark Categorizer with M-Team data.

Requirement:
- SQLite database by MTSearch (https://github.com/libertypi/mtsearch)

Author:
David P.
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import defaultdict
from itertools import islice
from pathlib import Path

ENTRY_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENTRY_DIR))

from queersmission.cat import Cat, Categorizer, normstr
from queersmission.utils import humansize

DEFAULT_DB_PATH = "mtsearch/profile/data.db"
MTEAM_TO_CAT = {
    100: (Cat.MOVIES,),  # 电影
    105: (Cat.TV_SHOWS,),  # 影剧/综艺
    110: (Cat.MUSIC,),  # Music
    115: (Cat.AV,),  # AV(有码)
    120: (Cat.AV,),  # AV(无码)
    401: (Cat.MOVIES,),  # 电影/SD
    402: (Cat.TV_SHOWS, Cat.MOVIES),  # 影剧/综艺/HD
    403: (Cat.TV_SHOWS,),  # 影剧/综艺/SD
    404: (Cat.MOVIES, Cat.TV_SHOWS),  # 纪录
    405: (Cat.TV_SHOWS, Cat.MOVIES),  # 动画
    406: (Cat.MOVIES, Cat.MUSIC),  # 演唱
    407: (Cat.MOVIES, Cat.TV_SHOWS),  # 运动
    408: (Cat.MUSIC,),  # Music (AAC/ALAC)
    409: (Cat.DEFAULT,),  # Misc(其他)
    410: (Cat.AV,),  # AV(有码)/HD Censored
    411: (Cat.AV, Cat.DEFAULT),  # H-游戏
    412: (Cat.AV,),  # H-动漫
    413: (Cat.AV, Cat.DEFAULT),  # H-漫画
    419: (Cat.MOVIES,),  # 电影/HD
    420: (Cat.MOVIES,),  # 电影/DVDiSo
    421: (Cat.MOVIES,),  # 电影/Blu-Ray
    422: (Cat.DEFAULT,),  # 软件
    423: (Cat.DEFAULT,),  # PC游戏
    424: (Cat.AV,),  # AV(有码)/SD Censored
    425: (Cat.AV, Cat.DEFAULT),  # IV(写真影集)
    426: (Cat.AV,),  # AV(无码)/DVDiSo Uncensored
    427: (Cat.DEFAULT,),  # 电子书
    429: (Cat.AV,),  # AV(无码)/HD Uncensored
    430: (Cat.AV,),  # AV(无码)/SD Uncensored
    431: (Cat.AV,),  # AV(有码)/Blu-Ray Censored
    432: (Cat.AV,),  # AV(无码)/Blu-Ray Uncensored
    433: (Cat.AV, Cat.DEFAULT),  # IV(写真图集)
    434: (Cat.MUSIC,),  # Music (无损)
    435: (Cat.TV_SHOWS,),  # 影剧/综艺/DVDiSo
    436: (Cat.AV,),  # AV(网站)/0Day
    437: (Cat.AV,),  # AV(有码)/DVDiSo Censored
    438: (Cat.TV_SHOWS,),  # 影剧/综艺/BD
    439: (Cat.MOVIES,),  # 电影/Remux
    440: (Cat.AV,),  # AV(Gay)/HD
    441: (Cat.MOVIES, Cat.TV_SHOWS),  # 教育(影片)
    442: (Cat.MUSIC,),  # 有声书
    443: (Cat.DEFAULT,),  # 教育
    444: (Cat.MOVIES, Cat.TV_SHOWS),  # 纪录
    445: (Cat.AV,),  # IV
    446: (Cat.AV,),  # H-ACG
    447: (Cat.DEFAULT,),  # 游戏
    448: (Cat.DEFAULT,),  # TV游戏
    449: (Cat.TV_SHOWS,),  # 动漫
    450: (Cat.DEFAULT,),  # 其他
    451: (Cat.MOVIES, Cat.TV_SHOWS),  # 教育影片
}


class CatBench:

    def __init__(self, db_path: Path, store_json: bool = False):

        self.db_path = db_path
        self.store_json = store_json

        p = Path(__file__)
        self.logpath = p.with_name(p.stem + "_log.txt")
        self.jsonpath = p.with_name(p.stem + "_log.json")

        self.categorizer = Categorizer()

        # Make sure it's compiled the same way as in Categorizer
        self._av_search = re.compile(
            self.categorizer._patterns["av_regex"], re.ASCII
        ).search

        self.conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        self.mt_cats = dict(self.conn.execute("SELECT id, nameCht FROM categories"))

        self.logfd = self.logpath.open("w", encoding="utf-8")

    def av_search(self, s: str):
        return self._av_search(normstr(s))

    def examine_mt_cat(self):
        """Examine M-Team category IDs in the database."""
        for _id in self.mt_cats.keys() - MTEAM_TO_CAT:
            raise ValueError(
                f"Unknown category ID found in Database: {_id}, name: {self.mt_cats[_id]}. "
                "Update MTEAM_TO_CAT mapping in the tester code."
            )

    @staticmethod
    def _construct_query(
        ids: list[int] | None,
        max_items: int | None,
        id_lo: int | None,
        id_hi: int | None,
        in_mt_cats: list[int] | None,
        ex_mt_cats: list[int] | None,
    ):
        """Construct SQL queries for torrents and files based on filters."""
        if ids:
            t_sql = f"""
                SELECT id, category, name, length
                FROM torrents
                WHERE id IN ({_ph(ids)})
                ORDER BY id DESC
            """.strip()
            f_sql = f"""
                SELECT id, path, length
                FROM files
                WHERE id IN ({_ph(ids)})
                ORDER BY id DESC
            """.strip()
            return t_sql, ids, f_sql, ids

        where_parts = []
        t_params = []

        if id_lo is not None:
            where_parts.append("t.id >= ?")
            t_params.append(id_lo)
        if id_hi is not None:
            where_parts.append("t.id <= ?")
            t_params.append(id_hi)
        if in_mt_cats:
            where_parts.append(f"t.category IN ({_ph(in_mt_cats)})")
            t_params.extend(in_mt_cats)
        if ex_mt_cats:
            where_parts.append(f"t.category NOT IN ({_ph(ex_mt_cats)})")
            t_params.extend(ex_mt_cats)

        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        f_params = t_params.copy()

        if max_items and max_items > 0:
            limit_sql = "LIMIT ?"
            t_params.append(max_items)
        else:
            limit_sql = ""

        t_sql = f"""
            SELECT id, category, name, length
            FROM torrents AS t
            {where_sql}
            ORDER BY id DESC
            {limit_sql}
        """.strip()
        f_sql = f"""
            SELECT f.id, f.path, f.length
            FROM files AS f
            JOIN torrents AS t ON f.id = t.id
            {where_sql}
            ORDER BY f.id DESC
        """.strip()
        return t_sql, t_params, f_sql, f_params

    def iter_torrents(
        self,
        ids: list[int] | None,
        max_items: int | None,
        id_lo: int | None,
        id_hi: int | None,
        in_mt_cats: list[int] | None,
        ex_mt_cats: list[int] | None,
    ):
        """Iterate over MTEAM torrents. Yields (tid, mt_id, name, files)."""
        t_sql, t_params, f_sql, f_params = self._construct_query(
            ids=ids,
            max_items=max_items,
            id_lo=id_lo,
            id_hi=id_hi,
            in_mt_cats=in_mt_cats,
            ex_mt_cats=ex_mt_cats,
        )
        ffetch = self.conn.execute(f_sql, f_params).fetchone
        frow = ffetch()

        for tid, mt_id, name, tlen in self.conn.execute(t_sql, t_params):
            # Advance file cursor to current torrent ID
            while frow and frow[0] > tid:
                frow = ffetch()

            # Collect all files for this torrent
            files = []
            while frow and frow[0] == tid:
                files.append({"name": f"{name}/{frow[1]}", "length": frow[2]})
                frow = ffetch()

            if files:
                # Maintain original order
                files.reverse()
            else:
                # Single-file torrent
                files.append({"name": name, "length": tlen})

            yield tid, mt_id, name, files

    def run(
        self,
        ids: list[int] | None,
        max_items: int | None,
        id_lo: int | None,
        id_hi: int | None,
        in_mt_cats: list[int] | None,
        ex_mt_cats: list[int] | None,
    ):

        total = mismatch = 0
        elapsed_sum = 0.0
        mismatch_files = []
        av_fp = defaultdict(list)

        store_json = self.store_json
        mt_to_cat = MTEAM_TO_CAT
        cat_av = Cat.AV
        infer = self.categorizer.infer
        stderr_write = sys.stderr.write
        fmt = "\rMismatch: {}/{}, rate: {:.2%}".format

        perf = time.perf_counter
        wall_start = perf()

        for tid, mt_id, name, files in self.iter_torrents(
            ids=ids,
            max_items=max_items,
            id_lo=id_lo,
            id_hi=id_hi,
            in_mt_cats=in_mt_cats,
            ex_mt_cats=ex_mt_cats,
        ):
            total += 1
            t0 = perf()
            inferred = infer(files)
            elapsed_sum += perf() - t0

            expected = mt_to_cat[mt_id]
            if inferred in expected:
                continue

            mismatch += 1
            stderr_write(fmt(mismatch, total, mismatch / total))

            self.write_log(
                tid=tid,
                mt_id=mt_id,
                expected=expected,
                inferred=inferred,
                name=name,
                files=files,
            )

            if inferred == cat_av:
                m = self.av_search(name)
                if not m:
                    for f in files:
                        m = self.av_search(f["name"])
                        if m:
                            break
                if m:
                    av_fp[m[0]].append(m.string)
                else:
                    av_fp["- N/A -"].append(name)

            if store_json:
                mismatch_files.append([f["name"] for f in files])

        # Mismatches JSON log
        if store_json:
            with self.jsonpath.open("w", encoding="utf-8") as f:
                json.dump(mismatch_files, f, ensure_ascii=False, separators=(",", ":"))
            del mismatch_files

        # AV False Positives Summary
        av_fp_sum = self.write_av_summary(av_fp)

        # Summary
        wall_time = perf() - wall_start
        matched = total - mismatch
        perf_line = "n/a"

        if total > 0:
            sys.stderr.write("\r\033[2K")  # Clear mismatch line
            match_rate = matched / total
            mismatch_rate = mismatch / total
            if elapsed_sum > 0:
                perf_line = "avg {:.6f} s/torrent | {:.2f} torrents/s".format(
                    elapsed_sum / total, total / elapsed_sum
                )
        else:
            match_rate = mismatch_rate = 0.0

        print(
            "Summary:\n"
            f"  Database :  {self.db_path}\n"
            f"  Total    :  {total}\n"
            f"  Match    :  {matched} ({match_rate:.2%})\n"
            f"  Mismatch :  {mismatch} ({mismatch_rate:.2%})\n"
            f"  AV FP    :  {av_fp_sum}\n"
            f"  Perf     :  {perf_line}  (sum {elapsed_sum:.3f}s)\n"
            f"  Wall time:  {wall_time:.3f}s\n"
            f"  Log file :  {self.logpath}"
        )

    def write_log(
        self,
        tid: int,
        mt_id: int,
        expected: tuple,
        inferred: Cat,
        name: str,
        files: list,
        limit: int = 20,
    ):
        write = self.logfd.write
        f1 = "{:8}: {}\n".format
        f2 = (" " * 10 + "{}\n").format

        write(f1("ID", tid))
        write(f1("MT-TEAM", f"{self.mt_cats.get(mt_id, 'Unknown')} [{mt_id}]"))
        write(f1("EXPECTED", "/".join(e.name for e in expected)))
        write(f1("INFERRED", inferred.name))
        write(f1("NAME", name))

        # List files (up to `limit`)
        it = islice((f"{f['name']} [{humansize(f['length'])}]" for f in files), limit)
        write(f1("FILES", next(it)))
        for line in it:
            write(f2(line))

        exceed = len(files) - limit
        if exceed > 0:
            write(f2(f"... and {exceed} more files"))

        write("\n")

    def write_av_summary(self, av_fp: dict):
        if not av_fp:
            return 0

        entries = sorted(
            ((m, len(paths), paths) for m, paths in av_fp.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        av_fp_sum = sum(m[1] for m in entries)
        w = max(map(len, av_fp))

        write = self.logfd.write
        write(f"---\n\nAV False Positives ({av_fp_sum}):\n\n")

        for m, count, paths in entries:
            write(f"{m:>{w}}: ({count} torrents)\n")
            for p in paths:
                write(f'{" ":{w}}  {p}\n')

        return av_fp_sum

    def close(self):
        self.conn.close()
        self.logfd.close()


def _ph(lst: list) -> str:
    """Generate placeholder string for SQL IN clause."""
    return ",".join("?" * len(lst))


def parse_args():

    parser = argparse.ArgumentParser(
        description="Testing the Categorizer with M-Team data."
    )

    filters = parser.add_argument_group("filters")
    filters.add_argument(
        "-i",
        dest="ids",
        nargs="+",
        type=int,
        help="Specify IDs to test (overwrite other filters).",
    )
    filters.add_argument(
        "-m",
        dest="max_items",
        type=int,
        help="Maximum number of IDs to test.",
    )
    filters.add_argument(
        "-L",
        dest="id_lo",
        type=int,
        help="Smallest ID to test.",
    )
    filters.add_argument(
        "-H",
        dest="id_hi",
        type=int,
        help="Largest ID to test.",
    )
    filters.add_argument(
        "-I",
        dest="in_mt_cats",
        nargs="+",
        type=int,
        help="Include only these M-Team category IDs.",
    )
    filters.add_argument(
        "-E",
        dest="ex_mt_cats",
        nargs="+",
        type=int,
        help="Exclude these M-Team category IDs.",
    )

    parser.add_argument(
        "-j",
        dest="store_json",
        action="store_true",
        help="Store mismatched files in JSON.",
    )
    parser.add_argument(
        "-t",
        dest="test_string",
        type=str,
        nargs="?",
        const="",
        help="Test string with AV_REGEX.",
    )
    parser.add_argument(
        dest="db_path",
        nargs="?",
        type=Path,
        help="Path to the database file.",
    )
    return parser.parse_args()


def ensure_db_path(db_path: Path | None) -> Path:
    if db_path:
        db_path = db_path.resolve()
    else:
        db_path = ENTRY_DIR.parent.joinpath(DEFAULT_DB_PATH)
    if db_path.is_file():
        return db_path
    raise FileNotFoundError("Database file not found. Please specify the correct path.")


def test_string(s: str, bench: CatBench):
    m = bench.av_search(s)
    if m:
        print(f"String: {s}\nMatch : {m[0]}")
    else:
        print("No match.")


def main():
    args = parse_args()
    bench = CatBench(ensure_db_path(args.db_path), args.store_json)
    try:
        if args.test_string is not None:
            if args.test_string:
                test_string(args.test_string, bench)
                return
            while True:
                s = input("Enter test string: ")
                if not s:
                    break
                test_string(s, bench)
        else:
            bench.examine_mt_cat()
            bench.run(
                ids=args.ids,
                max_items=args.max_items,
                id_lo=args.id_lo,
                id_hi=args.id_hi,
                in_mt_cats=args.in_mt_cats,
                ex_mt_cats=args.ex_mt_cats,
            )
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    finally:
        bench.close()


if __name__ == "__main__":
    main()
