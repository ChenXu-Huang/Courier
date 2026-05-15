#!/usr/bin/env python3

# nuitka-project-if: {OS} == "Darwin":
#    nuitka-project: --mode=app
# nuitka-project-else:
#    nuitka-project: --mode=standalone

# nuitka-project: --disable-console
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --enable-plugin=pyside6
# nuitka-project: --output-dir=dist
# nuitka-project: --output-filename=Courier
# nuitka-project: --product-name=Courier
# nuitka-project: --include-distribution-metadata=courier

import sys

from src import launch_gui


if __name__ == "__main__":
    sys.exit(launch_gui())
