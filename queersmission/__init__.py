"""
Queersmission - Smart Categorization for Transmission
=====================================================

Description:
------------
Queersmission is a custom script for the Transmission client. It manages a
dedicated seeding space and copies completed downloads to user-specified
locations.

Features:
---------
- Storage management based on quota settings.
- Copy finished downloads to user destinations.
- Smart torrent categorization.

Author:
-------
- David Pi
- GitHub: https://github.com/libertypi/queersmission
"""

import logging

logger = logging.getLogger(__name__)

PKG_NAME = __name__
