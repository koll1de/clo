"""Locate the streamer's LIVE webcam in the source video.

CS2 gameplay has no human faces on screen, so a frontal-face detector run over a
handful of sampled frames lights up on the webcam (and, in edited VODs, on any
talking-head segments). We:

  1. detect faces across the whole VOD,
  2. density-cluster the hits and keep the DOMINANT, persistent location — so a brief
     intro talking-head or a stray detection can't drag the box off the real cam, and
     so it works for ANY streamer's layout (not just a hard-coded Renyan top-left),
  3. verify that location is a LIVE camera (its pixels change over time) — a static
     photo / avatar covering the radar is rejected, since that isn't a real cam feed.

Returns the cam box as fractions of the frame (survives any source resolution), or
None when there's no live webcam (the pipeline then uses a no-cam gameplay layout).
"""
from __future__ import annotations

import numpy as np


def _region_is_live(cap, f0: int, f1: int, box_px: tuple[int, int, int, int],
                    *, n: int = 14, min_std: float = 3.5) -> bool:
    """Sample the candidate cam box across [f0,f1): a live webcam varies frame-to-frame
    (the person moves, lighting shifts), a static photo barely changes. Returns the mean
    per-pixel temporal std of the (downscaled, grayscale) region."""
    import cv2
    x0, y0, x1, y1 = box_px
    crops = []
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f0 + (f1 - f0) * (k + 0.5) / n))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0:
            continue
        g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        crops.append(cv2.resize(g, (32, 32)).astype(np.float32))
    if len(crops) < 4:
        return True   # can't tell — don't reject a maybe-real cam
    temporal_std = float(np.stack(crops, 0).std(axis=0).mean())
    return temporal_std >= min_std


def detect_facecam(vod_path: str, *, start_s: float | None = None, end_s: float | None = None,
                   samples: int = 36, min_hits: int = 8) -> dict | None:
    """Find the live webcam, sampling the WHOLE VOD by default or just [start_s,end_s) when
    given. Per-clip windows handle VODs whose layout changes between segments (compilations,
    multi-POV edits) — the cam can sit in a different place from one clip to the next."""
    try:
        import cv2
    except ImportError:
        return None

    cap = cv2.VideoCapture(vod_path)
    if not cap.isOpened():
        return None
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if total <= 0 or W == 0 or H == 0:
        cap.release()
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    f0 = max(0, int(start_s * fps)) if start_s is not None else 0
    f1 = min(total, int(end_s * fps)) if end_s is not None else total
    if f1 - f0 < 2:
        f0, f1 = 0, total

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    hits: list[tuple[float, float, float, float, float, float]] = []  # cx,cy,x,y,w,h
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f0 + (f1 - f0) * (k + 0.5) / samples))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                         minSize=(int(H * 0.05), int(H * 0.05)))
        for (x, y, w, h) in faces:
            hits.append((x + w / 2, y + h / 2, x, y, w, h))

    if len(hits) < min_hits:
        cap.release()
        return None

    # Density cluster: the seed is the hit with the most neighbours within a radius; the
    # cluster is everyone near it. This locks onto the PERSISTENT face (the webcam, present
    # for most of the VOD) and discards outliers (a short intro shot, a stray false hit).
    arr = np.array(hits, dtype=float)
    centers = arr[:, :2]
    r = 0.12 * float(np.hypot(W, H))
    dist = np.sqrt(((centers[:, None, :] - centers[None, :, :]) ** 2).sum(-1))
    neighbours = (dist < r).sum(1)
    seed = int(np.argmax(neighbours))
    cluster = arr[dist[seed] < r]
    if cluster.shape[0] < min_hits:
        cap.release()
        return None

    # robust face box via medians of the cluster
    mx, my, mw, mh = np.median(cluster[:, 2:6], axis=0)
    fcx, fcy = mx + mw / 2, my + mh / 2
    left = fcx < W / 2
    top = fcy < H / 2
    # Build the cam box AROUND the face (a webcam frames head+shoulders with the face upper-
    # centre), tightly — NOT stretched to the frame corner. This generalises to any layout
    # instead of assuming the cam fills a corner to the edge (the Renyan-specific assumption).
    cam_w = min(float(W), mw * 1.8)
    cam_h = min(float(H), mh * 2.2)
    x0 = max(0.0, min(W - cam_w, fcx - cam_w / 2))
    y0 = max(0.0, min(H - cam_h, fcy - cam_h * 0.40))   # face ~40% down from the cam's top
    x1, y1 = x0 + cam_w, y0 + cam_h

    box_px = (int(x0), int(y0), int(x1), int(y1))
    live = _region_is_live(cap, f0, f1, box_px)
    cap.release()
    if not live:
        print("[facecam] dominant face region is static (a photo/avatar, not a live cam) -> no cam")
        return None

    return {
        "present": True,
        "x": round(x0 / W, 4),
        "y": round(y0 / H, 4),
        "w": round((x1 - x0) / W, 4),
        "h": round((y1 - y0) / H, 4),
        "corner": ("top" if top else "bottom") + "-" + ("left" if left else "right"),
        "hits": int(cluster.shape[0]),
    }
