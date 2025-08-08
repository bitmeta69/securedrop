import functools
from datetime import date

FOCAL_VERSION = "20.04"
NOBLE_VERSION = "24.04"

FOCAL_ENDOFLIFE = date(2025, 5, 31)


@functools.lru_cache
def get_os_release() -> str:
    with open("/etc/os-release") as f:
        os_release = f.readlines()
        for line in os_release:
            if line.startswith("VERSION_ID="):
                version_id = line.split("=")[1].strip().strip('"')
                break
    return version_id


def is_os_past_eol() -> bool:
    """
    Check if it's focal and if today is past the official EOL date
    """
    return get_os_release() == FOCAL_VERSION and date.today() >= FOCAL_ENDOFLIFE
