#!/usr/bin/env python3

import os.path
import re
import sys
from collections import defaultdict

import re_compute


def read_file(file, optimize=False):
    file = os.path.join(sys.path[0], file)

    with open(file, mode="r+", encoding="utf-8") as f:
        org = [i.strip() for i in f.readlines()]

        if optimize:
            rlist = [i.upper() for j in map(re_compute.extract_regex, org) for i in j]
            rlist.sort()
            extracted = set(i.lower() for i in rlist)
            computed = re_compute.compute_regex(extracted)
            assert re_compute.unit_test(extracted, computed) == True
        else:
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
    re_template = """(^|[^a-z0-9])(__AV_KEYWORD__|([1-9][0-9]{1,2})?__AV_ID_PREFIX__([[:space:]_-]?[0-9]{2,6}|[0-9]{3,6}hhb[1-9]?))([^a-z0-9]|$)\n"""

    av_keyword = read_file("av_keyword.txt")
    av_id_prefix = read_file("av_id_prefix.txt", True)

    re_template = re_template.replace("__AV_KEYWORD__", av_keyword, 1).replace(
        "__AV_ID_PREFIX__", av_id_prefix, 1
    )

    with open(
        os.path.join(sys.path[0], "av_regex.txt"), mode="r+", encoding="utf-8"
    ) as f:
        oldRegex = f.read()
        if re_template != oldRegex:
            f.seek(0)
            f.write(re_template)
            f.truncate()
            print("Updated.")
        else:
            print("Skiped.")
