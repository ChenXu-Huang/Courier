# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-06-01

### Added

- Portable mode: create `.portable` file next to the executable to store config
  and logs in the same directory
- Thumbnail rotation animation when files are added or removed
- Delete button for removing individual files from the basket
- Thumbnails now scale to match the device pixel ratio of the display

### Changed

- `FileBasket` utility class restructured for cleaner API
- Code updated with modern Python syntax
- Release pipeline restructured to use CHANGELOG.md as release body
- macOS builds signed with self-signed certificate

### Fixed

- Caps Lock handling in global hotkey shortcut processing

## [1.1.4] - 2026-05-28

### Added

- File thumbnail preview in the basket window
- Icon embedding for compiled artifacts

### Changed

- Platform compatibility code consolidated into a single `src/gui/platform.py`
  module
- Packaging logic extracted into `src/utils/` module
- Thumbnail acquisition logic restructured into standalone module

### Fixed

- Mypy type-checking errors in GUI code

## [1.1.3] - 2026-05-21

### Added

- Dark/light mode with unified theme palette
- Basket window now visible across all desktops and apps on macOS

### Changed

- Runtime OS detection centralized in `_meta.py`
- Config `get()` method falls back to `_DEFAULT_CONFIG` when key is missing

### Fixed

- Native DWM corners display on Windows 11 basket window
- Caps Lock switching behavior when used as a hotkey
- Build action output format

## [1.1.2] - 2026-05-18

### Fixed

- macOS Nuitka compilation parameters

## [1.1.1] - 2026-05-18

### Fixed

- Silent crash on macOS when saving configuration
- macOS system locale detection failure

### Changed

- Locale resolution and string loading logic restructured

## [1.1.0] - 2026-05-17

### Added

- Multi-language support (i18n) with hot-switchable translations
- ZIP compression support on basket drag-out

### Fixed

- macOS keyboard input not working
- `Qt.Tool` windows not overlaying other apps on macOS

### Changed

- CI test runner platform changed to `windows-latest`

## [1.0.1] - 2026-05-15

### Fixed

- Path resolution error during macOS packaging process

## [1.0.0] - 2026-05-15

### Added

- Core file staging functionality: drag files in, drag files out
- Floating square frameless always-on-top basket window
- System tray integration with context menu
- Global hotkey support (configurable)
- Configurable window size, opacity, and corner radius
- File transfer mode (copy/move) with Shift key toggling
- `after_drop_action` setting (close, clear, keep)
- Cross-platform support (Windows, macOS, Linux)
- Nuitka-based packaging workflow via GitHub Actions
- GPL-3.0 license

[Unreleased]: https://github.com/ChenXu-Huang/Courier/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/ChenXu-Huang/Courier/compare/v1.1.4...v1.2.0
[1.1.4]: https://github.com/ChenXu-Huang/Courier/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/ChenXu-Huang/Courier/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/ChenXu-Huang/Courier/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/ChenXu-Huang/Courier/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/ChenXu-Huang/Courier/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/ChenXu-Huang/Courier/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/ChenXu-Huang/Courier/releases/tag/v1.0.0
