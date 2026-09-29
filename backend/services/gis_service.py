"""GIS service for spatial operations, dynamic Indian UTM projections, and geodesic area validation."""

import logging
import json
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path
from shapely.geometry import shape, Point, Polygon, MultiPolygon, mapping
from shapely.ops import transform
import pyproj
import unicodedata

logger = logging.getLogger("geoldger.gis")

# Standard WGS84 lat/lon coordinate reference system
WGS84 = pyproj.CRS("EPSG:4326")
ACRE_UNIT_LABELS = {
    "acre", "acres", "एकड़", "একর", "એકર", "ஏக்கர்", "ఎకరాలు",
    "ಎಕರೆ", "ഏക്കർ", "ଏକର", "ਏਕੜ", "ایکڑ",
}


def area_to_acres(value: Optional[float], unit: Optional[str]) -> Optional[float]:
    """Normalize known acre labels; return None rather than compare unlike units."""
    if value is None or float(value) <= 0:
        return None
    normalized = unicodedata.normalize("NFKC", (unit or "").strip()).casefold()
    if normalized in ACRE_UNIT_LABELS:
        return float(value)
    return None


def get_utm_crs_for_geometry(geom: Any) -> Tuple[pyproj.CRS, int]:
    """
    Dynamically determine the appropriate UTM projection CRS and Zone
    based on the geometry's centroid coordinates across all Indian states.

    Indian UTM Zones (Northern Hemisphere):
    - Zone 42N (EPSG:32642): 66°E - 72°E (Western Gujarat, West Rajasthan)
    - Zone 43N (EPSG:32643): 72°E - 78°E (Maharashtra, Karnataka, Kerala, Goa, Gujarat, MP, Rajasthan, Punjab, Delhi, J&K)
    - Zone 44N (EPSG:32644): 78°E - 84°E (Andhra, Telangana, Tamil Nadu, Odisha, MP, UP, Uttarakhand)
    - Zone 45N (EPSG:32645): 84°E - 90°E (West Bengal, Bihar, Jharkhand, Sikkim, Meghalaya)
    - Zone 46N (EPSG:32646): 90°E - 96°E (Assam, Arunachal, Nagaland, Manipur, Mizoram, Tripura)
    - Zone 47N (EPSG:32647): 96°E - 102°E (Eastern Arunachal)
    """
    centroid = geom.centroid
    lon = centroid.x
    lat = centroid.y

    # Calculate UTM zone number from longitude: zone = int((lon + 180) / 6) + 1
    zone_number = int((lon + 180) / 6) + 1
    # Clamp to valid UTM zones (1 to 60)
    zone_number = max(1, min(60, zone_number))

    # EPSG for Northern hemisphere UTM is 32600 + zone
    epsg_code = 32600 + zone_number if lat >= 0 else 32700 + zone_number
    utm_crs = pyproj.CRS(f"EPSG:{epsg_code}")

    logger.info(f"Dynamically resolved CRS for lon={lon:.4f}, lat={lat:.4f} -> UTM Zone {zone_number}N (EPSG:{epsg_code})")
    return utm_crs, zone_number


def extract_raw_geometry(geojson_data: Any) -> Dict[str, Any]:
    """Extract raw geometry dict from Feature, FeatureCollection, or Geometry object."""
    if isinstance(geojson_data, str):
        try:
            geojson_data = json.loads(geojson_data)
        except Exception as e:
            raise ValueError(f"Invalid GeoJSON JSON string: {e}")

    if not isinstance(geojson_data, dict):
        raise ValueError("GeoJSON must be a dictionary or valid JSON object")

    if geojson_data.get("type") == "FeatureCollection":
        features = geojson_data.get("features", [])
        if not features:
            raise ValueError("FeatureCollection contains no features")
        return extract_raw_geometry(features[0])

    if geojson_data.get("type") == "Feature":
        geom = geojson_data.get("geometry")
        if not geom:
            raise ValueError("Feature has no geometry property")
        return geom

    return geojson_data


