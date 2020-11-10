#!/usr/bin/env python3

import sys
from pathlib import Path

scriptDir = Path(__file__).parent
sys.path.insert(0, str(scriptDir.joinpath("../../regenerator").resolve()))

from regenerator import Regen


def read_file(file: str, extractWriteback: bool = False) -> Regen:

    path = scriptDir / file

    with path.open(mode="r+", encoding="utf-8") as f:

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


def write_file(file: str, content: str):

    path = scriptDir / file

    try:
        with path.open(mode="r+", encoding="utf-8") as f:
            if f.read() == content:
                print(f"{file} skiped.")
            else:
                f.seek(0)
                f.write(content)
                f.truncate()
                print(f"{file} updated.")

    except FileNotFoundError:
        with path.open(mode="w", encoding="utf-8") as f:
            f.write(content)
            print(f"{file} updated.")


def main():

    kwRegen = read_file("av_keyword.txt", extractWriteback=False)
    idRegen = read_file("av_id_prefix.txt", extractWriteback=True)

    av_keyword = optimize_regex(kwRegen, "Keywords", omitOuterParen=True)
    av_id_prefix = optimize_regex(idRegen, "ID Prefix")

    final_regex = f"(^|[^a-z0-9])({av_keyword}|[0-9]{{,3}}{av_id_prefix}[ _-]?[0-9]{{2,6}})([^a-z0-9]|$)\n"
    write_file("av_regex.txt", final_regex)

    print("Regex:")
    print(final_regex)
    print("Length:", len(final_regex))


if __name__ == "__main__":
    main()
