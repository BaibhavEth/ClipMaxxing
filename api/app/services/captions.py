"""Word-synchronized ASS captions with animated presets."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.models import CaptionStyle, TranscriptWord

FONTS_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"


@dataclass(frozen=True)
class CaptionCue:
    start: float
    end: float
    text: str
    words: tuple[TranscriptWord, ...]


@dataclass(frozen=True)
class CaptionPreset:
    font: str
    size: int
    # For karaoke presets, primary is the unspoken color and highlight the spoken fill.
    primary: str = "#FFFFFF"
    highlight: str = "#FFFFFF"
    outline: str = "#000000"
    outline_width: float = 4
    shadow: float = 2
    shadow_alpha: int = 0x60
    bold: bool = True
    uppercase: bool = True
    max_words: int = 3
    max_chars: int = 24
    # karaoke: one event per cue with \kf fills; highlight: one event per word
    mode: str = "highlight"
    pop: bool = False
    # Active word drawn on a colored pill (spotlight) or a soft glow (glow).
    pill: str | None = None
    glow: str | None = None
    # Whole line on a translucent plate.
    plate: str | None = None
    plate_alpha: int = 0x60


PRESETS: dict[CaptionStyle, CaptionPreset] = {
    CaptionStyle.CLEAN: CaptionPreset(
        font="Arial", size=52, primary="#D8D8D8", highlight="#FFFFFF", outline_width=2,
        shadow=1, shadow_alpha=0x80, bold=False, uppercase=False, max_words=7, max_chars=40,
        mode="karaoke",
    ),
    CaptionStyle.BOLD: CaptionPreset(
        font="Arial", size=64, primary="#D8D8D8", highlight="#FFFFFF", outline_width=3,
        shadow=1, shadow_alpha=0x80, max_words=7, max_chars=40, mode="karaoke",
    ),
    CaptionStyle.MINIMAL: CaptionPreset(
        font="Arial", size=42, primary="#D8D8D8", highlight="#FFFFFF", outline_width=1,
        shadow=0, bold=False, uppercase=False, max_words=7, max_chars=40, mode="karaoke",
    ),
    CaptionStyle.POP: CaptionPreset(
        font="Montserrat Black", size=96, highlight="#FFE234", outline_width=6, shadow=3,
        pop=True,
    ),
    CaptionStyle.SPOTLIGHT: CaptionPreset(
        font="Poppins Black", size=92, highlight="#FFFFFF", outline_width=5, shadow=0,
        pill="#7C5CFF",
    ),
    CaptionStyle.IMPACT: CaptionPreset(
        font="Anton", size=140, highlight="#FFD60A", outline_width=7, shadow=9,
        shadow_alpha=0x18, bold=False, max_words=2, max_chars=16, pop=True,
    ),
    CaptionStyle.BOXED: CaptionPreset(
        font="Archivo Black", size=76, highlight="#FFD23F", outline_width=0, shadow=0,
        bold=False, plate="#000000", plate_alpha=0x60, max_words=4, max_chars=26,
    ),
    CaptionStyle.SWEEP: CaptionPreset(
        font="Poppins ExtraBold", size=88, primary="#FFFFFF", highlight="#FF5FA2",
        outline_width=5, shadow=2, max_words=4, max_chars=26, mode="karaoke",
    ),
    CaptionStyle.PUNCH: CaptionPreset(
        font="Anton", size=170, outline_width=8, shadow=11, shadow_alpha=0x18, bold=False,
        max_words=1, max_chars=14, pop=True,
    ),
    CaptionStyle.GLOW: CaptionPreset(
        font="Montserrat ExtraBold", size=92, highlight="#7DF9FF", outline_width=0,
        shadow=4, shadow_alpha=0x50, glow="#00C8FF",
    ),
}


def preset_for(style: CaptionStyle) -> CaptionPreset:
    return PRESETS[style]


def build_caption_cues(
    words: list[TranscriptWord],
    clip_start: float,
    clip_end: float,
    words_per_cue: int = 7,
    max_chars: int = 40,
) -> list[CaptionCue]:
    duration = clip_end - clip_start
    local_words = [
        TranscriptWord(
            start=max(0.0, word.start - clip_start),
            end=min(duration, word.end - clip_start),
            word=word.word.strip(),
        )
        for word in words
        if word.end > clip_start and word.start < clip_end and word.word.strip()
    ]
    if not local_words:
        return []

    cues: list[CaptionCue] = []
    group: list[TranscriptWord] = []

    def flush() -> None:
        if not group:
            return
        cues.append(
            CaptionCue(
                start=round(group[0].start, 3),
                end=round(min(duration, group[-1].end + 0.08), 3),
                text=" ".join(word.word for word in group),
                words=tuple(group),
            )
        )
        group.clear()

    for word in local_words:
        next_text = " ".join([*(item.word for item in group), word.word])
        has_pause = bool(group and word.start - group[-1].end >= 0.55)
        too_long = bool(group and word.end - group[0].start > 3.2)
        too_wide = bool(group) and len(next_text) > max_chars
        if group and (len(group) >= words_per_cue or has_pause or too_long or too_wide):
            flush()
        group.append(word)
        ends_sentence = bool(re.search(r"""[.!?…]["'’”)]*$""", word.word))
        if ends_sentence and len(group) >= 2:
            flush()
    flush()

    # Hold each cue until the next one starts when the gap is short, so lines
    # don't flicker off between words, and never let two cues overlap.
    held: list[CaptionCue] = []
    for index, cue in enumerate(cues):
        following = cues[index + 1] if index + 1 < len(cues) else None
        end = cue.end
        if following and following.start - cue.end < 0.35:
            end = following.start
        held.append(CaptionCue(cue.start, end, cue.text, cue.words))
    return held


