"""
Queer's mission... is to help Transmission.

Queersmission is a custom script for the Transmission client. It manages a
dedicated seeding space, categorizes torrents, and copies completed downloads to
user-specified locations.

:copyright: (c) 2025 by David Pi.
:license: Apache 2.0, see LICENSE for more details.
:github: <https://github.com/libertypi/queersmission>
"""

import logging

PKG_NAME = __name__

logger = logging.getLogger(PKG_NAME)
