import base64
import json
import sys

from .cat import Cat

# Config fields with keys, expected types, and default values
FIELDS = (
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


def makeconfig(fields: tuple, userconf: dict = None) -> dict:
    """
    Construct a config dict from a template and user settings, ensuring the
    correct types in each field.
    """
    conf = {}
    get = (userconf if isinstance(userconf, dict) else {}).get
    for key, _type, default in fields:
        val = get(key)
        if _type is dict:
            conf[key] = makeconfig(default, val)
        else:
            conf[key] = val if isinstance(val, _type) else default
    return conf


def parse(file: str) -> dict:
    """Parse and validate the configuration file, update the file if
    necessary."""
    try:
        with open(file, "r", encoding="utf-8") as f:
            userconf = json.load(f)
        if not userconf or not isinstance(userconf, dict):
            raise ValueError("Corrupted config file.")
    except (FileNotFoundError, ValueError):  # including JSONDecodeError
        json_dump(makeconfig(FIELDS), file)
        sys.stderr.write(
            f'A blank configuration file has been created at "{file}". '
            "Edit the settings before running this script again.\n"
        )
        sys.exit(1)

    conf = makeconfig(FIELDS, userconf)
    try:
        # validation
        if not conf["destinations"][Cat.DEFAULT.value]:
            raise ValueError("The default destination path is not set.")
        # password
        p = conf["rpc-password"]
        if not p:
            pass
        elif p[0] == "{" and p[-1] == "}":
            p = base64.b64decode(p[-2:0:-1]).decode()
        else:
            conf["rpc-password"] = f"{{{base64.b64encode(p.encode()).decode()[::-1]}}}"
    except Exception as e:
        sys.stderr.write(f"Configuration error: {e}\n")
        sys.exit(1)

    if conf != userconf:
        json_dump(conf, file)

    conf["rpc-password"] = p
    return conf


def json_dump(data, file: str):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
