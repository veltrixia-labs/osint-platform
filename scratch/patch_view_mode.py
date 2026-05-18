from pathlib import Path

p = Path(r"c:\RDTP project\Development\OSINT_analytics\web_dashboard\src\modules\render\context_briefs.ts")
text = p.read_text(encoding="utf-8")

old_fn = """function renderFreeEntityExposureList(
    entityState: { visible: ExposureRow[]; lockedCount: number },
    options?: { showTierNote?: boolean }
): string {
    let html = `<motion class="cb-compact-list cb-compact-list--entities">`;"""

old_fn = """function renderFreeEntityExposureList(
    entityState: { visible: ExposureRow[]; lockedCount: number },
    options?: { showTierNote?: boolean }
): string {
    let html = `<div class="cb-compact-list cb-compact-list--entities">`;
    entityState.visible.forEach((row: ExposureRow) => {
        html += renderExposureRowHtml(row, 'industry');
    });
    if (entityState.lockedCount > 0) {
        html += renderEntityLockTeaser(entityState.lockedCount);
    }
    html += `</div>`;
    if (options?.showTierNote && entityState.lockedCount > 0) {
        html += `<p class="cb-entity-tier-note">Full entity registry matches are available on Pro / Expert. Free access includes one primary match.</p>`;
    }
    return html;
}"""

new_fn = """function renderFreeEntityExposureList(
    entityState: { visible: ExposureRow[]; lockedCount: number },
    viewMode: ContextBriefViewMode
): string {
    const isDetail = viewMode === 'detail';
    let html = `<div class="cb-compact-list cb-compact-list--entities">`;
    entityState.visible.forEach((row: ExposureRow) => {
        html += renderExposureRowHtml(row, 'industry');
    });
    if (isDetail && entityState.lockedCount > 0) {
        html += renderEntityLockTeaser(entityState.lockedCount);
    }
    html += `</div>`;
    if (isDetail && entityState.lockedCount > 0) {
        html += `<p class="cb-entity-tier-note">Full entity registry matches are available on Pro / Expert. Free access includes one primary match.</p>`;
    }
    return html;
}"""

if old_fn not in text:
    raise SystemExit("renderFreeEntityExposureList block not found")
text = text.replace(old_fn, new_fn, 1)
text = text.replace("      ${entityPreview}\n", "")
p.write_text(text, encoding="utf-8")
print("patched")
