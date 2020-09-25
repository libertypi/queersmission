#!/usr/bin/env python3

import os.path
import sys

import re_compute


def read_file(file, optimize=False):
    file = os.path.join(sys.path[0], file)

    with open(file, mode="r+", encoding="utf-8") as f:

        if optimize:
            orgf = f.read()
            org = tuple(i for i in orgf.splitlines() if i)

            rlist = [i.upper() for i in re_compute.extract_regex(*org)]
            rlist.sort()

            extracted = set(i.lower() for i in rlist)
            print(f"Original string length: {len(orgf)}")

            computed = re_compute.compute_regex(extracted)
            print(f"Computed regex length: {len(computed)}")

            assert re_compute.unit_test(extracted, computed) == True
        else:
            org = [i.strip() for i in f.readlines()]
            rlist = sorted(set(i.lower() for i in org if i))

        if rlist != org:
            f.seek(0)
            f.writelines(f"{i}\n" for i in rlist)
            f.truncate()

    if optimize:
        return computed
    else:
        return "|".join(rlist)


if __name__ == "__main__":
    av_keyword = read_file("av_keyword.txt")
    av_censored_id = read_file("av_censored_id.txt", optimize=True)
    av_uncencored_id = read_file("av_uncencored_id.txt", optimize=True)

    regex = f"(^|[^a-z0-9])({av_keyword}|[0-9]{{,4}}{av_censored_id}[[:space:]_-]*[0-9]{{2,6}}(hhb[1-9]?)?|{av_uncencored_id}[[:space:]_-]*[0-9]{{2,6}})([^a-z0-9]|$)\n"

    with open(os.path.join(sys.path[0], "av_regex.txt"), mode="r+", encoding="utf-8") as f:
        oldRegex = f.read()
        if regex != oldRegex:
            f.seek(0)
            f.write(regex)
            f.truncate()
            print("Updated.")
        else:
            print("Skiped.")
