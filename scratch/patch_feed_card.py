from pathlib import Path

p = Path(r"c:\RDTP project\Development\OSINT_analytics\web_dashboard\src\modules\render\context_briefs.ts")
text = p.read_text(encoding="utf-8")

old = """function renderFeedCard(item: FreeAlertFeedItem, index: number): string {
    const cardId = `cb-card-${index}`;
    const triggeredStr = formatDate(item.triggered_at);
    const canonicalTopic = normalizeTopicCode(item.topic);
    const topicStr = getTopicDisplayLabel(canonicalTopic);
    const topicVars = getTopicCssVars(canonicalTopic);
    const newsCount = item.related_news_count ?? 0;
    const entitiesCount = item.related_entities_count ?? 0;
    const displayTitle = cleanBriefTitle(item.title || item.target_label || 'Strategic Intelligence Alert');
    const teaser = escapeHtml(extractTeaserFromMarkdown(item.content_markdown || ''));

    return `"""

new = """function renderFeedCard(item: FreeAlertFeedItem, index: number, viewerTier: string = 'free'): string {
    const cardId = `cb-card-${index}`;
    const triggeredStr = formatDate(item.triggered_at);
    const canonicalTopic = normalizeTopicCode(item.topic);
    const topicStr = getTopicDisplayLabel(canonicalTopic);
    const topicVars = getTopicCssVars(canonicalTopic);
    const newsCount = item.related_news_count ?? 0;
    const industryRows = companyImpactsToIndustryRows(item.company_impacts);
    const entityState = computeEntityDisplayState(
        industryRows,
        item.related_entities_count ?? 0,
        item.additional_pro_count ?? 0,
        isPaidContextTier(viewerTier)
    );
    const entitiesCount = entityState.total || item.related_entities_count ?? 0;
    const entityPreview = renderCardEntityPreview(item, viewerTier);
    const displayTitle = cleanBriefTitle(item.title || item.target_label || 'Strategic Intelligence Alert');
    const teaser = escapeHtml(extractTeaserFromMarkdown(item.content_markdown || ''));

    return `"""

if old not in text:
    raise SystemExit("renderFeedCard header not found")
text = text.replace(old, new, 1)

old2 = """      </motion>
      <div class="cb-brief-card-actions">"""

# exact match from file
old2 = """      </div>
      <motion class="cb-brief-card-actions">"""
old2 = """      </div>
      <div class="cb-brief-card-actions">"""

needle = """        <span class="cb-brief-stat-chip">🏢 ${entitiesCount} entities</span>
      </div>
      <div class="cb-brief-card-actions">"""

repl = """        <span class="cb-brief-stat-chip">🏢 ${entitiesCount} entities</span>
      </div>
      ${entityPreview}
      <div class="cb-brief-card-actions">"""

if needle not in text:
    raise SystemExit("stats/actions block not found")
text = text.replace(needle, repl, 1)

# keydown subscription
old_kd = """    modalBody.addEventListener('keydown', (e: KeyboardEvent) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const gate = (e.target as HTMLElement).closest('[data-cb-pro-gate]');"""

new_kd = """    modalBody.addEventListener('keydown', (e: KeyboardEvent) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const subCta = (e.target as HTMLElement).closest('[data-cb-subscription-cta]');
        if (subCta && modalBody.contains(subCta)) {
            e.preventDefault();
            e.stopPropagation();
            navigateToSubscription();
            closeModal();
            return;
        }
        const gate = (e.target as HTMLElement).closest('[data-cb-pro-gate]');"""

if old_kd not in text:
    raise SystemExit("keydown block not found")
text = text.replace(old_kd, new_kd, 1)

p.write_text(text, encoding="utf-8")
print("patched feed card + keydown")
