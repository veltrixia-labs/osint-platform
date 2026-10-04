/**
 * Arc geometry + easing for the relationship Globe. PURE FUNCTIONS, ZERO IMPORTS.
 *
 * ★ WHAT WAS AND WAS NOT PORTED FROM THE LEGACY PRO MAP — read before "restoring" something.
 *
 *   The legacy map does NOT contain an arc generator. Its arcs are deck.gl `ArcLayer`
 *   instances with `greatCircle: true`, `getHeight: 0.45`, `numSegments: 64`
 *   (pro_interactive_map.ts:1094-1109, and buildUnquantifiedArcLayer at :501-519). The curve is
 *   tessellated in a GPU shader; there is no JS point loop and no polyline to copy.
 *
 *   `greatCircleAt()` below IS a verbatim port — pro_interactive_map.ts:1372-1393. In the legacy
 *   map it does NOT build the line: it places the comet PARTICLES that ride on top of the
 *   shader-drawn arc, and its own comment says so ("matches Deck.gl's ArcLayer so particles ride
 *   exactly on top of the rendered arc geometry"). Reusing it here means our polyline and the
 *   legacy arcs are the same curve, sampled in JS instead of in a shader.
 *
 *   The LIFT had to be re-derived, not ported. deck.gl's `getHeight` raises the arc off the
 *   ground in 3-D; a GeoJSON LineString on a 2-D map has no third axis, so the bow here is a
 *   LATERAL displacement perpendicular to the chord — the same degree-space perpendicular math
 *   as the legacy `applyArcLaneOffset()` (:259-280), but scaled by `sin(pi*t)` so it peaks at the
 *   midpoint instead of shifting the whole chord sideways into a parallel lane. Note also that
 *   the legacy lift is NOT distance-proportional: it is the constant 0.45, or
 *   `0.40 + |lane_offset| * 0.22` (:3055, :3193-3194) where lane_offset is the domain's lane and
 *   is 0 outside the multi-domain aggregate view. Distance-proportional bowing is new here.
 */

/** Points per arc. 48 is enough that the bow reads as smooth at any zoom this view allows. */
export const ARC_POINTS = 48;

/**
 * Bow amplitude is `LIFT * chord-degrees`, CAPPED at MAX_BOW_DEG.
 *
 * ★ The cap is not a tidy-up, it is load-bearing. Un-capped at the first value tried (0.18), a
 *   Rotterdam-Shanghai arc (chord 119 degrees) bowed to 79 N — past the top of the Mercator
 *   viewport and far enough north to read as a route over the pole, which is a geographic claim
 *   this view has no business making. The great circle ALREADY carries the real curvature; the
 *   lift only needs to separate overlapping arcs so a fan of edges from one node is legible.
 *   With the cap, the bow adds at most 9 degrees of latitude at the midpoint.
 */
export const LIFT = 0.10;
export const MAX_BOW_DEG = 9;

/**
 * Project a point at parametric `t` (0..1) along the great-circle arc between two lng/lat
 * positions, by spherical linear interpolation.
 *
 * ★ Ported verbatim from pro_interactive_map.ts:1372-1393. Unchanged apart from this comment.
 */
export function greatCircleAt(
    srcLon: number, srcLat: number,
    tgtLon: number, tgtLat: number,
    t: number,
): [number, number] {
    const lat1 = (srcLat * Math.PI) / 180;
    const lon1 = (srcLon * Math.PI) / 180;
    const lat2 = (tgtLat * Math.PI) / 180;
    const lon2 = (tgtLon * Math.PI) / 180;
    const d = 2 * Math.asin(Math.sqrt(
        Math.sin((lat2 - lat1) / 2) ** 2 +
        Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2,
    ));
    if (!isFinite(d) || d === 0) return [srcLon, srcLat];
    const A = Math.sin((1 - t) * d) / Math.sin(d);
    const B = Math.sin(t * d) / Math.sin(d);
    const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
    const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);
    const lat = (Math.atan2(z, Math.sqrt(x * x + y * y)) * 180) / Math.PI;
    const lon = (Math.atan2(y, x) * 180) / Math.PI;
    return [lon, lat];
}

