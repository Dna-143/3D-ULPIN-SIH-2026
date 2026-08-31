# Part 1 — Ingestion and Projected Transformation

## What this part proves

Part 1 turns an uploaded cadastral file into checked, metre-based geometry that later parts
can store as 3D parcels. It solves three common production failures:

1. **Bad legal geometry enters the database.** The validator rejects empty, self-intersecting,
   unclosed, duplicate-ID, non-finite, and structurally invalid data. It never silently repairs
   a property boundary.
2. **Latitude/longitude degrees are treated like metres.** The engine finds the dataset's WGS 84
   centroid and makes that point the origin of a custom ellipsoidal Transverse Mercator grid.
3. **One mistyped survey point shifts the whole model.** A deterministic RANSAC solver fits a 2D
   similarity transformation, excludes points outside the metre threshold, and reports every
   residual.

## Workflow in simple language

| Stage | What happens | Evidence returned |
|---|---|---|
| 1. Read | Browser parses the GeoJSON; the API receives JSON, source CRS, and optional controls. | Source SHA-256 |
| 2. Check | Structure, IDs, finite coordinates, ring closure, topology, limits, and dimensions are checked. | Feature/coordinate counts and exact errors |
| 3. Centre | Geometry is safely transformed to WGS 84 only to calculate the project centroid and extent. | Longitude/latitude origin |
| 4. Project | A local `+proj=tmerc` grid is built around that centroid; X/Y become metres. | PROJ string, WKT2, extent, distortion estimate |
| 5. Filter | RANSAC repeatedly tests control-point pairs and keeps the largest consistent group. | Inlier/outlier IDs, residuals, RMSE, fitted transform |
| 6. Return | The geometry and quality report are returned without writing to the legal database. | Projected FeatureCollection and bounding box |

## Why a centroid-based Transverse Mercator grid

Decimal-degree scaling is not a coordinate transformation: a degree of longitude changes
physical length with latitude. Transverse Mercator is conformal, uses an ellipsoidal Earth, and
lets the selected central meridian keep constant scale. Part 1 chooses the parcel dataset's
centroid as `lon_0` and `lat_0`, uses `k_0=1`, and rejects extents wider than 6° so a local job is
not accidentally treated as a national grid.

The response includes a corner-sampled scale error in parts per million. This makes the
projection decision measurable during a demo instead of merely claiming it is accurate.

Authoritative references:

- [PROJ Transverse Mercator](https://proj.org/en/stable/operations/projections/tmerc.html)
- [pyproj Transformer and `always_xy`](https://pyproj4.github.io/pyproj/stable/api/transformer.html)
- [Shapely validity check](https://shapely.readthedocs.io/en/stable/reference/shapely.is_valid.html)

## What RANSAC is doing

Suppose five known boundary corners are entered. Four agree within 0.2 m, but one longitude was
typed as `73.86682` instead of `73.85682`—roughly a kilometre away. A normal least-squares fit is
pulled by that error. RANSAC tests small point pairs, measures all residuals, refits the largest
group within the threshold, and labels the mistyped point as an outlier. The outlier is excluded
from calibration; it is not silently deleted from the audit report.

The fitted model is a 2D similarity transform:

\[
X = ax - by + t_x, \qquad Y = bx + ay + t_y
\]

It permits one uniform scale, one rotation, and X/Y translation. It does not warp parcel shapes.

## Z-coordinate rule

Part 1 transforms only horizontal X/Y. Every Z value is preserved exactly. If the request does
not name a vertical reference (for example, `EGM2008 orthometric height`), the result carries a
warning. A geoid or vertical-datum conversion must be explicit in a later pipeline; inventing one
would create false legal accuracy.

## API contract

`POST /api/v1/ingestions/preview`

```json
{
  "dataset_name": "Pune ward demo",
  "source_crs": "EPSG:4326",
  "vertical_reference": "Demo orthometric height in metres",
  "geojson": { "type": "FeatureCollection", "features": [] },
  "control_points": [],
  "ransac": {
    "residual_threshold_m": 0.75,
    "max_trials": 512,
    "min_inlier_ratio": 0.6,
    "random_seed": 42
  },
  "apply_control_alignment": false
}
```

Use either zero control points or at least four. The committed Pune sample has five, including
one deliberate typo named `cp-typo`.

## WebMCP action

The demo page registers one imperative tool named `preview_cadastral_ingestion` when the browser
supports `document.modelContext`. Its name says **preview** because it does not persist anything.
It validates input, runs the same API, updates the visible result, and returns only a concise
quality summary to the agent. User-provided GeoJSON is marked as untrusted content.

## Judge demo (about 60 seconds)

1. Open the page and click **Load Pune demo**.
2. Point out that the source is EPSG:4326 and contains two adjacent 3D parcel footprints.
3. Click **Run Part 1**.
4. Show that X/Y are now metres around a local `(0,0)` origin while Z remains around `560 m`.
5. Show `cp-typo` in the red outlier card and the four accepted control points.
6. Expand the technical result to show WKT, distortion, residuals, and the transformed data.

## Current boundaries

- Accepted geometry types: Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon.
- Maximum per preview: 10,000 features and 1,000,000 positions.
- A local grid is limited to 6° longitude and 6° latitude; larger projects must be partitioned.
- This part does not persist data, build solids, issue ULPINs, or render Cesium tiles. Those belong
  to Parts 2–4.

## Container note

The selected Minimus Python 3.13 image is distroless and non-root at runtime. Minimus announced
that `reg.mini.dev` will shut down on **22 October 2026**, so the base image must be mirrored or
replaced before then. Do not put registry tokens in the Dockerfile.
