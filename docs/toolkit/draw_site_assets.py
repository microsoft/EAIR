"""Regenerate documentation bitmap diagrams; Pillow is a design-time dependency."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ASSETS = Path(__file__).resolve().parents[2] / "enterprise_toolkit" / "site" / "assets"


def font(size: int, *, bold: bool = False):
    windows = Path("C:/Windows/Fonts") / ("seguisb.ttf" if bold else "segoeui.ttf")
    return ImageFont.truetype(str(windows) if windows.is_file() else "DejaVuSans.ttf", size)


def arrow(draw, points, color="#67857a"):
    draw.line(points, fill=color, width=4, joint="curve")
    end = points[-1]
    previous = points[-2]
    if end[0] > previous[0]:
        head = [(end[0] - 11, end[1] - 8), end, (end[0] - 11, end[1] + 8)]
    elif end[0] < previous[0]:
        head = [(end[0] + 11, end[1] - 8), end, (end[0] + 11, end[1] + 8)]
    else:
        head = [(end[0] - 8, end[1] - 11), end, (end[0] + 8, end[1] - 11)]
    draw.line(head, fill=color, width=4)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1560, 460), "#ffffff")
    draw = ImageDraw.Draw(image)
    nodes = [
        (30, 35, "01", "Microworld", "Observed messages + tool events", "#edf5f0", "#27654f"),
        (565, 35, "02", "Sanitized bundle", "Evidence only; identity map private", "#edf5f0", "#27654f"),
        (1100, 35, "03", "Auditor", "Findings + bounded repair plans", "#fff6e8", "#94661b"),
        (1100, 265, "04", "Isolated Coder", "Source copy + smoke / utility checks", "#edf1f9", "#365d9a"),
        (565, 265, "05", "Repair Auditor", "Independent comparison + feedback", "#edf1f9", "#365d9a"),
        (30, 265, "06", "Fresh replay", "Held-out risk + legitimate-work cases", "#edf5f0", "#27654f"),
    ]
    for left, top, number, title, subtitle, fill, accent in nodes:
        draw.rounded_rectangle((left, top, left + 430, top + 135), radius=8, fill=fill, outline="#d5dfd9", width=2)
        draw.rectangle((left, top + 16, left + 4, top + 119), fill=accent)
        draw.text((left + 24, top + 18), number, fill=accent, font=font(19, bold=True))
        draw.text((left + 64, top + 13), title, fill="#243b30", font=font(31, bold=True))
        draw.text((left + 24, top + 76), subtitle, fill="#526b5e", font=font(22))
    arrow(draw, [(461, 104), (550, 104)])
    arrow(draw, [(996, 104), (1085, 104)])
    arrow(draw, [(1315, 171), (1315, 250)])
    arrow(draw, [(1099, 332), (1010, 332)])
    arrow(draw, [(564, 332), (475, 332)])
    draw.text((34, 204), "PRIVATE MAPPING AND REFERENCE LABELS STAY OUTSIDE THE AUDITOR INPUT", fill="#718379", font=font(18))
    image.save(ASSETS / "workflow.png", optimize=True)
    print("Generated workflow.png (1560x460)")


if __name__ == "__main__":
    main()