from pathlib import Path

p = Path(r"c:\RDTP project\Development\OSINT_analytics\web_dashboard\src\modules\render\context_briefs.ts")
text = p.read_text(encoding="utf-8")

old_block_start = text.find(
    "            const paid = isPaidContextTier(viewerTier);\n            const showProGate"
)
old_block_end = text.find(
    "        }\n        else if (lowerTitle.includes('coverage'))",
    old_block_start,
)
if old_block_start < 0 or old_block_end < 0:
    raise SystemExit(f"block bounds not found {old_block_start} {old_block_end}")

new_block = """            const paid = isPaidContextTier(viewerTier);
            const entityState = computeEntityDisplayState(
                industryRows,
                relatedEntitiesCount,
                additionalProCount,
                paid
            );

            if (usable.length > 0 || entityState.total > 0) {
                html += `<div class="cb-exposure-single">`;
                html += `<p class="cb-exposure-kicker">Affected segments</p>`;
                html += `<h5 class="cb-exposure-subtitle">Industry &amp; Assets</h5>`;
                if (industryRows.length > 0 || entityState.lockedCount > 0) {
                    if (paid) {
                        html += renderIndustryExpandableList(industryRows);
                    } else {
                        html += renderFreeEntityExposureList(entityState, { showTierNote: true });
                    }
                } else {
                    html += `<div class="cb-muted-text cb-exposure-empty">No industry or asset matches.</div>`;
                }
                html += `</div>`;
            } else {
                html += `<motion class="cb-muted-text">No related companies or infrastructure matched this alert.</div>`;
            }
"""

new_block = new_block.replace(
    '<motion class="cb-muted-text">',
    '<div class="cb-muted-text">',
)

text = text[:old_block_start] + new_block + text[old_block_end:]
p.write_text(text, encoding="utf-8")
print("patched companies section")
