#!/usr/bin/env python3

import os.path

import re_compute


def read_file(file: str, extract=False):
    path = os.path.join(os.path.dirname(__file__), file)
    with open(path, mode="r+", encoding="utf-8") as f:
        o_list = f.read().splitlines()
        s_list = {i.lower() for i in o_list if i}
        if extract:
            s_list = re_compute.extract_regex(*s_list)
        s_list = sorted(s_list)

        if o_list != s_list:
            f.seek(0)
            f.write("\n".join(s_list) + "\n")
            f.truncate()
            print(f"{file} updated.")
    return s_list


def write_file(file: str, content: str, checkDiff=True):
    path = os.path.join(os.path.dirname(__file__), file)
    with open(path, mode="r+", encoding="utf-8") as f:
        if checkDiff:
            old = f.read()
            if old == content:
                print(f"{file} skiped.")
                return
            f.seek(0)
        f.write(content)
        f.truncate()
        print(f"{file} updated.")


def optimize_regex(rlist: list):
    computed = re_compute.compute_regex(rlist)
    assert re_compute.unit_test(rlist, computed)
    return computed


def main():
    av_keyword = "|".join(read_file("av_keyword.txt", extract=False))

    av_censored_id = read_file("av_censored_id.txt", extract=True)
    av_uncencored_id = read_file("av_uncencored_id.txt", extract=True)

    set_av_uncencored_id = set(av_uncencored_id)
    intersect = set_av_uncencored_id.intersection(av_censored_id)
    if intersect:
        set_av_uncencored_id.difference_update(intersect)
        av_uncencored_id = sorted(set_av_uncencored_id)
        write_file("av_uncencored_id.txt", "\n".join(av_uncencored_id) + "\n", checkDiff=False)

    av_censored_id = optimize_regex(av_censored_id)
    av_uncencored_id = optimize_regex(av_uncencored_id)

    avReg = f"(^|[^a-z0-9])({av_keyword}|{av_uncencored_id}[ _-]*[0-9]{{2,6}}|[0-9]{{,4}}{av_censored_id}[ _-]*[0-9]{{2,6}}(hhb[1-9]?)?)([^a-z0-9]|$)\n"
    write_file("av_regex.txt", avReg, checkDiff=True)


if __name__ == "__main__":
    main()
