/**
 * UTF-8 mojibake repair for API JSON (structured_payload, titles, etc.).
 */

/** Repair UTF-8 mojibake (UTF-8 bytes misread as Latin-1). */
export function repairUtf8Mojibake(value: string): string {
    if (!value) return value;
    if (!/[\u0080-\u00ff]|â|Ã|æ|œ|å|…/.test(value)) return value;
    try {
        const bytes = new Uint8Array([...value].map((ch) => ch.charCodeAt(0) & 0xff));
        const repaired = new TextDecoder('utf-8').decode(bytes);
        return repaired !== value ? repairUtf8Mojibake(repaired) : repaired;
    } catch {
        return value;
    }
}

/** Recursively repair strings in API JSON trees. */
export function sanitizeUnicodeTree<T>(data: T): T {
    if (typeof data === 'string') return repairUtf8Mojibake(data) as T;
    if (Array.isArray(data)) return data.map((v) => sanitizeUnicodeTree(v)) as T;
    if (data && typeof data === 'object') {
        const out: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
            out[k] = sanitizeUnicodeTree(v);
        }
        return out as T;
    }
    return data;
}

/** Parse JSON as UTF-8 and repair common mojibake in string fields. */
export async function parseApiJson<T>(resp: Response): Promise<T> {
    const text = await resp.text();
    const parsed = JSON.parse(text) as T;
    return sanitizeUnicodeTree(parsed);
}
