#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024-2026 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: Apache-2.0

"""release-access — grant/revoke per-project read access on release buckets.

Usage:
  release_access.py bootstrap
  release_access.py grant --products <name[,name...]> --account-id <id> \
                          --role {dev,customer} --friendly-name "..."
  release_access.py revoke <project> <account-id>
  release_access.py list [<project>]

See README.md for details.
"""

from release_access.cli import main

if __name__ == "__main__":
    main()
