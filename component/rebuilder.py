#!/usr/bin/env python3

import os.path
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../regenerator")))
from regenerator import Regen


def read_file(file: str, extractWriteback: bool = False) -> Regen:

    path = os.path.join(os.path.dirname(__file__), file)

    with open(path, mode="r+", encoding="utf-8") as f:

        o_list = f.read().splitlines()
        s_list = sorted({i.lower() for i in o_list if i})
        regen = Regen(s_list)

        if extractWriteback:
            s_list = list(regen.to_text())

        if o_list != s_list:
            f.seek(0)
            f.write("\n".join(s_list))
            f.write("\n")
            f.truncate()
            print(f"{file} updated.")

    return regen


def optimize_regex(regen: Regen, name: str, omitOuterParen: bool = False) -> str:

    wordlist = regen.wordlist
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


def write_file(file: str, content: str, checkDiff: bool = True):
    path = os.path.join(os.path.dirname(__file__), file)

    if checkDiff:
        try:
            with open(path, mode="r", encoding="utf-8") as f:
                old = f.read()
        except FileNotFoundError:
            pass
        else:
            if old == content:
                print(f"{file} skiped.")
                return

    with open(path, mode="w", encoding="utf-8") as f:
        f.write(content)
        print(f"{file} updated.")


def main():

    kwRegen = read_file("av_keyword.txt", extractWriteback=False)
    cidRegen = read_file("av_censored_id.txt", extractWriteback=True)
    ucidRegen = read_file("av_uncensored_id.txt", extractWriteback=True)

    source = set(ucidRegen.to_text())
    sourceLen = len(source)
    source.difference_update(cidRegen.to_text())
    if sourceLen != len(source):
        source = sorted(source)
        ucidRegen = Regen(source)
        write_file("av_uncensored_id.txt", "\n".join(source) + "\n", checkDiff=False)

    av_keyword = optimize_regex(kwRegen, "Keywords", omitOuterParen=True)
    av_censored_id = optimize_regex(cidRegen, "Censored ID")
    av_uncensored_id = optimize_regex(ucidRegen, "Uncensored ID")

    final_regex = f"(^|[^a-z0-9])({av_keyword}|{av_uncensored_id}[ _-]*[0-9]{{2,6}}|[0-9]{{,4}}{av_censored_id}[ _-]*[0-9]{{2,6}})([^a-z0-9]|$)\n"
    write_file("av_regex.txt", final_regex, checkDiff=True)

    print("Regex:")
    print(final_regex)
    print("Length:", len(final_regex))


if __name__ == "__main__":
    main()
