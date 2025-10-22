import itertools
import json
import operator
import os
import os.path as op
import sys
from typing import Union

from .cat import Cat

# --- Normalizers & validators -------------------------------------------------


def _non_negative(val: Union[int, float]):
    return val if val >= 0 else 0


def _port(val: int):
    if 0 < val < 65536:
        return val
    raise ValueError(f"Port number out of range: {val}.")


def _abs_path(val: str):
    """Normalize and validate an absolute path. Empty string is allowed."""
    if not val:
        return val
    if not op.isabs(val):
        raise ValueError(f'Path is not absolute: "{val}".')
    return op.normpath(val)


# --- Schema ------------------------------------------------------------------

# key, type, default, normalizer

SCHEMA = [
    ("log-level", str, "INFO", None),
    ("public-upload-limited", bool, False, None),
    ("public-upload-limit-kbps", int, 50, _non_negative),
    ("remove-public-on-complete", bool, False, None),
    ("rpc-path", str, "/transmission/rpc", None),
    ("rpc-port", int, 9091, _port),
    ("rpc-username", str, "", None),
    ("rpc-password", str, "", None),
    ("seed-dir-purge", bool, False, None),
    ("seed-dir-quota-gib", (int, float), 0, _non_negative),
    ("seed-dir-reserve-space-gib", (int, float), 0, _non_negative),
    ("seed-dir", str, "", _abs_path),
    ("watch-dir", str, "", _abs_path),
]
SCHEMA.extend((c.value, str, "", _abs_path) for c in Cat)

# --- Core --------------------------------------------------------------------


def makeconfig(userconf: dict = None) -> dict:
    """
    Build a config dict from schema and user settings; apply normalizers.
    Missing/wrong-typed values fall back to defaults.
    """
    conf = {}
    get = (userconf if isinstance(userconf, dict) else {}).get
    for key, _type, default, norm in SCHEMA:
        val = get(key)
        if isinstance(val, _type):
            conf[key] = val if norm is None else norm(val)
        else:
            conf[key] = default
    return conf


def json_dump(data, file: str):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def xor_cipher(b: bytes, key: bytes = b"Claire Kuo") -> bytes:
    """Perform XOR obfuscation on the given bytes using a key."""
    return bytes(map(operator.xor, b, itertools.cycle(key)))


def _error(msg):
    sys.stderr.write(f"Configuration error: {msg}\n")
    sys.exit(1)


def parse(file: str) -> dict:
    """
    Parse and validate a JSON configuration file, update the file as necessary.
    """
    try:
        with open(file, "r", encoding="utf-8") as f:
            userconf = json.load(f)
    except FileNotFoundError:
        os.makedirs(op.dirname(file), exist_ok=True)
        json_dump(makeconfig(), file)
        sys.stderr.write(
            f'A blank configuration file has been created at "{file}". '
            "Edit the settings before running this script again.\n"
        )
        sys.exit(1)
    except Exception as e:
        _error(e)

    try:
        conf = makeconfig(userconf)
    except ValueError as e:
        _error(e)

    # check paths
    if not conf[Cat.DEFAULT.value]:
        _error(f'"{Cat.DEFAULT.value}" must be set to a valid path.')

    # password
    p: str = conf["rpc-password"]
    if not p:
        pass
    elif p[0] == "{" and p[-1] == "}":
        try:
            p = xor_cipher(bytes.fromhex(p[1:-1])).decode()
        except (ValueError, UnicodeDecodeError):
            _error(f"Cannot decode the password.")
    else:
        conf["rpc-password"] = "{" + xor_cipher(p.encode()).hex() + "}"

    if conf != userconf:
        json_dump(conf, file)

    conf["rpc-password"] = p
    return conf
