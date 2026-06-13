"""Chat signal — Twitch chat message-velocity + emote bursts.

When chat suddenly floods (spam of laughter emotes, hype, copypasta) it marks a
moment the room reacted to. Parallels the audio signal: bursts above the chat's
own baseline corroborate transcript clips and can surface clips on their own.

Chat is downloaded during ingest (see ingest.download_chat) into
data/work/<job>.chat.json as a list of {"t": seconds, "text": str}. This module
only reads that file, so it works regardless of how chat was obtained.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Emotes/words that signal funny vs. hype, so a burst can be typed.
_LAUGH = {"lul", "lmao", "kekw", "omegalul", "kek", "ахаха", "ахах", "лол", "ору", "ржу", "хаха"}
_HYPE = {"pog", "pogchamp", "poggers", "ezz", "ez", "clap", "gg", "вау", "имба", "топ"}


@dataclass
class Burst:
    start: float
    end: float
    peak: float        # seconds of peak message rate
    level: float       # peak rate / baseline rate
    funny: bool = False  # laughter emotes dominated the burst


def load_chat(path: str) -> list[tuple[float, str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: list[tuple[float, str]] = []
    for m in data:
        t = m.get("t", m.get("time_in_seconds"))
        if t is None:
            continue
        out.append((float(t), (m.get("text") or m.get("message") or "")))
    out.sort(key=lambda x: x[0])
    return out


def _classify(texts: list[str]) -> bool:
    laugh = hype = 0
    for t in texts:
        low = t.lower()
        words = set(low.replace("!", " ").replace(",", " ").split())
        if words & _LAUGH:
            laugh += 1
        if words & _HYPE:
            hype += 1
    return laugh >= hype and laugh > 0


def find_bursts(
    messages: list[tuple[float, str]],
    *,
    win_s: float = 2.0,
    factor: float = 3.0,      # rate this many× the baseline counts as a burst
    min_gap_s: float = 4.0,   # merge bursts closer than this
    min_msgs: int = 4,        # ignore tiny bursts in low-traffic chats
) -> list[Burst]:
    if not messages:
        return []
    total = messages[-1][0]
    n_win = int(total / win_s) + 1
    if n_win < 4:
        return []
    counts = [0] * n_win
    bucket_texts: list[list[str]] = [[] for _ in range(n_win)]
    for t, text in messages:
        i = min(n_win - 1, int(t / win_s))
        counts[i] += 1
        bucket_texts[i].append(text)

    nonzero = [c for c in counts if c > 0]
    baseline = sorted(nonzero)[len(nonzero) // 2] if nonzero else 0
    baseline = max(baseline, 1)
    thresh = max(baseline * factor, min_msgs)

    bursts: list[Burst] = []
    gap_wins = int(min_gap_s / win_s)
    i = 0
    while i < n_win:
        if counts[i] < thresh:
            i += 1
            continue
        j = i
        last_hot = i
        while j < n_win and (counts[j] >= thresh or (j - last_hot) <= gap_wins):
            if counts[j] >= thresh:
                last_hot = j
            j += 1
        seg = counts[i : last_hot + 1]
        peak_idx = i + seg.index(max(seg))
        texts: list[str] = []
        for k in range(i, last_hot + 1):
            texts += bucket_texts[k]
        bursts.append(Burst(
            start=round(i * win_s, 2),
            end=round((last_hot + 1) * win_s, 2),
            peak=round(peak_idx * win_s, 2),
            level=round(max(seg) / baseline, 2),
            funny=_classify(texts),
        ))
        i = j
    bursts.sort(key=lambda b: b.level, reverse=True)
    return bursts