def parse_geojson(geojson_data: Any) -> Tuple[Any, str]:
    """
    Parse GeoJSON and return Shapely geometry.
    Returns (geometry, geometry_type)
    """
    try:
        raw_geom = extract_raw_geometry(geojson_data)
        geom = shape(raw_geom)
        geom_type = geom.geom_type
        logger.info(f"Parsed GeoJSON: {geom_type}, valid={geom.is_valid}")
        return geom, geom_type
    except Exception as e:
        logger.error(f"Failed to parse GeoJSON: {e}")
        raise ValueError(f"Invalid GeoJSON: {e}")


def calculate_area_from_geojson(geojson_data: Any, use_projected: bool = True) -> Tuple[float, str, float]:
    """
    Calculate area from GeoJSON geometry using dynamic UTM projected CRS.

    Returns (area_in_acres, unit_label, area_sq_meters)
    """
    geom, geom_type = parse_geojson(geojson_data)

    if geom_type not in ["Polygon", "MultiPolygon"]:
        raise ValueError(f"Cannot calculate area for geometry type: {geom_type}")

    if not geom.is_valid:
        logger.warning("Invalid geometry detected, attempting to fix with buffer(0)")
        geom = geom.buffer(0)
        if not geom.is_valid:
            raise ValueError("Geometry is invalid and cannot be fixed")

    if use_projected:
        # Dynamically determine the correct UTM CRS based on the parcel's geographic location
        utm_crs, zone_num = get_utm_crs_for_geometry(geom)
        project = pyproj.Transformer.from_crs(WGS84, utm_crs, always_xy=True).transform
        geom_projected = transform(project, geom)
        area_sq_meters = geom_projected.area
        logger.info(f"Projected area (UTM Zone {zone_num}N): {area_sq_meters:.2f} m²")
    else:
        # Rough calculation in degrees (not recommended)
        area_sq_meters = geom.area * 111320 * 111320
        logger.warning("Using unprojected area calculation - inaccurate!")

    # Convert square meters to acres (1 acre = 4046.8564224 sq.m)
    area_acres = area_sq_meters / 4046.8564224
    logger.info(f"Calculated area: {area_acres:.4f} acres ({area_sq_meters:.2f} m²)")

    return round(area_acres, 4), "acres", round(area_sq_meters, 2)


def compare_areas(doc_area: float, gis_area: float, tolerance: float = 0.10) -> Dict[str, Any]:
    """
    Compare document-stated area with GIS-calculated area.

    Args:
        doc_area: Area from land record document (acres)
        gis_area: GIS-calculated area (acres)
        tolerance: Acceptable variance as fraction (default 0.10 = 10%)

    Returns dict with:
        - variance_acres
        - variance_percent
        - within_tolerance (bool)
        - severity (INFO/MEDIUM/HIGH/CRITICAL)
        - explanation
    """
    variance_acres = abs(doc_area - gis_area)
    variance_pct = (variance_acres / doc_area) * 100 if doc_area > 0 else 0.0

    within_tolerance = variance_pct <= (tolerance * 100)

    if variance_pct < 5:
        severity = "INFO"
    elif variance_pct <= 10:
        severity = "LOW"
    elif variance_pct <= 25:
        severity = "MEDIUM"
    elif variance_pct <= 50:
        severity = "HIGH"
    else:
        severity = "CRITICAL"

    if within_tolerance:
        status_label = "MATCH"
        explanation = f"GIS geodesic area ({gis_area:.4f} acres) matches recorded area ({doc_area:.4f} acres) within {tolerance*100:.0f}% tolerance (variance: {variance_pct:.2f}%)."
    else:
        status_label = "DISCREPANCY"
        explanation = f"GIS geodesic area ({gis_area:.4f} acres) differs from recorded area ({doc_area:.4f} acres) by {variance_pct:.2f}% ({variance_acres:.4f} acres deviation). Requires verification review."

    result = {
        "document_area": round(doc_area, 4),
        "gis_area": round(gis_area, 4),
        "variance_acres": round(variance_acres, 4),
        "variance_percent": round(variance_pct, 2),
        "within_tolerance": within_tolerance,
        "status": status_label,
        "severity": severity,
        "tolerance_percent": round(tolerance * 100, 1),
        "explanation": explanation,
    }

    logger.info(
        f"Area comparison: doc={doc_area:.4f} vs gis={gis_area:.4f}, "
        f"variance={variance_pct:.2f}%, status={status_label}"
    )

    return result


