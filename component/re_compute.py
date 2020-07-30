#!/usr/bin/env python3

try:
    import regex as re
except:
    import re
from collections import defaultdict


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
                            i = j
                        else:
                            prefix = {f"{p}{s}" for p in prefix for s in substr}
                        j += 1
                        break
                j += 1
            else:
                raise ValueError(f"Unbalanced parenthesis: {string}")

        elif string[i] == "?":
            prefix = {f"{p}{string[j:i-1]}" for p in prefix}
            prefix.update({f"{p}{string[i-1]}" for p in prefix})
            j = i + 1

        elif string[i] in "])}{":
            raise ValueError(f"{i} of {string[i]} in {string}")

        i += 1

    if i - j > 0:
        prefix = {f"{p}{string[j:]}" for p in prefix}

    return prefix


def compute_regex(words) -> str:

    words = set(words)

    if "" in words:
        qmark = True
        words.remove("")
    else:
        qmark = False

    if not words:
        return ""

    elif any(len(w) > 1 for w in words):
        if len(words) == 1:
            return f"({str(*words)})?" if qmark else str(*words)

        result = []
        group = defaultdict(set)
        prefixs = defaultdict(set)
        posfixs = defaultdict(set)
        connections = {}

        for word in words:
            skip = re.search(r"[\[\(].*[\[\)?*+]", word)
            if skip:
                skip = skip.span()
            length = len(word)
            for sep in range(0, length):
                if not (skip and sep > skip[0]):
                    group[f"~{word[sep:]}"].add(word)
                if not (skip and length - sep < skip[1]):
                    group[f"{word[:sep+1]}~"].add(word)

        while True:
            group = {k: v for k, v in group.items() if len(v) > 1}
            if not group:
                break

            for key, val in group.items():
                if key.startswith("~"):
                    target = prefixs
                    v = key[1:]
                    l = -len(v)
                    k = (w[:l] for w in val)
                else:
                    target = posfixs
                    v = key[:-1]
                    l = len(v)
                    k = (w[l:] for w in val)
                target[tuple(sorted(k))].add(v)

            for source in prefixs, posfixs:
                for key, val in source.items():
                    fullwords = tuple(
                        sorted(
                            f"{k}{v}" if source is prefixs else f"{v}{k}"
                            for k in key
                            for v in val
                        )
                    )
                    if fullwords not in connections:
                        OrgLength = len("".join(fullwords))
                        preLength = None
                    else:
                        OrgLength = connections[fullwords][2]
                        preLength = connections[fullwords][3]
                    OptLength = len("".join((*key, *val)))

                    if not preLength or OptLength < preLength:
                        connections[fullwords] = (
                            (key, val, OrgLength, OptLength)
                            if source is prefixs
                            else (val, key, OrgLength, OptLength)
                        )

            for fullwords, prefix, posfix, _, _ in sorted(
                ((k, *v) for k, v in connections.items()),
                key=lambda x: (x[3] - x[4], -x[3],),
                reverse=True,
            ):
                if not words.issuperset(fullwords):
                    break
                string = f"{compute_regex(prefix)}{compute_regex(posfix)}"
                if len(string) > len("|".join(fullwords)):
                    result.extend(fullwords)
                else:
                    result.append(string)
                words.difference_update(fullwords)

            for val in group.values():
                val.intersection_update(words)

            prefixs.clear()
            posfixs.clear()
            connections.clear()

        if words:
            string = compute_regex(i for i in words if len(i) == 1)
            if string:
                result.append(string)
            result.extend(i for i in words if len(i) > 1)

        result.sort()
        string = "|".join(result)

        if len(result) > 1 or (qmark and not re.fullmatch(r"\[[^]]+\]|.", string)):
            string = f"({string})"

        if qmark:
            string = f"{string}?"

        return string

    else:
        if len(words) > 1:
            return f'[{"".join(sorted(words))}]{"?" if qmark else ""}'
        else:
            return f'{str(*words)}{"?" if qmark else ""}'


def unit_test(extracted: set, computed: str) -> bool:
    print("Matching test begin...")
    regex = re.compile(computed, flags=re.IGNORECASE)
    for e in extracted:
        if not regex.fullmatch(e):
            assert "[" in e, e
    print("Passed.")

    for i in range(4):
        extracted2 = extract_regex(computed)
        assert extracted2 == extracted
        if i < 3:
            print(f"Computing test: {i+1}")
            computed = compute_regex(extracted)
            extracted = extracted2

    print("All passed!")
    return True


if __name__ == "__main__":

    import os.path

    # file = os.path.join(os.path.dirname(__file__), "test.txt")
    file = os.path.join(os.path.dirname(__file__), "av_id_prefix.txt")
    extracted = set()
    with open(file, "r",) as f:
        for string in f.readlines():
            extracted.update(extract_regex(string.strip().lower()))

    # extracted = {
    #     "xart",
    #     "x-art",
    #     "sexart",
    #     "atkgirlfriends",
    #     "tonightsgirlfriends",
    #     "cruelgirlfriends",
    #     "testgirlfriend",
    #     "test2girlfriend",
    # }

    # computed = "(avi|iso|m(4p|[24kop]v|p([24]|e?g))|rm(vb)?|wmv)"
    # computed = "(avi|iso|m4p|m[24ko]v|mp([24v]|e?g)|rm(vb)?|wmv)"
    # extracted = extract_regex(computed)
    # print(extracted)

    computed = compute_regex(extracted)
    print(computed)
    print(len(computed))
    unit_test(extracted, computed)

