#!/usr/bin/env python3

# nuitka-project-if: {OS} == "Darwin":
#    nuitka-project: --mode=app
#    nuitka-project: --macos-signed-app-name=com.chenxu-huang.courier
#    nuitka-project: --macos-sign-identity=ad-hoc
#    nuitka-project: --macos-app-mode=ui-element
#    nuitka-project: --macos-app-name=Courier
#    nuitka-project: --macos-app-icon=dist/icon/icon.icns

# nuitka-project-if: {OS} == "Windows":
#    nuitka-project: --mode=standalone
#    nuitka-project: --windows-console-mode=disable
#    nuitka-project: --windows-icon-from-ico=dist/icon/icon.ico

# nuitka-project-if: {OS} in ("Linux", "FreeBSD"):
#    nuitka-project: --mode=standalone
#    nuitka-project: --linux-icon=dist/icon/icon-256.png

# nuitka-project: --deployment
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --enable-plugin=pyside6
# nuitka-project: --output-dir=dist
# nuitka-project: --output-filename=Courier
# nuitka-project: --product-name=Courier
# nuitka-project: --include-distribution-metadata=courier
# nuitka-project: --noinclude-unittest-mode=error
# nuitka-project: --noinclude-pytest-mode=error

import sys

from src import launch_gui


if __name__ == "__main__":
    sys.exit(launch_gui())
