#!/usr/bin/env -S uv run --script --no-project
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "cairosvg>=2.7.0",
#   "pillow>=10.0.0",
# ]
# ///

"""Convert svg to platform-specific icon formats."""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import cairosvg
from PIL import Image


def _render_svg(svg_path: Path, size: int) -> Image.Image:
    """Rasterize SVG to Pillow Image Object of Specified Size"""
    render_size = max(512, size)
    png_data = cairosvg.svg2png(url=str(svg_path), output_width=render_size, output_height=render_size)
    img = Image.open(io.BytesIO(png_data))

    if render_size != size:
        img = img.resize((size, size), resample=Image.Resampling.LANCZOS)

    if img.mode == "RGBA":
        r, g, b, a = img.split()
        a = a.point(lambda p: min(255, max(0, int((p - 128) * 3.0 + 128))))
        # or directly binarize the Alpha channel
        # a = a.point(lambda p: 255 if p >= 128 else 0)
        img = Image.merge("RGBA", (r, g, b, a))

    return img


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate platform icons from an SVG source file.")
    parser.add_argument("--svg", required=True, type=Path, help="Path to the source SVG file")
    parser.add_argument("--output", default=Path("dist/icon"), type=Path, help="Output directory (default: dist/icon/)")
    parser.add_argument("--ico", action="store_true", help="Generate Windows .ico")
    parser.add_argument("--icns", action="store_true", help="Generate macOS .icns")
    parser.add_argument("--png", action="store_true", help="Generate Linux PNGs")
    parser.add_argument("--png-sizes", type=int, nargs="*", default=[256], help="PNG sizes in pixels (default: 256)")
    parser.add_argument("--all", action="store_true", help="Shortcut for --ico --icns --png")
    args = parser.parse_args()

    if not args.svg.is_file():
        print(f"Error: SVG file not found: {args.svg}", file=sys.stderr)
        sys.exit(1)

    args.output.mkdir(parents=True, exist_ok=True)
    do_all = args.all or not (args.ico or args.icns or args.png)

    print(f"Generating icons from {args.svg} to {args.output}/")

    if do_all or args.ico:
        ico_sizes = [16, 32, 48, 256]
        ico_imgs = [_render_svg(args.svg, s) for s in ico_sizes]
        ico_path = args.output / "icon.ico"
        ico_imgs[0].save(ico_path, format="ICO", sizes=[(s, s) for s in ico_sizes], append_images=ico_imgs[1:])
        print(f"  {ico_path} ({'x'.join(map(str, ico_sizes))})")

    if do_all or args.icns:
        icns_sizes = [16, 32, 64, 128, 256, 512]
        icns_imgs = [_render_svg(args.svg, s) for s in icns_sizes]
        icns_path = args.output / "icon.icns"
        icns_imgs[0].save(icns_path, format="ICNS", append_images=icns_imgs[1:])
        print(f"  {icns_path} ({'x'.join(map(str, icns_sizes))})")

    if do_all or args.png:
        for size in args.png_sizes:
            png_path = args.output / f"icon-{size}.png"
            _render_svg(args.svg, size).save(png_path, format="PNG")
            print(f"  {png_path}")

    print("Done.")


if __name__ == "__main__":
    main()