def ass_color(hex_color: str, alpha: int = 0) -> str:
    value = hex_color.lstrip("#")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def inline_color(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    return f"&H{value[4:6]}{value[2:4]}{value[0:2]}&".upper()


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _escape(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _display(word: str, preset: CaptionPreset) -> str:
    return _escape(word.upper() if preset.uppercase else word)


def _karaoke_text(cue: CaptionCue, preset: CaptionPreset) -> str:
    parts: list[str] = []
    for index, word in enumerate(cue.words):
        next_start = cue.words[index + 1].start if index + 1 < len(cue.words) else word.end
        centiseconds = max(1, round((next_start - word.start) * 100))
        parts.append(f"{{\\kf{centiseconds}}}{_display(word.word, preset)}")
    return " ".join(parts)


def _highlight_text(cue: CaptionCue, active: int, preset: CaptionPreset) -> str:
    primary = inline_color(preset.primary)
    highlight = inline_color(preset.highlight)
    parts: list[str] = []
    for index, word in enumerate(cue.words):
        text = _display(word.word, preset)
        if index == active:
            tags = f"\\c{highlight}"
            if preset.pop:
                tags += "\\fscx88\\fscy88\\t(0,90,\\fscx112\\fscy112)\\t(90,170,\\fscx100\\fscy100)"
            parts.append(f"{{{tags}}}{text}{{\\c{primary}\\fscx100\\fscy100}}")
        else:
            parts.append(text)
    return " ".join(parts)


def _accent_text(cue: CaptionCue, active: int, preset: CaptionPreset) -> str:
    """Only the active word is visible; the rest keep their width but are transparent."""
    parts: list[str] = []
    for index, word in enumerate(cue.words):
        text = _display(word.word, preset)
        if index == active:
            parts.append(f"{{\\alpha&H00&}}{text}{{\\alpha&HFF&}}")
        else:
            parts.append(text)
        if index + 1 < len(cue.words):
            parts.append("{\\alpha&HFF&} ")
    return "{\\alpha&HFF&}" + "".join(parts)


def _style_line(name: str, preset: CaptionPreset, scale: float, **overrides: object) -> str:
    values = {
        "font": preset.font,
        "size": round(preset.size * scale),
        "primary": ass_color(preset.highlight if preset.mode == "karaoke" else preset.primary),
        "secondary": ass_color(preset.primary if preset.mode == "karaoke" else preset.highlight),
        "outline_color": ass_color(preset.outline),
        "back": ass_color("#000000", preset.shadow_alpha),
        "bold": -1 if preset.bold else 0,
        "border_style": 1,
        "outline": preset.outline_width * scale,
        "shadow": preset.shadow * scale,
    }
    values.update(overrides)
    return (
        f"Style: {name},{values['font']},{values['size']},{values['primary']},"
        f"{values['secondary']},{values['outline_color']},{values['back']},{values['bold']},"
        f"0,0,0,100,100,0,0,{values['border_style']},{values['outline']:.1f},"
        f"{values['shadow']:.1f},5,60,60,60,1"
    )


def write_ass_captions(
    cues: list[CaptionCue],
    destination: Path,
    style: CaptionStyle,
    width: int = 1080,
    height: int = 1920,
    position: Callable[[float], tuple[int, int]] | None = None,
) -> None:
    """Write an ASS file for an output of ``width`` x ``height``.

    ``position(t)`` returns the (x, y) center for a caption starting at ``t``;
    by default captions sit centered in the lower part of the frame.
    """
    preset = PRESETS[style]
    scale = min(width, height) / 1080
    place = position or (lambda _t: (width // 2, round(height * 0.8)))

    styles = [_style_line("Caption", preset, scale)]
    if preset.pill:
        styles.append(
            _style_line(
                "Pill", preset, scale, border_style=3, outline_color=ass_color(preset.pill),
                outline=14 * scale, shadow=0,
            )
        )
    if preset.glow:
        styles.append(
            _style_line(
                "Glow", preset, scale, primary=ass_color(preset.glow),
                outline_color=ass_color(preset.glow, 0x30), outline=7 * scale, shadow=0,
            )
        )
    if preset.plate:
        styles.append(
            _style_line(
                "Caption", preset, scale, border_style=3,
                outline_color=ass_color(preset.plate, preset.plate_alpha),
                back=ass_color(preset.plate, 0xFF), outline=18 * scale, shadow=0,
            )
        )
        styles = styles[1:]

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        + "\n".join(styles)
        + "\n\n[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )

    def event(layer: int, start: float, end: float, name: str, text: str, pos: str) -> str:
        return f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{name},,0,0,0,,{pos}{text}"

    events: list[str] = []
    for cue in cues:
        x, y = place(cue.start)
        pos = f"{{\\an5\\pos({x},{y})}}"
        if preset.mode == "karaoke":
            events.append(event(1, cue.start, cue.end, "Caption", _karaoke_text(cue, preset), pos))
            continue
        for index, word in enumerate(cue.words):
            start = cue.start if index == 0 else word.start
            end = cue.words[index + 1].start if index + 1 < len(cue.words) else cue.end
            if end - start < 0.01:
                continue
            if preset.glow:
                glow = "{\\blur9}" + _accent_text(cue, index, preset)
                events.append(event(0, start, end, "Glow", glow, pos))
            events.append(
                event(1, start, end, "Caption", _highlight_text(cue, index, preset), pos)
            )
            if preset.pill:
                events.append(event(0, start, end, "Pill", _accent_text(cue, index, preset), pos))
    destination.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
