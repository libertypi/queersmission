#!/usr/bin/env python3

from collections import defaultdict
import sys
import os.path
import re


def read_file(file, optimize=False):
    file = os.path.join(sys.path[0], file)

    with open(file, mode="r+", encoding="utf-8") as f:
        org = [i.strip() for i in f.readlines()]

        if optimize:
            rlist = org[:]
            optimize_regex(rlist)
        else:
            rlist = sorted(i.lower() for i in org if i)

        if rlist != org:
            f.seek(0)
            f.writelines(f"{i}\n" for i in rlist)
            f.truncate()

    if optimize:
        return "|".join(rlist).lower()
    else:
        return "|".join(rlist)


def optimize_regex(rlist):
    group = defaultdict(set)
    for regex in rlist:
        if not regex:
            continue
        regex = regex.upper()

        p = regex.find("(")
        if p == -1:
            p = 2
        elif p != 2:
            print("Irregular Expression: ", regex)

        key = regex[:p]
        val = regex[p:]

        if val.startswith("("):
            if val.endswith(")?"):
                group[key].add("")
                val = val[1:-2]
            elif val.endswith(")"):
                val = val[1:-1]
            else:
                raise ValueError(f"Regex: '{val}'")

        if val.strip("|") != val:
            raise ValueError(f"Regex: '{val}'")

        if "|" in val:
            i = p = 0
            for j, c in enumerate(val):
                if c == "|" and p == 0:
                    group[key].add(val[i:j])
                    i = j + 1
                elif c == "(":
                    p += 1
                elif c == ")":
                    p -= 1
            if p != 0:
                raise ValueError(f"Regex: '{val}'")
            group[key].add(val[i:])
        else:
            group[key].add(val)

    rlist.clear()
    for key, val in sorted(group.items()):
        char = tuple(i for i in val if re.fullmatch(r"(\[[^]]+\]|[A-Z0-9])\??", i))
        if char:
            val.difference_update(char)
            if any(i.endswith("?") for i in char):
                val.add("")
            char = [c for i in char for c in i if c.isalnum()]
            if len(char) > 1:
                char.sort()
                char = f'[{"".join(char)}]'
            else:
                char = char[0]
            val.add(char)

        if len(val) == 1:
            rlist.append("".join((key, *val)))
            continue

        q = False
        if "" in val:
            val.discard("")
            if len(val) == 1 and all(c.startswith("[") or len(c) == 1 for c in val):
                rlist.append("".join((key, *val, "?")))
                continue
            q = True

        rlist.append(f'{key}({"|".join(sorted(val))}){"?" if q else ""}')


if __name__ == "__main__":
    re_template = """(^|[^a-z0-9])(__AV_KEYWORD__|[0-9]{,3}(__AV_ID_PREFIX__)([[:space:]_-]?[0-9]{2,6}|[0-9]{3,6}hhb[0-9]?))([^a-z0-9]|$)\n"""

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

