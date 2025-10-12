import itertools
import json
import operator
import os.path as op
import sys

from .cat import Cat

# Config schema: key, expected type, default value
_opt_str = (str, type(None))
SCHEMA = [
    ("log-level", str, "INFO"),
    ("only-seed-private", bool, False),
    ("rpc-path", str, "/transmission/rpc"),
    ("rpc-port", int, 9091),
    ("rpc-username", _opt_str, None),
    ("rpc-password", _opt_str, None),
    ("seed-dir-purge", bool, False),
    ("seed-dir-quota-gib", (int, float), 0),
    ("seed-dir-reserve-space-gib", (int, float), 0),
    ("seed-dir", _opt_str, None),
    ("watch-dir", _opt_str, None),
]
SCHEMA.extend((c.value, _opt_str, None) for c in Cat)
del _opt_str


def makeconfig(schema: list, userconf: dict = None) -> dict:
    """
    Construct a config dict from a schema and user settings, ensuring the
    correct types in each field.
    """
    conf = {}
    get = (userconf if isinstance(userconf, dict) else {}).get
    for key, _type, default in schema:
        val = get(key)
        conf[key] = val if isinstance(val, _type) else default
    return conf


def json_dump(data, file: str):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def xor_cipher(b: bytes, key: bytes = b"Claire Kuo") -> bytes:
    """Perform XOR obfuscation on the given bytes using a key."""
    return bytes(map(operator.xor, b, itertools.cycle(key)))


def normalize_path(conf: dict, k: str, not_empty: bool = False):
    """
    Validate and normalize a path, and write back to the config dict. Empty
    strings are converted to None unless not_empty is True.
    """
    path = conf[k]
    if path:
        if not op.isabs(path):
            _error(f'Path for "{k}" is not absolute: "{path}".')
        conf[k] = op.normpath(path)
    elif not_empty:
        _error(f"Path for '{k}' cannot be empty.")
    else:
        conf[k] = None


def _error(msg, code: int = 1):
    sys.stderr.write(f"Configuration error: {msg}\n")
    sys.exit(code)


def parse(file: str) -> dict:
    """
    Parse and validate a JSON configuration file, update the file as necessary.
    """
    try:
        with open(file, "r", encoding="utf-8") as f:
            userconf = json.load(f)
    except FileNotFoundError:
        json_dump(makeconfig(SCHEMA), file)
        sys.stderr.write(
            f'A blank configuration file has been created at "{file}". '
            "Edit the settings before running this script again.\n"
        )
        sys.exit(1)
    except Exception as e:
        _error(f"Cannot read the configuration file: {e}")

    conf = makeconfig(SCHEMA, userconf)

    # validate & normalize paths
    normalize_path(conf, "seed-dir")
    normalize_path(conf, "watch-dir")
    for c in Cat:
        normalize_path(conf, c.value, not_empty=(c == Cat.DEFAULT))

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
