"""Isolated subprocess worker for OpenCV image stitching.

Run as:  python stitch_worker.py <in1> <in2> ... -- <out>
Exits 0 and writes the mosaic to <out> on success; non-zero otherwise.
Runs in its own process so a native crash/hang can't affect the API server.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2  # noqa: E402

import photogram  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if "--" not in args:
        return 3
    sep = args.index("--")
    ins, rest = args[:sep], args[sep + 1:]
    if not rest:
        return 3
    out = rest[0]
    imgs = [cv2.imread(p) for p in ins]
    imgs = [im for im in imgs if im is not None]
    if len(imgs) < 2:
        return 4
    mosaic = photogram._try_stitch(imgs)
    if mosaic is None or not mosaic.size:
        return 2
    cv2.imwrite(out, mosaic)
    return 0


if __name__ == "__main__":
    sys.exit(main())