def validate_geometry(geojson_data: Any) -> Dict[str, Any]:
    """
    Validate GeoJSON geometry for topological correctness, vertex count, self-intersections, and bounds.
    Returns dict with validation results and diagnostic details.
    """
    try:
        raw_geom = extract_raw_geometry(geojson_data)
        geom, geom_type = parse_geojson(raw_geom)

        issues = []
        warnings = []

        # Check validity
        if not geom.is_valid:
            issues.append(f"Topologically invalid geometry: {getattr(geom, 'is_valid_reason', 'Self-intersection or degenerate ring')}")

        if geom_type not in ("Polygon", "MultiPolygon"):
            issues.append(f"Parcel geometry must be Polygon or MultiPolygon (found {geom_type})")

        # Check for empty
        if geom.is_empty:
            issues.append("Geometry is empty")

        # Check coordinate bounds
        bounds = list(geom.bounds) if geom and not geom.is_empty else None  # [minx, miny, maxx, maxy]
        if bounds and len(bounds) == 4:
            minx, miny, maxx, maxy = bounds
            width = maxx - minx
            height = maxy - miny

            # Check for inverted or invalid lat/lon
            if miny < -90 or maxy > 90:
                issues.append(f"Latitude out of valid range [-90, 90]: [{miny}, {maxy}]")
            if minx < -180 or maxx > 180:
                issues.append(f"Longitude out of valid range [-180, 180]: [{minx}, {maxx}]")

            # Check Indian subcontinental coordinate bounds warning
            if not (6.0 <= miny <= 38.0 and 68.0 <= minx <= 98.0):
                warnings.append(f"Coordinates [{minx:.4f}, {miny:.4f}] are outside standard Indian territory bounds")

            # Suspiciously small/large
            if width < 0.00001 or height < 0.00001:
                warnings.append("Geometry is exceptionally small (< 1 meter)")
            elif width > 2.0 or height > 2.0:
                warnings.append("Geometry is exceptionally large (> 200 km)")

        # Polygon-specific checks
        coord_count = 0
        polygons = [geom] if geom_type == "Polygon" else list(geom.geoms) if geom_type == "MultiPolygon" else []
        for polygon in polygons:
            coords = list(polygon.exterior.coords)
            coord_count += len(coords)
            if len(coords) < 4:
                issues.append(f"Polygon must have at least 4 vertices (found {len(coords)})")
            if not polygon.exterior.is_simple:
                issues.append("Polygon has a self-intersecting exterior boundary")
            if any(a == b for a, b in zip(coords, coords[1:])):
                issues.append("Polygon boundary contains consecutive duplicate vertices")
            for ring in polygon.interiors:
                ring_coords = list(ring.coords)
                if any(a == b for a, b in zip(ring_coords, ring_coords[1:])):
                    issues.append("Polygon hole contains consecutive duplicate vertices")

        # Compute dynamic projection and area if valid
        calculated_area_acres = None
        calculated_area_sqm = None
        utm_zone = None
        if not issues and geom_type in ["Polygon", "MultiPolygon"]:
            try:
                acres, _, sqm = calculate_area_from_geojson(raw_geom, use_projected=True)
                calculated_area_acres = acres
                calculated_area_sqm = sqm
                if sqm <= 0.01:
                    issues.append("Polygon area is zero or too small for a parcel boundary")
                _, utm_zone = get_utm_crs_for_geometry(geom)
            except Exception as ex:
                warnings.append(f"Area computation note: {ex}")

        return {
            "valid": len(issues) == 0,
            "geometry_type": geom_type,
            "issues": issues,
            "warnings": warnings,
            "bounds": bounds,
            "coordinate_count": coord_count,
            "calculated_area_acres": calculated_area_acres,
            "calculated_area_sqm": calculated_area_sqm,
            "utm_zone": f"Zone {utm_zone}N" if utm_zone else None,
        }

    except Exception as e:
        logger.error(f"Geometry validation error: {e}")
        return {
            "valid": False,
            "geometry_type": None,
            "issues": [f"Parse error: {str(e)}"],
            "warnings": [],
            "bounds": None,
            "coordinate_count": 0,
            "calculated_area_acres": None,
            "calculated_area_sqm": None,
            "utm_zone": None,
        }