/**
 * Great-circle arc from `from` to `to` as ~`points` [lng,lat] pairs, bowed perpendicular to the
 * chord by `lift` x chord-length x sin(pi*t).
 *
 * ★ ANTIMERIDIAN. greatCircleAt ends in `Math.atan2`, so every longitude it returns is in
 *   (-180, 180]. A path from Tokyo to Los Angeles therefore comes back as a sequence that JUMPS
 *   by ~360 degrees mid-array, and a GeoJSON LineString built from it draws a horizontal scar
 *   across the whole map. The legacy code never hit this because it never built a LineString —
 *   deck.gl's shader handles the seam itself. We UNWRAP instead of splitting: each longitude is
 *   shifted by whole turns of 360 until it is within 180 degrees of its predecessor, which
 *   yields one continuous polyline whose longitudes may legitimately sit outside [-180, 180].
 *   MapLibre renders that correctly and the seam disappears. Unwrapping happens BEFORE the bow,
 *   so the chord used for the perpendicular is the unwrapped one.
 *
 * The bow is forced toward +latitude ("upward on screen") rather than following the sign of the
 * chord's perpendicular, so that an east-to-west arc and its west-to-east twin bow the same way
 * instead of mirroring into a lens.
 */
export function arc(
    from: [number, number],
    to: [number, number],
    lift = LIFT,
    points = ARC_POINTS,
): [number, number][] {
    const n = Math.max(2, points | 0);
    const [lon1, lat1] = from;
    const [lon2, lat2] = to;
    if (!Number.isFinite(lon1) || !Number.isFinite(lat1) || !Number.isFinite(lon2) || !Number.isFinite(lat2)) {
        return [];
    }

    // 1. Sample the great circle, unwrapping longitudes as we go.
    const pts: [number, number][] = [];
    let prevLon = lon1;
    for (let i = 0; i < n; i++) {
        const t = i / (n - 1);
        const [lo, la] = greatCircleAt(lon1, lat1, lon2, lat2, t);
        let lon = lo;
        while (lon - prevLon > 180) lon -= 360;
        while (lon - prevLon < -180) lon += 360;
        prevLon = lon;
        pts.push([lon, la]);
    }

    if (!lift) return pts;

    // 2. Perpendicular to the UNWRAPPED chord, in degree space — applyArcLaneOffset's math.
    const dLon = pts[n - 1][0] - pts[0][0];
    const dLat = pts[n - 1][1] - pts[0][1];
    const len = Math.hypot(dLon, dLat);
    if (!len) return pts;
    let pLon = -dLat / len;
    let pLat = dLon / len;
    if (pLat < 0) { pLon = -pLon; pLat = -pLat; }   // always bow upward
    const amp = Math.min(lift * len, MAX_BOW_DEG);   // proportional to distance, then capped

    for (let i = 0; i < n; i++) {
        const t = i / (n - 1);
        const k = Math.sin(Math.PI * t) * amp;
        pts[i] = [pts[i][0] + pLon * k, Math.max(-85, Math.min(85, pts[i][1] + pLat * k))];
    }
    return pts;
}

/**
 * The first `frac` of an arc, for a progressive draw-on. Always returns at least two points once
 * frac > 0 — a one-point LineString is invalid GeoJSON and MapLibre drops the whole feature, so
 * an un-clamped slice makes the first frames of the animation silently empty.
 */
export function arcProgress(pts: [number, number][], frac: number): [number, number][] {
    if (pts.length < 2) return pts;
    if (frac >= 1) return pts;
    if (frac <= 0) return [];
    const keep = Math.max(2, Math.ceil(frac * pts.length));
    return pts.slice(0, Math.min(pts.length, keep));
}

/** Ease-out cubic: fast departure, settled arrival. */
export const easeOutCubic = (t: number): number => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);
