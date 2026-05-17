# Courier

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/ChenXu-Huang/Courier?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/github/v/release/ChenXu-Huang/Courier?style=flat-square" alt="Release">
  <img src="https://img.shields.io/badge/python-3.13+-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/built%20with-Nuitka-purple?style=flat-square" alt="Nuitka">
</p>

Make drag-and-drop easier using Courier!

Courier provides a floating square window (the "basket") where you drag-and-drop files to stage them, then drag them out to a target destination. No more opening side-by-side windows or switching between multiple file manager tabs.

Works on **Windows**, **Linux** and **macOS**. (Linux support is provided but not verified.)

## Features

- **Floating always-on-top window** — frameless, translucent, stays above other windows
- **Drag-in to stage** — drop files into the basket to accumulate them
- **Drag-out to transfer** — drag files out to any destination (copy or move)
- **Shift to toggle mode** — hold Shift during drag-out to invert the configured transfer mode
- **Compress on drag** — optionally bundle all staged files into a single zip on drag-out
- **Multiple windows** — create as many independent baskets as you need
- **Global hotkey** — summon a new basket window at cursor position
- **System tray** — runs in the background with tray menu (New Window, Settings, Quit)
- **Multi-language** — Chinese, English, or auto-detect from system locale
- **Customizable** — window size, opacity, corner radius, transfer mode, after-drop behavior, hotkey

## How to Install

### Pre-built executable (recommended)

Download the latest release for your platform from the [Releases page](https://github.com/ChenXu-Huang/Courier/releases).

- **Windows** — Download `Courier-<version>-win.zip`, extract, and run `Courier.exe`.
- **macOS** — Download `Courier-<version>-macos.dmg`, install, and open `Courier.app`.
- **Linux** — Download `Courier-<version>-linux.zip`, extract, and run `Courier`.

### From source

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/) package manager.

```bash
git clone https://github.com/ChenXu-Huang/Courier.git
cd Courier
uv sync --group dev
```

## Usage

Run the program:

```bash
uv run python main.py
```

A square floating window appears on your screen. Drag any files or folders into it, go to your target location, and drag them out.

- **Drag-out**: Files are copied by default; hold **Shift** to toggle to move mode.
- **Close**: Click the **X** button to close the window (files are not affected).
- **New window**: Click the tray icon, select "New Window", or press the global hotkey.
- **Global hotkey**: Press <kbd>Shift</kbd>+<kbd>Caps Lock</kbd> (Windows/Linux) or <kbd>Shift</kbd>+<kbd>Enter</kbd> (macOS) to create a new basket at your cursor position.
- **Compress**: Open the top-left menu and toggle "Compress on drag" to bundle all files into a zip.

## Configuration

Settings are available through the tray menu → **Settings**, or directly in `config/settings.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `language` | `"auto"` | Interface language: `"auto"`, `"zh_CN"`, `"en_US"` |
| `window_size` | `320` | Window width/height in pixels |
| `window_opacity` | `0.92` | Window opacity (0.1–1.0) |
| `window_radius` | `20` | Corner radius in pixels |
| `after_drop_action` | `"close"` | Action after drag-out: `close`, `clear`, or `keep` |
| `default_transfer_mode` | `"copy"` | Transfer mode: `copy` or `move` |
| `global_hotkey` | `"shift+enter"` (macOS) / `"shift+caps lock"` | Global hotkey combination |
| `show_on_startup` | `true` | Show a basket window when the app starts |
| `compress_on_drag` | `false` | Bundle files into a zip on drag-out |

## Building from source

Nuitka compilation directives are embedded in `main.py`. To build a standalone executable:

```bash
uv run nuitka main.py
```

The output will be placed in the `dist/` directory. The packaged executable is self-contained — no Python or dependencies required.

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest

# Type checking
uv run mypy src/ tests/

# Run a single test
uv run pytest tests/test_file_basket.py::TestAdd::test_add_new_files -v
```

## Related

- [DropPoint](https://github.com/GameGodS3/DropPoint) — A cross-platform drag-and-drop file staging utility built with Tauri that inspired this project.
- [Dropover](http://dropoverapp.com/) — A macOS-native file staging app that inspired the design and workflow of these tools.

## License

GPL-3.0
