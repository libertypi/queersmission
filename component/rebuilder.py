#!/usr/bin/env python3

import os.path
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import regenerator as regen


def read_file(file: str, extractWriteBack: bool = False):
    path = os.path.join(os.path.dirname(__file__), file)

    with open(path, mode="r+", encoding="utf-8") as f:

        o_list = f.read().splitlines()
        s_list = {i.lower() for i in o_list if i}
        extracters = tuple(map(regen.Extractor, s_list))

        if extractWriteBack:
            s_list = [j for i in extracters for j in i.get_text()]
        else:
            s_list = list(s_list)
        s_list.sort()

        if o_list != s_list:
            f.seek(0)
            f.write("\n".join(s_list))
            f.write("\n")
            f.truncate()
            print(f"{file} updated.")

    return extracters, s_list


def write_file(file: str, content: str, checkDiff: bool = True):
    path = os.path.join(os.path.dirname(__file__), file)

    if checkDiff:
        try:
            with open(path, mode="r", encoding="utf-8") as f:
                old = f.read()
            if old == content:
                print(f"{file} skiped.")
                return
        except FileNotFoundError:
            pass

    with open(path, mode="w", encoding="utf-8") as f:
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")

        print(f"{file} updated.")


def optimize_regex(extractors: list, wordlist: list, name: str, test: bool = True) -> str:
    computed = regen.Optimizer(*extractors).result

    concat = "|".join(wordlist)
    if len(wordlist) > 1:
        concat = f"({concat})"

    diff = len(computed) - len(concat)
    if diff > 0:
        print(f"{name}: Computed regex is {diff} characters longer than concatenation, use the latter.")
        return concat

    if test:
        regen.test_regex(regex=computed, wordlist=wordlist)
        print(f"{name}: Regex test passed. Characters saved: {-diff}.")

    return computed


def main():
    kwExtractors, kwList = read_file("av_keyword.txt", extractWriteBack=False)

    cidExtractors, cidList = read_file("av_censored_id.txt", extractWriteBack=True)
    ucidExtractors, ucidList = read_file("av_uncensored_id.txt", extractWriteBack=True)

    remove = set(ucidList)
    removeLength = len(remove)
    remove.difference_update(cidList)
    if len(remove) != removeLength:
        ucidList = sorted(remove)
        ucidExtractors = map(regen.Extractor, remove)
        write_file("av_uncensored_id.txt", "\n".join(ucidList), checkDiff=False)

    av_keyword = optimize_regex(kwExtractors, kwList, "Keywords", False)
    if av_keyword.startswith("(") and av_keyword.endswith(")"):
        av_keyword = av_keyword[1:-1]

    av_censored_id = optimize_regex(cidExtractors, cidList, "Censored ID")
    av_uncensored_id = optimize_regex(ucidExtractors, ucidList, "Uncensored ID")

    avReg = f"(^|[^a-z0-9])({av_keyword}|{av_uncensored_id}[ _-]*[0-9]{{2,6}}|[0-9]{{,4}}{av_censored_id}[ _-]*[0-9]{{2,6}})([^a-z0-9]|$)"
    write_file("av_regex.txt", avReg, checkDiff=True)

    print("Regex:")
    print(avReg)
    print("Length:", len(avReg))


if __name__ == "__main__":
    main()
