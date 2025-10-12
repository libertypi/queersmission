import itertools
import json
import operator
import os.path as op
import sys

from .cat import Cat

# --- Normalizers & validators -------------------------------------------------


def _port(val):
    if 0 < val < 65536:
        return val
    raise ValueError(f"Port number out of range: {val}.")


def _non_negative(val):
    return val if val > 0 else 0


def _abs_path(val):
    """Normalize and validate an absolute path. Return None if val is empty."""
    if not val:
        return None
    if not op.isabs(val):
        raise ValueError(f'Path is not absolute: "{val}".')
    return op.normpath(val)


# --- Schema ------------------------------------------------------------------

_opt_str = (str, type(None))

# key, type, default, normalization function

SCHEMA = [
    ("log-level", str, "INFO", None),
    ("only-seed-private", bool, False, None),
    ("rpc-path", str, "/transmission/rpc", None),
    ("rpc-port", int, 9091, _port),
    ("rpc-username", _opt_str, None, None),
    ("rpc-password", _opt_str, None, None),
    ("seed-dir-purge", bool, False, None),
    ("seed-dir-quota-gib", (int, float), 0, _non_negative),
    ("seed-dir-reserve-space-gib", (int, float), 0, _non_negative),
    ("seed-dir", _opt_str, None, _abs_path),
    ("watch-dir", _opt_str, None, _abs_path),
]
SCHEMA.extend((c.value, _opt_str, None, _abs_path) for c in Cat)

del _opt_str

# --- Core --------------------------------------------------------------------


def makeconfig(userconf: dict = None) -> dict:
    """
    Build a config dict from schema and user settings; apply normalizers.
    Missing/wrong-typed values fall back to defaults.
    """
    conf = {}
    get = (userconf if isinstance(userconf, dict) else {}).get
    for key, _type, default, func in SCHEMA:
        val = get(key)
        if isinstance(val, _type):
            conf[key] = val if func is None else func(val)
        else:
            conf[key] = default
    return conf


def json_dump(data, file: str):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def xor_cipher(b: bytes, key: bytes = b"Claire Kuo") -> bytes:
    """Perform XOR obfuscation on the given bytes using a key."""
    return bytes(map(operator.xor, b, itertools.cycle(key)))


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
