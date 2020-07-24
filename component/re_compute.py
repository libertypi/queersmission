from collections import defaultdict
import re


def extract_regex(string: str) -> set:
    prefix = {""}
    substr = set()
    length = len(string)
    i = j = 0
    while i < length:
        if string[i] == "[":
            p = 1
            for c, s in enumerate(string[i + 1 :]):
                if s == "[":
                    p += 1
                elif s == "]":
                    p -= 1
                if p == 0:
                    break
            else:
                raise ValueError(f"Unbalanced bracket: {string}")

            c += i + 1
            s = string[i + 1 : c]
            posfix = string[c + 1] if c + 1 < length else "~"

            if posfix in "*+":
                i = c + 1
            elif not s.isalnum():
                if posfix in "?*+":
                    i = c + 1
                else:
                    i = c
            else:
                if i - j > 0:
                    prefix = {f"{p}{string[j:i]}" for p in prefix}
                if posfix == "?":
                    i = c + 1
                    prefix.update({f"{p}{c}" for p in prefix for c in s})
                else:
                    i = c
                    prefix = {f"{p}{c}" for p in prefix for c in s}
                j = i + 1

        elif string[i] == "(":
            if i - j > 0:
                prefix = {f"{p}{string[j:i]}" for p in prefix}
            substr.clear()
            p = 1
            j = i + 1
            while j < length:
                if string[j] == "(":
                    p += 1
                elif string[j] == ")":
                    p -= 1
                if p == 1 and string[j] == "|" or p == 0 and string[j] == ")":
                    substr.update(extract_regex(string[i + 1 : j]))
                    i = j
                    if p == 0:
                        if j + 1 < length and string[j + 1] == "?":
                            prefix.update({f"{p}{s}" for p in prefix for s in substr})
                            j += 1
                        else:
                            prefix = {f"{p}{s}" for p in prefix for s in substr}
                        j += 1
                        break
                j += 1
            else:
                raise ValueError(f"Unbalanced parenthesis: {string}")
            i = j

        elif string[i] == "?":
            prefix = {f"{p}{string[j:i-1]}" for p in prefix}
            prefix.update({f"{p}{string[i-1]}" for p in prefix})
            j = i + 1

        elif string[i] in "])}{":
            raise ValueError(f"{string[i]} in {string}")

        i += 1

    if i - j > 0:
        prefix = {f"{p}{string[j:]}" for p in prefix}

    return prefix


def compute_regex(source: set) -> str:
    candidate = []
    result = []

    for _ in range(3):

        words = source.copy()
        group = defaultdict(set)

        if "" in words:
            qmark = True
            words.discard("")
        else:
            qmark = False

        for word in words:
            skip = re.search(r"[\[\(].*[\[\)?*+]", word)
            if skip:
                skip = skip.span()

            for sepLength in range(0, len(word)):
                for sep in range(len(word) + 1):
                    if not (
                        skip and skip[0] - sepLength < sep < skip[1] + sepLength - 1
                    ):
                        group[f"{word[:sep]}~{word[sep+sepLength:]}"].add(word)
                        group[f"{word[:sep]}~{word[sep:]}"].add(word)

        group = {k: v for k, v in group.items() if len(v) > 1}
        result.clear()

        while group and words:
            key, val = max(
                group.items(),
                key=lambda x: (len(x[0]) - 1)
                * len(tuple(i for i in x[1] if i in words)),
            )
            del group[key]
            val.intersection_update(words)
            if not val or len(val) == 1 and "" in val:
                continue

            sep = key.index("~")
            prefix, posfix = key[:sep], key[sep + 1 :]
            prefixLength, posfixLength = sep, len(posfix)
            members = {w[prefixLength : len(w) - posfixLength] for w in val}

            if any(len(w) > 1 for w in members):
                string = compute_regex(members)
            else:
                q = True if "" in members else False
                if q and len(members) == 1:
                    continue

                string = "".join(sorted(members))
                if len(string) > 1:
                    string = f"[{string}]"
                if q:
                    string = f"{string}?"

            string = f"{prefix}{string}{posfix}"
            result.append(string)
            words.difference_update(val)

        if words:
            c = "".join(sorted(i for i in words if len(i) == 1))
            if c:
                if len(c) > 1:
                    c = f"[{c}]"
                result.append(c)
            result.extend(i for i in words if len(i) > 1)

        result.sort()
        string = "|".join(result)
        if len(result) > 1 or (
            qmark and len(string) > 1 and not re.fullmatch(r"\[[^]]+\]", string)
        ):
            string = f"({string})"

        if qmark:
            string = f"{string}?"

        candidate.append(string)

    return min(candidate, key=len)


def unit_test(extracted: set, computed: str) -> bool:
    print("Matching test:")
    regex = re.compile(computed, flags=re.IGNORECASE)
    for e in extracted:
        if not regex.fullmatch(e):
            assert "[" in e
    print("Passed.")

    for i in range(4):
        extracted2 = extract_regex(computed)
        assert extracted2 == extracted
        if i < 3:
            print(f"Computing test: {i+1}")
            computed = compute_regex(extracted)
            extracted = extracted2

    print("Passed!")
    return True


if __name__ == "__main__":
    origion = "/home/laop/git/transmission-torrent-done/component/test/av_id_prefix.txt"
    extract = "/home/laop/git/transmission-torrent-done/component/test/av_id_prefix_extract.txt"
    compute = "/home/laop/git/transmission-torrent-done/component/test/av_id_prefix_computed.txt"

    extracted = set()
    with open(origion, "r",) as f:
        for string in f.readlines():
            extracted.update(extract_regex(string.strip().lower()))
    computed = compute_regex(extracted).lower()

    unit_test(extracted, computed)

    # test = {"harg", "lean", "om", "reat"}

    # test = {
    #     "M",
    #     "MX",
    #     "MXG",
    #     "MXGS",
    #     "MXPA",
    #     "MXSPS",
    #     "MXX",
    #     "MYAB",
    #     "MYBA",
    #     "MYWIFE",
    # }

