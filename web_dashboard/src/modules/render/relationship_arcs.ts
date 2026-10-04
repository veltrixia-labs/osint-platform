/**
 * Great-circle sampling + easing for the relationship Globe. PURE FUNCTIONS, ZERO IMPORTS.
 *
 * ★ WHAT THIS FILE USED TO CONTAIN, AND WHY IT NO LONGER DOES.
 *
 *   It held a hand-rolled `arc()` that sampled a great circle into ~48 [lng,lat] points, bowed
 *   them perpendicular to the chord, capped the bow at 9 degrees, and unwrapped longitudes across
 *   the antimeridian; plus `arcProgress()` for a progressive polyline draw. All of it existed to
 *   reproduce in 2-D GeoJSON what deck.gl's ArcLayer does in a shader. The Globe now uses the
 *   ArcLayer directly — greatCircle:true, getHeight 0.45, numSegments 64, exactly the legacy
 *   map's props (pro_interactive_map.ts:1094-1109) — so the shader owns the curve, the 3-D lift
 *   and the seam, and that code is deleted rather than kept as a second implementation.
 *
 *   Two problems went with it, and both were real: the bow had NO 2-D equivalent of getHeight
 *   (it had to be re-derived as a lateral displacement, and un-capped it sent a
 *   Rotterdam-Shanghai arc to 79 N), and `greatCircleAt` ends in atan2, so a Tokyo-LA polyline
 *   came back with a 360-degree jump through the middle of it. Neither is a problem the shader
 *   has. Handing the geometry back is a net deletion.
 *
 * WHAT REMAINS is the part deck.gl does not do for us: the comet particles need a position at a
 * parametric t along the arc, and that is `greatCircleAt`, ported verbatim from
 * pro_interactive_map.ts:1372-1393 — the same function the legacy map uses for the same purpose.
 */

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

/** Ease-out cubic: fast departure, settled arrival. */
export const easeOutCubic = (t: number): number => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);
