"""
Queer's mission... is to help Transmission.

Queersmission is a custom script for the Transmission client. It manages a
dedicated seeding space, categorizes torrents, and copies completed downloads to
user-specified locations.

:copyright: (c) 2024 by David Pi.
:license: Apache 2.0, see LICENSE for more details.
:github: <https://github.com/libertypi/queersmission>
"""

import logging

logger = logging.getLogger(__name__)

PKG_NAME = __name__
