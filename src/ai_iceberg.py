#!/usr/bin/env python3
"""
Ice-berg meme generator
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Dict
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random
import math
import os
import sys
import json


# ───────────────────────────── data model ────────────────────────────────
@dataclass
class IcebergEntry:
    level: int
    title: str
    description: str
    source: str

    @classmethod
    def from_json(cls, d: dict) -> "IcebergEntry":
        return cls(
            level=d["level"],
            title=d["title"],
            description=d.get("description", ""),
            source=d.get("source", ""),
        )


# ───────────────────────────── generator ────────────────────────────────
class IcebergMemeGenerator:
    # layout search
    start_font_size = 64
    min_font_size   = 18
    font_step       = 4

    max_padding = 60
    min_padding = 8
    pad_step    = 4

    # jitter
    jitter_px     = 30
    jitter_trials = 600

    # shadow
    shadow_blur     = 8
    shadow_passes   = 5
    shadow_offset   = 6

    def __init__(self, template_path: str, output_path: str, seed: int | None = None):
        self.template_path = template_path
        self.output_path   = output_path
        self.entries: List[IcebergEntry] = []

        if seed is not None:
            random.seed(seed)

        self.font_path = os.path.join(os.path.dirname(__file__), "anton.ttf")
        self.font      = self._load_font(self.start_font_size)

    # ───────────────────────────────── public API
    def add_entry(self, e: IcebergEntry):
        if not 0 <= e.level <= 4:
            raise ValueError("Level must be 0–4")
        self.entries.append(e)

    # ───────────────────────────────── helpers
    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(self.font_path, size)
        except OSError:
            return ImageFont.load_default()

    @staticmethod
    def _level_bounds(lvl: int, W: int, H: int) -> Tuple[int, int, int, int]:
        y = {
            0: (0,   216),
            1: (216, 635),
            2: (635, 1150),
            3: (1150, 1647),
            4: (1647, 2140),
        }[lvl]
        margin = int(W * 0.05)
        return margin, W - margin, y[0], y[1]

    @staticmethod
    def _colour_for_level(level: int) -> Tuple[int, int, int]:
        """
        White (255,255,255) → pure red (255,0,0) as level goes 0→4.
        """
        t = level / 4  # 0.0 … 1.0
        gb = int(255 * (1 - t))
        return (255, gb, gb)

    def _measure(self, title: str, pad: int) -> Tuple[int, int]:
        l, t, r, b = self.font.getbbox(title)
        return r - l + 2 * pad, b - t + 2 * pad

    # greedy shelf pack
    def _pack(
        self,
        rects: List[Tuple[int, int, IcebergEntry]],
        bounds: Tuple[int, int, int, int],
    ) -> List[Tuple[int, int, int, int, IcebergEntry]] | None:
        x0, x1, y0, y1 = bounds
        shelf_y, shelf_h, cursor_x = y0, 0, x0
        placed = []
        for w, h, e in sorted(rects, key=lambda z: -z[1]):  # tallest first
            if w > (x1 - x0):
                return None
            if cursor_x + w > x1:
                shelf_y += shelf_h
                shelf_h, cursor_x = 0, x0
            if shelf_y + h > y1:
                return None
            placed.append((cursor_x, shelf_y, w, h, e))
            cursor_x += w
            shelf_h = max(shelf_h, h)
        return placed

    # jitter pass
    @staticmethod
    def _overlap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        return not (ax2 <= bx1 or ax1 >= bx2 or ay2 <= by1 or ay1 >= by2)

    def _jitter(
        self,
        placed: List[Tuple[int, int, int, int, IcebergEntry]],
        bounds: Tuple[int, int, int, int],
    ) -> List[Tuple[int, int, int, int, IcebergEntry]]:
        x0, x1, y0, y1 = bounds
        boxes = placed[:]
        for _ in range(self.jitter_trials):
            idx = random.randrange(len(boxes))
            bx, by, w, h, e = boxes[idx]
            dx = random.randint(-self.jitter_px, self.jitter_px)
            dy = random.randint(-self.jitter_px, self.jitter_px)
            nx, ny = bx + dx, by + dy
            if nx < x0 or nx + w > x1 or ny < y0 or ny + h > y1:
                continue
            new_box = (nx, ny, nx + w, ny + h)
            if any(
                self._overlap(new_box, (ox, oy, ox + ow, oy + oh))
                for j, (ox, oy, ow, oh, _) in enumerate(boxes)
                if j != idx
            ):
                continue
            boxes[idx] = (nx, ny, w, h, e)
        return boxes

    # text with soft shadow, coloured foreground
    def _shadow_text(
        self,
        img: Image.Image,
        xy: Tuple[int, int],
        txt: str,
        colour: Tuple[int, int, int],
    ):
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        base_alpha = 60
        for i in range(self.shadow_passes):
            off = self.shadow_offset * (i + 1)
            alpha = int(base_alpha * (1 - i / self.shadow_passes * 0.5))
            for ang in range(0, 360, 20):
                rad = math.radians(ang)
                sd.text(
                    (xy[0] + off * math.cos(rad), xy[1] + off * math.sin(rad)),
                    txt,
                    font=self.font,
                    fill=(0, 0, 0, alpha),
                )
        sd.text((xy[0] + 4, xy[1] + 4), txt, font=self.font, fill=(0, 0, 0, 100))
        sh = sh.filter(ImageFilter.GaussianBlur(self.shadow_blur))
        img.alpha_composite(sh)
        ImageDraw.Draw(img).text(xy, txt, font=self.font, fill=colour)

    # ───────────────────────────────── pipeline
    def generate(self):
        img = Image.open(self.template_path).convert("RGBA")

        by_lvl: Dict[int, List[IcebergEntry]] = {i: [] for i in range(5)}
        for e in self.entries:
            by_lvl[e.level].append(e)

        for lvl in range(5):
            if not by_lvl[lvl]:
                continue
            bounds = self._level_bounds(lvl, img.width, img.height)

            fit: List[Tuple[int, int, int, int, IcebergEntry]] | None = None
            for fsz in range(self.start_font_size, self.min_font_size - 1, -self.font_step):
                self.font = self._load_font(fsz)
                for pad in range(self.max_padding, self.min_padding - 1, -self.pad_step):
                    rects = [(*self._measure(e.title, pad), e) for e in by_lvl[lvl]]
                    fit = self._pack(rects, bounds)
                    if fit:
                        break
                if fit:
                    break
            if fit is None:
                raise RuntimeError(
                    f"Level {lvl} cannot fit even at {self.min_font_size} pt /"
                    f" {self.min_padding}px pad"
                )

            fit = self._jitter(fit, bounds)
            colour = self._colour_for_level(lvl)

            for x, y, w, h, e in fit:
                tx = x + w // 2 - self.font.getlength(e.title) // 2
                ty = y + h // 2 - self.font.getbbox(e.title)[3] // 2
                self._shadow_text(img, (int(tx), int(ty)), e.title, colour)

        img.save(self.output_path, "PNG")
        print(f"✓  saved → {self.output_path}")


# ─────────────────────────────── CLI ────────────────────────────────
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(here, "entries.json")
    template_path = os.path.join(here, "..", "images", "template.png")
    output_path = os.path.join(here, "..", "images", "iceberg.png")

    for p in (json_path, template_path):
        if not os.path.exists(p):
            print(f"Error: {p} not found", file=sys.stderr)
            sys.exit(1)

    try:
        with open(json_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        entries = [IcebergEntry.from_json(d) for d in data["entries"]]
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"Error reading {json_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    gen = IcebergMemeGenerator(template_path, output_path, seed=None)
    for e in entries:
        gen.add_entry(e)
    gen.generate()


if __name__ == "__main__":
    main()
