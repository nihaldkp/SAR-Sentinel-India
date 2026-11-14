"""Page-specific reports assembled from persisted observations, not frontend measurements."""

from datetime import datetime, timezone
from io import BytesIO
from xml.sax.saxutils import escape

import numpy as np
import rasterio
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, PolyLine, Rect, String
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas.workspace_report import WorkspaceReportRequest
from app.services import acquisitions, analysis, sentinel2, vegetation_validation
from app.services.rivers import RIVER_CATALOG


def _value(value: object, suffix: str = "") -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, float):
        return f"{value:,.4f}{suffix}"
    return f"{value}{suffix}"


def _land_evidence(request: WorkspaceReportRequest) -> dict | None:
    if not request.vegetation_item_id:
        return None
    record = next(
        (item for item in sentinel2._load_catalog()
         if item.get("river_id") == request.vegetation_river_id
         and item.get("item_id") == request.vegetation_item_id),
        None,
    )
    if record is None or record.get("status") != "processed":
        raise ValueError("The selected vegetation observation is not a processed catalog record.")
    record = sentinel2.reconcile_cached_grid(record)
    if record.get("status") != "processed":
        raise ValueError("The selected vegetation observation has no usable raster pixels.")
    index = request.index_name
    if index is None:
        raise ValueError("An index is required for the selected vegetation observation.")
    path = sentinel2._cached_raster_path(record, index)
    with rasterio.open(path) as dataset:
        array = dataset.read(1, masked=True).astype(np.float32).filled(np.nan)
        values = array[np.isfinite(array)]
        stats = {
            "valid": int(values.size),
            "nodata": int(array.size - values.size),
            "minimum": float(values.min()) if values.size else None,
            "maximum": float(values.max()) if values.size else None,
            "mean": float(values.mean()) if values.size else None,
            "crs": str(dataset.crs) if dataset.crs else None,
            "shape": f"{dataset.width} x {dataset.height}",
        }
    assessments = vegetation_validation.list_assessments(request.vegetation_river_id or "")
    domain = "agriculture" if request.workspace == "Agriculture" else "forest"
    assessment = next(
        (item for item in assessments
         if item["protocol"]["item_id"] == request.vegetation_item_id
         and item["protocol"]["domain"] == domain
         and item["protocol"]["index_name"] == index),
        None,
    )
    return {"record": record, "index": index, "path": path, "stats": stats, "assessment": assessment}


def collect_report_data(request: WorkspaceReportRequest) -> dict:
    catalog = acquisitions.get_catalog_status().model_dump(mode="json")
    rivers = [river for river in catalog["rivers"]
              if request.river_id == "both" or river["river_id"] == request.river_id]
    products = [{**product, "river_id": river["river_id"], "mission": "NISAR"}
                for river in rivers for product in river.get("nisar_products", [])]
    observations = [{**item, "mission": "Sentinel-1"}
                    for river in rivers for item in river.get("observations", [])]
    products.sort(key=lambda item: item.get("acquisition_start") or "", reverse=True)
    observations.sort(key=lambda item: item.get("acquisition_start") or "", reverse=True)
    land = _land_evidence(request)
    records = [
        item for item in sentinel2._load_catalog()
        if request.river_id == "both" or item.get("river_id") == request.river_id
    ] if request.workspace in ("Agriculture", "Forest monitoring") else []
    selected_analysis = None
    if request.selected_analysis_id and not request.selected_analysis_id.startswith("nisar-"):
        try:
            selected_analysis = analysis._load_result(request.selected_analysis_id)
        except (ValueError, FileNotFoundError) as error:
            raise ValueError("The selected analysis is unavailable.") from error
        if request.river_id != "both" and selected_analysis.get("river_id") != request.river_id:
            raise ValueError("The selected analysis is outside the selected river.")
    return {
        "products": products,
        "observations": observations,
        "land": land,
        "land_records": records,
        "selected_analysis": selected_analysis,
        "selected_product": next(
            (item for item in products + observations
             if (request.selected_product_id and item["product_id"] == request.selected_product_id)
             or (request.selected_analysis_id and (
                 item.get("analysis_id") == request.selected_analysis_id
                 or f"nisar-{item['product_id']}" == request.selected_analysis_id
             ))),
            None,
        ),
    }


