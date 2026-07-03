"""Renders a field report to PDF with reportlab (no system deps).

Includes a small vector layout diagram (field outline + sampled planting points)
drawn straight from the coordinates, so no headless map renderer is needed.
"""
from __future__ import annotations

import datetime as dt
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

LAYER_COLORS = {
    "underground": colors.HexColor("#b5651d"),
    "ground": colors.HexColor("#7cd14f"),
    "middle": colors.HexColor("#3fae6a"),
    "vine": colors.HexColor("#56c2c2"),
    "top": colors.HexColor("#e2b13c"),
}
GREEN = colors.HexColor("#2f8a52")
MUTED = colors.HexColor("#667")

_styles = getSampleStyleSheet()
_H1 = ParagraphStyle("H1", parent=_styles["Title"], textColor=GREEN, fontSize=20)
_H2 = ParagraphStyle("H2", parent=_styles["Heading2"], textColor=GREEN, fontSize=13,
                     spaceBefore=10, spaceAfter=4)
_BODY = ParagraphStyle("Body", parent=_styles["BodyText"], fontSize=9.5, leading=13)
_MUTED = ParagraphStyle("Muted", parent=_BODY, textColor=MUTED, fontSize=8)


class FieldDiagram(Flowable):
    """Draws the field polygon + a sample of planting points to scale."""

    def __init__(self, ring: list[list[float]], points: list[tuple[float, float, str]],
                 width: float, height: float):
        super().__init__()
        self.ring = ring
        self.points = points
        self.width = width
        self.height = height

    def wrap(self, *_args):
        return self.width, self.height

    def _project(self):
        lons = [c[0] for c in self.ring]
        lats = [c[1] for c in self.ring]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        span_lon = (max_lon - min_lon) or 1e-6
        span_lat = (max_lat - min_lat) or 1e-6
        pad = 8
        scale = min((self.width - 2 * pad) / span_lon,
                    (self.height - 2 * pad) / span_lat)
        # centre the drawing
        off_x = (self.width - span_lon * scale) / 2
        off_y = (self.height - span_lat * scale) / 2

        def to_xy(lon: float, lat: float) -> tuple[float, float]:
            return (off_x + (lon - min_lon) * scale,
                    off_y + (lat - min_lat) * scale)

        return to_xy

    def draw(self):
        c = self.canv
        c.setFillColor(colors.HexColor("#0f1413"))
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        to_xy = self._project()

        # field outline
        path = c.beginPath()
        for i, (lon, lat) in enumerate(self.ring):
            x, y = to_xy(lon, lat)
            (path.moveTo if i == 0 else path.lineTo)(x, y)
        path.close()
        c.setStrokeColor(GREEN)
        c.setLineWidth(1.5)
        c.setFillColor(colors.HexColor("#15241a"))
        c.drawPath(path, fill=1, stroke=1)

        # planting points
        for lon, lat, layer in self.points:
            x, y = to_xy(lon, lat)
            c.setFillColor(LAYER_COLORS.get(layer, colors.white))
            c.circle(x, y, 1.1, fill=1, stroke=0)


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    data = [[Paragraph(f"<b>{k}</b>", _BODY), Paragraph(v, _BODY)] for k, v in rows]
    t = Table(data, colWidths=[55 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#dde")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _fmt(v, suffix: str = "") -> str:
    return f"{v}{suffix}" if v is not None else "—"


def build_report_pdf(ctx: dict) -> bytes:
    summary = ctx["summary"]
    soil = ctx.get("soil") or {}
    climate = ctx.get("climate") or {}
    ndvi = ctx.get("ndvi") or {}
    plans = ctx.get("plans") or []
    layout = ctx.get("layout")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="SmartFarm Field Report",
    )
    story: list = []

    region = summary.get("region", {})
    place = ", ".join(x for x in [region.get("district"), region.get("state")] if x) or "—"
    story.append(Paragraph("🌱 SmartFarm — Field Report", _H1))
    story.append(Paragraph(
        f"{place} · generated {dt.date.today().isoformat()}", _MUTED))
    story.append(Spacer(1, 6))

    # 1 · Field
    area = summary["area"]
    story.append(Paragraph("Your land", _H2))
    story.append(_kv_table([
        ("Area", f"{area['acres']} acre · {area['hectares']} ha · {area['guntha']} guntha"),
        ("Perimeter", f"{summary['perimeter_meters']} m"),
        ("Location", region.get("display_name") or place),
        ("Centroid", f"{summary['centroid']['lat']}, {summary['centroid']['lon']}"),
    ]))

    # 2 · Land intelligence
    story.append(Paragraph("Land intelligence", _H2))
    li_rows = [
        ("Soil texture", _fmt(soil.get("texture_class"))),
        ("Soil pH", _fmt(soil.get("ph"))),
        ("Season", _fmt(climate.get("season"))),
        ("Annual rainfall", _fmt(climate.get("annual_rainfall_mm"), " mm")
         + (f" ({climate.get('rainfall_band')})" if climate.get("rainfall_band") else "")),
        ("Avg max temp", _fmt(climate.get("temp_max_avg_c"), " °C")),
    ]
    if ndvi.get("mean") is not None:
        li_rows.append(("NDVI (vigour)", f"{ndvi['mean']} — {ndvi.get('vigour') or ''}"))
    story.append(_kv_table(li_rows))
    story.append(Paragraph(
        "Soil from SoilGrids (~250 m estimate); climate from Open-Meteo. "
        "Guidance only — verify with a local soil test.", _MUTED))

    # 3 · Layout diagram
    ring_coords = ctx.get("ring")
    if layout and ring_coords and layout.get("planting_points", {}).get("features"):
        story.append(Paragraph("Planting layout", _H2))
        pts = _sample_points(layout["planting_points"]["features"], 1200)
        story.append(FieldDiagram(ring_coords, pts, width=165 * mm, height=95 * mm))
        total = layout.get("total_plants", 0)
        story.append(Paragraph(
            f"Total plants: <b>{total:,}</b>"
            + (" (sampled)" if layout.get("truncated") else ""), _BODY))

    # 4 · Crop plans
    for plan in plans:
        crop = plan["crop"]
        story.append(Paragraph(
            f"Plan — {crop['name']} ({crop['layer']} layer)", _H2))
        fert = plan["fertilizer"]["total_kg"]
        story.append(_kv_table([
            ("Plants (est.)", f"{plan['plants']['total_estimate']:,}"),
            ("Seed quantity", f"{plan['seed']['quantity_kg']} kg"),
            ("Fertilizer (N-P-K)",
             f"{fert.get('N')} - {fert.get('P')} - {fert.get('K')} kg total"),
            ("Spacing", f"{plan['spacing_cm']['row']} × {plan['spacing_cm']['plant']} cm"),
        ]))
        cal = plan.get("calendar", [])
        if cal:
            data = [["Stage", "Day", "Date"]] + [
                [s["stage"], str(s["day"]), s["date"]] for s in cal]
            t = Table(data, colWidths=[80 * mm, 20 * mm, 40 * mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), GREEN),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cce")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(Spacer(1, 4))
            story.append(t)

    # 5 · Economics
    econ = ctx.get("economics")
    if econ and econ.get("crops"):
        story.append(Paragraph("Profit estimate (₹)", _H2))
        header = ["Crop", "Input cost", "Revenue", "Net margin"]
        rows = [header]
        for c in econ["crops"]:
            rows.append([
                c["name"],
                f"{c['cost']['total']:,}",
                f"{c['revenue'][0]:,}-{c['revenue'][1]:,}",
                f"{c['margin'][0]:,}-{c['margin'][1]:,}",
            ])
        tot = econ["totals"]
        rows.append([
            "TOTAL",
            f"{tot['cost']:,}",
            f"{tot['revenue'][0]:,}-{tot['revenue'][1]:,}",
            f"{tot['margin'][0]:,}-{tot['margin'][1]:,}",
        ])
        t = Table(rows, colWidths=[42 * mm, 32 * mm, 46 * mm, 46 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cce")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(t)
        story.append(Paragraph(econ.get("disclaimer", ""), _MUTED))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Estimates from a curated knowledge base and open geo-datasets. "
        "Confirm crop, spacing and fertilizer advice with a local agronomist "
        "before field use.", _MUTED))

    doc.build(story)
    return buf.getvalue()


def _sample_points(features: list, cap: int) -> list[tuple[float, float, str]]:
    step = max(1, len(features) // cap)
    out = []
    for f in features[::step]:
        lon, lat = f["geometry"]["coordinates"]
        out.append((lon, lat, f.get("properties", {}).get("layer", "")))
    return out
