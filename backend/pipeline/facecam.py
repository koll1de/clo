"""Locate the streamer's webcam in the source video.

CS2 gameplay has no human faces on screen, so a frontal-face detector run over a
handful of sampled frames lights up only on the webcam. We cluster those hits into
one box and pad it a little (to include hair/headphones), returned as fractions of
the frame so it survives any source resolution. Falls back to the config rect when
detection is unreliable (e.g. he wears glasses / looks away a lot).
"""
from __future__ import annotations

import numpy as np


def detect_facecam(vod_path: str, *, samples: int = 24, min_hits: int = 4) -> dict | None:
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

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    boxes: list[tuple[int, int, int, int]] = []
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / samples))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # webcam faces are sizeable; ignore tiny false hits
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                         minSize=(int(H * 0.05), int(H * 0.05)))
        for (x, y, w, h) in faces:
            boxes.append((x, y, w, h))
    cap.release()

    if len(boxes) < min_hits:
        return None

    arr = np.array(boxes, dtype=float)
    # robust face box via medians (drops the odd stray detection)
    mx, my, mw, mh = np.median(arr, axis=0)
    fcx, fcy = mx + mw / 2, my + mh / 2          # face centre
    left = fcx < W / 2
    top = fcy < H / 2
    # The webcam is corner-anchored; the detected box is just the face inside it.
    # Anchor the cam box to the nearest corner and extend past the face with margin
    # (sideways toward the centre, plus headroom above and shoulders below).
    side = mw * 0.6      # horizontal margin toward frame centre
    head = mh * 0.7      # above the face (hair/headphones)
    chin = mh * 0.4      # below the face (shoulders)
    if left:
        x0, x1 = 0.0, min(W, mx + mw + side)
    else:
        x0, x1 = max(0.0, mx - side), float(W)
    if top:
        y0, y1 = 0.0, min(H, my + mh + chin)
    else:
        y0, y1 = max(0.0, my - head), float(H)
    return {
        "present": True,
        "x": round(x0 / W, 4),
        "y": round(y0 / H, 4),
        "w": round((x1 - x0) / W, 4),
        "h": round((y1 - y0) / H, 4),
        "corner": ("top" if top else "bottom") + "-" + ("left" if left else "right"),
        "hits": len(boxes),
    }
