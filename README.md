# Courier

A lightweight cross-platform file staging tool with PySide6 GUI.

Courier provides a floating square window (the "basket") where you drag-and-drop files to stage them, then drag them out to a target destination. It's designed for quick, visual file staging without opening a full file manager.

## Features

- **Floating always-on-top window** — frameless, translucent, stays above other windows
- **Drag-in to stage** — drop files into the basket to accumulate them
- **Drag-out to transfer** — drag files out to any destination (copy or move)
- **Shift to toggle mode** — hold Shift during drag-out to invert the configured transfer mode
- **Multiple windows** — create as many independent baskets as you need
- **Global hotkey** — summon a new basket window at cursor position (default: <kbd>Shift</kbd>+<kbd>Caps Lock</kbd>)
- **System tray** — background operation with tray menu (New Window, Settings, Quit)
- **Customizable** — window size, opacity, corner radius, theme color, transfer mode, after-drop behavior

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

```bash
git clone https://github.com/ChenXu-Huang/Courier.git
cd Courier
uv sync --group dev
```

## Usage

```bash
uv run python main.py
```

Drag files into the Courier window to stage them, then drag them out to a folder or application to copy/move them.

## Packaging

Nuitka compilation directives are embedded in `main.py`. To build a standalone executable:

```bash
uv run nuitka main.py
```

The output will be placed in the `dist/` directory.

## Configuration

Settings are stored in `config/settings.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `window_size` | `320` | Window width/height in pixels |
| `window_opacity` | `0.92` | Window opacity (0.1–1.0) |
| `window_radius` | `20` | Corner radius in pixels |
| `theme_color` | `#3B82F6` | Primary theme color |
| `after_drop_action` | `"close"` | Action after drag-out: `close`, `clear`, or `keep` |
| `default_transfer_mode` | `"copy"` | Transfer mode: `copy` or `move` |
| `global_hotkey` | `"shift+caps lock"` | Global hotkey combination |

## Development

```bash
# Run tests
uv run pytest

# Type checking
uv run mypy src/ tests/

# Run a single test
uv run pytest tests/test_file_basket.py::TestAdd::test_add_new_files -v
```

## Related

- [DropPoint](https://github.com/GameGodS3/DropPoint) — A cross-platform drag-and-drop file staging utility with a similar floating-window concept, built with Tauri.
- [Dropover](http://dropoverapp.com/) — A macOS-native file staging app that inspired this project's design and workflow.

## License

GPL-3.0
