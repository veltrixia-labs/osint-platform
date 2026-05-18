from pathlib import Path

p = Path(r"c:\RDTP project\Development\OSINT_analytics\web_dashboard\src\modules\render\context_briefs.ts")
text = p.read_text(encoding="utf-8")

start = text.find('            <div id="cb-context-modal-root"')
if start == -1:
    raise SystemExit("modal block start not found")

end_marker = "    panel.addEventListener('click', e => e.stopPropagation());\n}"
end = text.find(end_marker, start)
if end == -1:
    raise SystemExit("modal block end not found")
end += len(end_marker)

replacement = """        </motion>`;

    container.dataset.cbViewerTier = viewerTier;

    const onFeedClick = (e: Event) => {
        const btn = (e.target as HTMLElement).closest('.cb-open-context-btn');
        if (!btn || !container.contains(btn)) return;
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        openContextBriefModal(parseInt(btn.getAttribute('data-detail-index') || '-1', 10));
    };
    container.removeEventListener('click', onFeedClick, true);
    container.addEventListener('click', onFeedClick, true);
}"""

new_text = text[:start] + replacement + text[end:]
new_text = new_text.replace("        </motion>`;", "        </div>`;", 1)

p.write_text(new_text, encoding="utf-8")
print("patched ok")
