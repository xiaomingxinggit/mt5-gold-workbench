"""Export the committed dragon SVGs as PNGs and a multi-resolution Windows ICO."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "src/mt5_workbench/ui/resources/branding"
PNG_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 192, 256, 512, 1024)
ICO_SIZES = tuple(size for size in PNG_SIZES if size <= 256)


def render(source: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG: {source}")
    scale = 4 if size <= 256 else 1
    image = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Could not encode icon PNG")
    return bytes(data)


def export(destination: Path, *, install_resources: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("dragon-gold", "dragon-ink", "dragon-white", "app-icon"):
        source = BRANDING / f"{name}.svg"
        shutil.copy2(source, destination / source.name)
        for size in PNG_SIZES:
            (destination / f"{name}-{size}.png").write_bytes(png_bytes(render(source, size)))
    images = [(size, (destination / f"app-icon-{size}.png").read_bytes())
              for size in ICO_SIZES]
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        dimension = 0 if size == 256 else size
        entries.append(struct.pack("<BBBBHHII", dimension, dimension, 0, 0,
                                   1, 32, len(data), offset))
        offset += len(data)
    icon = struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries)
    icon += b"".join(data for _, data in images)
    (destination / "app-icon.ico").write_bytes(icon)
    shutil.copy2(BRANDING / "README.md", destination / "README.md")
    if install_resources:
        shutil.copy2(destination / "app-icon.ico", BRANDING / "app-icon.ico")
        shutil.copy2(destination / "app-icon-256.png", BRANDING / "app-icon.png")
    print(f"Branding assets ready: {destination.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/branding")
    parser.add_argument("--install-resources", action="store_true",
                        help="Update runtime ICO/PNG after editing the SVGs on dev")
    args = parser.parse_args()
    export(args.output, install_resources=args.install_resources)