def _river_map(river_id: str) -> Drawing | None:
    selected = [river for river in RIVER_CATALOG if river_id == "both" or river.id == river_id]
    segments = []
    for river in selected:
        coordinates = river.centerline.coordinates
        lines = [coordinates] if river.centerline.type == "LineString" else coordinates
        for line in lines:
            if len(line) >= 2:
                segments.append((river.id, line))
    if not segments:
        return None
    points = [point for _, line in segments for point in line]
    west, east = min(p[0] for p in points), max(p[0] for p in points)
    south, north = min(p[1] for p in points), max(p[1] for p in points)
    width, height, margin = 490, 180, 15
    scale = min((width - 2*margin) / max(east - west, 0.0001),
                (height - 2*margin) / max(north - south, 0.0001))
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f4f8f6"), strokeColor=colors.HexColor("#c8d8d3")))
    for river, line in segments:
        step = max(1, len(line) // 2000)
        sampled = line[::step]
        if sampled[-1] != line[-1]:
            sampled = [*sampled, line[-1]]
        xy = [coordinate for lon, lat, *_ in sampled
              for coordinate in (margin + (lon - west) * scale, margin + (lat - south) * scale)]
        drawing.add(PolyLine(xy, strokeColor=colors.HexColor("#1f7fc2" if river == "kaveri" else "#eb8a2f"), strokeWidth=1.2))
    drawing.add(String(10, height - 12, "OSM registered centerlines; schematic WGS84 view", fontSize=8, fillColor=colors.HexColor("#375b57")))
    return drawing


def build_workspace_report(request: WorkspaceReportRequest) -> tuple[BytesIO, str]:
    data = collect_report_data(request)
    now = datetime.now(timezone.utc)
    river_names = {
        "both": "Kaveri and Tungabhadra",
        "kaveri": "Kaveri",
        "tungabhadra": "Tungabhadra",
    }
    descriptions = {
        "Overview": "A catalog-level overview of persisted NISAR and Sentinel-1 evidence, with each candidate kept separate.",
        "Map explorer": "Registered river geometry and selected map-layer context; geometry alone does not establish monitoring coverage.",
        "Change analysis": "The available acquisition timeline and processing states. A change claim requires compatible observations and a documented comparison.",
        "Impact explorer": "The latest eligible NISAR candidate for the selected river selection, not a cumulative area or a validated impact estimate.",
        "Agriculture": "Sentinel-2 spectral vegetation indices within mapped river-centerline support, not crop classification, health, or yield.",
        "Forest monitoring": "Sentinel-2 spectral indices are not forest classification. Natural forest, plantations and other vegetation require independent land-cover references.",
        "AI analysis": "A deterministic summary of persisted satellite evidence; no generative model was used in this report.",
        "Data & methodology": "The report describes the implemented processing methods and their scientific boundaries.",
        "About the project": "SAR Sentinel India explores documented satellite observations for Indian river regions.",
    }
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontSize=20, leading=24, textColor=colors.HexColor("#18343c"), spaceAfter=12))
    styles.add(ParagraphStyle(name="ReportBody", parent=styles["BodyText"], fontSize=9, leading=13, spaceAfter=6, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="ReportCell", parent=styles["BodyText"], fontSize=8, leading=10, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="ReportHeading", parent=styles["Heading2"], textColor=colors.HexColor("#23685f"), spaceBefore=10, spaceAfter=6))
    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm,
                            title=f"SAR Sentinel India - {request.workspace} report")
    story = []

    def paragraph(text: object, style: str = "ReportBody") -> None:
        story.append(Paragraph(escape(str(text)), styles[style]))

    def heading(text: str) -> None:
        paragraph(text, "ReportHeading")

    def table(rows: list[list[object]], widths: list[float]) -> None:
        values = [[Paragraph(escape(str(cell)), styles["ReportCell"]) for cell in row] for row in rows]
        result = Table(values, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceee9")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c8d8d3")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(result)
        story.append(Spacer(1, 5))

    paragraph(f"SAR Sentinel India - {request.workspace}", "ReportTitle")
    paragraph(f"Generated {now.strftime('%Y-%m-%d %H:%M UTC')} | NASA Space Apps Challenge 2026")
    heading("Executive summary")
    paragraph(descriptions[request.workspace])
    paragraph("Interpretation method: deterministic, data-grounded rules. No AI model or external AI service was used.")
    heading("Workspace and study region")
    table([["Field", "Selected context"], ["Workspace", request.workspace],
           ["Study region", river_names[request.river_id]],
           ["Selected map layer", request.map_layer if request.workspace in ("Overview", "Map explorer") else "Not applicable"],
           ["Selected satellite product", _value((data["selected_product"] or {}).get("product_id") or request.selected_product_id)],
           ["Selected analysis", _value(request.selected_analysis_id)],
           ["Selected optical item", _value(request.selected_optical_item_id)],
           ["Selected NWIC source ID", _value(request.selected_network_id)]], [55*mm, 119*mm])

    heading("Satellite data, acquisition details and observed results")
    land = data["land"]
    if request.workspace in ("Agriculture", "Forest monitoring"):
        records = data["land_records"]
        if records:
            table([["River / product", "Acquisition", "Processing"]]
                  + [[f"{r.get('river_id', 'Unavailable')} / {r.get('item_id', 'Unavailable')}",
                      _value(r.get("acquisition_datetime")), _value(r.get("status"))] for r in records],
                  [98*mm, 48*mm, 28*mm])
        else:
            paragraph("No saved Sentinel-2 observation is available for this selection.")
        if land:
            record, stats = land["record"], land["stats"]
            table([["Selected index measurement", "Value"],
                   ["Product / index", f"{record['item_id']} / {land['index'].upper()}"],
                   ["Acquisition", _value(record.get("acquisition_datetime"))],
                   ["Cloud cover", _value(record.get("cloud_cover_percent"), "%")],
                   ["Grid / CRS / resolution", f"{stats['shape']} / {_value(stats['crs'])} / {_value(record.get('resolution_m'), ' m')}"],
                   ["Raster valid / NoData pixels", f"{stats['valid']:,} / {stats['nodata']:,}"],
                   ["Raster mean / minimum / maximum", f"{_value(stats['mean'])} / {_value(stats['minimum'])} / {_value(stats['maximum'])}"],
                   ["Catalog NDVI valid count", _value(record.get("valid_pixel_count"))],
                   ["Valid centerline coverage", _value(record.get("valid_pixel_percent"), "%")]],
                  [70*mm, 104*mm])
            if record.get("raster_reconciliation"):
                metadata = record["raster_reconciliation"]["catalog_metadata"]
                paragraph(f"Catalog grid mismatch: stored grid {_value(metadata.get('width'))} x {_value(metadata.get('height'))} and NDVI count {_value(metadata.get('valid_pixel_count'))}; current grid {stats['shape']} and NDVI count {_value(record.get('valid_pixel_count'))}. Current raster processing provenance and centerline coverage are unavailable; original catalog metadata is retained.")
            if land["index"] == "ndvi" and record.get("valid_pixel_count") is not None and record["valid_pixel_count"] != stats["valid"]:
                paragraph("The stored catalog valid count differs from the current selected raster. The raster statistics above were read from the GeoTIFF; the discrepancy has not been resolved.")
            if land["index"] != "ndvi":
                paragraph("The catalog count and centerline coverage refer to NDVI, not necessarily the selected index.")
            heading("Visual evidence")
            preview = sentinel2.render_index_png(land["path"], overview=True)
            image = Image(BytesIO(preview))
            image._restrictSize(150*mm, 65*mm)
            image_table = Table([[image]], colWidths=[160*mm], hAlign="LEFT")
            image_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#a3adab"))]))
            story.append(image_table)
            paragraph(f"{land['index'].upper()} valid-pixel mean overview from the selected GeoTIFF. Transparent cells are NoData. Coloured thumbnail cells do not represent measured area. Fixed colour range: -1 blue, 0 pale yellow, +1 green.")
        else:
            paragraph("Selected index raster: unavailable. No raster measurement or image is substituted.")
    else:
        rows = [["River / mission / product", "Date", "Processing / support / candidate area"]]
        for item in data["products"]:
            result = item.get("processing_result") or {}
            rows.append([f"{item['river_id']} / NISAR GCOV / {item['product_id']}",
                         _value(item.get("acquisition_start")),
                         f"{_value(result.get('status') or item.get('processing_status'))}; valid pixels {_value(result.get('valid_pixel_count'))}; candidate {_value(result.get('candidate_water_area_m2'), ' m2')}"])
        if request.workspace not in ("Change analysis", "Impact explorer"):
            for item in data["observations"]:
                rows.append([f"{item['river_id']} / Sentinel-1 RTC / {item['product_id']}",
                             _value(item.get("acquisition_start")),
                             f"{_value(item.get('processing_status'))}; valid pixels {_value(item.get('valid_pixel_count'))}; candidate {_value(item.get('candidate_water_area_m2'), ' m2')}"])
        if len(rows) > 1:
            table(rows, [83*mm, 39*mm, 52*mm])
        else:
            paragraph("No persisted acquisition evidence is available for this workspace and river selection.")
        if request.workspace == "Impact explorer":
            eligible = [p for p in data["products"] if (p.get("processing_result") or {}).get("status") == "unvalidated_candidate"]
            selected = eligible[0] if eligible else None
            paragraph(f"Impact card selection: {selected['product_id'] if selected else 'Unavailable'}. Only this latest eligible NISAR candidate is represented by the impact cards; the table lists separate observations.")
        if request.selected_product_id:
            if not any(item["product_id"] == request.selected_product_id for item in data["products"] + data["observations"]):
                paragraph("The selected product is not in the persisted acquisition catalog; its acquisition details and measurements are unavailable in this report.")
        if data["selected_analysis"]:
            result = data["selected_analysis"]
            paragraph(f"Selected persisted analysis: {result.get('analysis_type', 'Unavailable')} | source product {_value(result.get('source_product_id'))} | acquisition {_value(result.get('acquisition_start'))} | candidate area {_value(result.get('candidate_water_area_m2'), ' m2')}.")
        heading("Visual evidence")
        if request.workspace in ("Overview", "Map explorer"):
            drawing = _river_map(request.river_id)
            if drawing:
                story.append(drawing)
                paragraph("Blue: Kaveri; orange: Tungabhadra. Registered OSM centerline geometry is simplified for display and does not establish monitoring coverage. The selected raster, footprint or candidate layer is not shown in this schematic.")
            else:
                paragraph("Registered river geometry is unavailable; no map is substituted.")
        else:
            paragraph("A compatible map or chart image is unavailable for this report; no image is substituted.")

    heading("Processing methodology")
    paragraph("NISAR GCOV candidate processing uses valid HH/HV backscatter and the documented corridor and thresholds. Sentinel-1 RTC candidates use calibrated VV intensity, filtering and thresholding. Sentinel-2 indices use surface reflectance and scene-classification and mapped-centerline masks at the recorded output resolution. Refer to the product metadata for exact parameters.")
    heading("Data-grounded interpretation")
    paragraph(descriptions[request.workspace])
    paragraph("Recorded candidate areas are exploratory classifications for individual acquisitions. They may motivate further inspection but do not establish water extent, flooding, impacts, causes or environmental change.")
    heading("Limitations and uncertainty")
    paragraph("Observations differ in date, spatial support, cloud and acquisition conditions. Centerline geometry is not proof of coverage. No candidate areas from different dates are summed. Missing values are explicitly unavailable.")
    paragraph("The current vegetation rasters are sparse centerline samples, not representative surrounding farmland or forest. An index alone cannot establish crop health, yield, forest cover, forest loss or deforestation.")
    if request.workspace == "Forest monitoring":
        paragraph("River-distance zones of 0-100 m, 100-500 m and 500-1,000 m and their comparison are unavailable: saved indices sample the mapped centerline, and a suitable local tree-cover reference is not integrated. Tree cover alone would not distinguish natural forest from plantations.")
    heading("Validation status")
    if land and land["assessment"]:
        assessment = land["assessment"]
        protocol = assessment.get("protocol") or {}
        paragraph(f"Selected index assessment: {assessment.get('status', 'NOT_VALIDATED')}. {assessment.get('reason', '')}")
        paragraph(f"Declared reference: {_value(protocol.get('reference_dataset'))}; acquisition {_value(protocol.get('reference_acquisition_datetime'))}; method {_value(protocol.get('methodology'))}. A completed assessment is sample-scoped index agreement, not land-cover or change classification validation.")
        paragraph(f"Index reference provider / resolution: {_value(protocol.get('reference_provider'))} / {_value(protocol.get('reference_resolution_m'), ' m')}. Land-cover reference: {_value(protocol.get('landcover_dataset'))}; provider {_value(protocol.get('landcover_provider'))}; acquisition {_value(protocol.get('landcover_acquisition_datetime'))}; resolution {_value(protocol.get('landcover_resolution_m'), ' m')}.")
        metrics = assessment.get("metrics") or {}
        if metrics.get("rmse") is not None:
            paragraph(f"Recorded sample metrics: RMSE {_value(metrics.get('rmse'))}, MAE {_value(metrics.get('mae'))}, bias {_value(metrics.get('bias'))}; common target pixels {_value(metrics.get('common_target_pixels'))}.")
        for limitation in assessment.get("limitations") or []:
            paragraph(f"Assessment limitation: {limitation}")
    elif land:
        paragraph("Selected index assessment: NOT_VALIDATED. No independent reference assessment has been recorded.")
    else:
        paragraph("Independent validation evidence for the selected measurement is unavailable in this report. Candidate classification is not confirmed water or flood extent.")
    heading("Conclusions and recommendations")
    paragraph("The available records support exploratory inspection only. Obtain independently reviewed, temporally compatible reference data and predeclare assessment criteria before making classification or change-accuracy claims.")
    heading("Data sources and product references")
    paragraph("NISAR L2 GCOV: ASF DAAC; Sentinel-1 RTC and Sentinel-2 L2A: Microsoft Planetary Computer; registered river geometry: OpenStreetMap contributors. Product identifiers and acquisition dates above refer to the persisted catalog.")
    paragraph("NWIC River Network is a separate source of reference geometry. Verified river geometry matches can select a pilot, but do not establish coverage by any satellite observation.")

    def footer(canvas, document) -> None:
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#607875"))
        canvas.drawString(18*mm, 10*mm, "SAR Sentinel India | Unvalidated research evidence")
        canvas.drawRightString(A4[0] - 18*mm, 10*mm, f"Page {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    stream.seek(0)
    river_part = {"both": "Both-Rivers", "kaveri": "Kaveri", "tungabhadra": "Tungabhadra"}[request.river_id]
    page_part = request.workspace.replace(" & ", "-and-").replace(" ", "-")
    return stream, f"SAR-Sentinel-India_{river_part}_{page_part}_Report_{now:%Y-%m-%d}.pdf"
