import base64
import itertools
import json
import operator
import sys

from .cat import Cat

# Config schema: key, expected type, default value
SCHEMA = (
    ("log-level", str, "INFO"),
    ("only-seed-private", bool, False),
    ("rpc-url", str, "/transmission/rpc"),
    ("rpc-port", int, 9091),
    ("rpc-username", str, ""),
    ("rpc-password", str, ""),
    ("seed-dir-purge", bool, False),
    ("seed-dir-size-limit-gb", (int, float), 0),
    ("seed-dir-space-floor-gb", (int, float), 0),
    ("seed-dir", str, ""),
    ("watch-dir", str, ""),
    ("destinations", dict, tuple((c.value, str, "") for c in Cat)),
)


def makeconfig(schema: tuple, userconf: dict = None) -> dict:
    """
    Construct a config dict from a schema and user settings, ensuring the
    correct types in each field.
    """
    conf = {}
    get = (userconf if isinstance(userconf, dict) else {}).get
    for key, _type, default in schema:
        val = get(key)
        if _type is dict:
            conf[key] = makeconfig(default, val)
        else:
            conf[key] = val if isinstance(val, _type) else default
    return conf


def json_dump(data, file: str):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def _xor(b: bytes, key: bytes = b"Claire Kuo") -> bytes:
    """Perform XOR encryption/decryption on the given bytes using a key."""
    return bytes(map(operator.xor, b, itertools.cycle(key)))


def _die(msg, code: int = 1):
    sys.stderr.write(f"Configuration error: {msg}\n")
    sys.exit(code)


def parse(file: str) -> dict:
    """Parse and validate a JSON configuration file, update the file as
    necessary."""
    try:
        with open(file, "r", encoding="utf-8") as f:
            userconf = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        json_dump(makeconfig(SCHEMA), file)
        _die(
            f'A blank configuration file has been created at "{file}". '
            "Edit the settings before running this script again."
        )
    conf = makeconfig(SCHEMA, userconf)

    # validation
    if not conf["destinations"][Cat.DEFAULT.value]:
        _die("The default destination path is not set.")

    # password
    p: str = conf["rpc-password"]
    if not p:
        pass
    elif p[0] == "{" and p[-1] == "}":
        try:
            p = _xor(base64.b64decode(p[1:-1])).decode()
        except ValueError as e:
            _die(e)
    else:
        conf["rpc-password"] = f"{{{base64.b64encode(_xor(p.encode())).decode()}}}"

    if conf != userconf:
        json_dump(conf, file)

    conf["rpc-password"] = p
    return conf
