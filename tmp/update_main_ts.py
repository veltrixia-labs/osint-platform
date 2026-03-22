import re

file_path = "c:\\RDTP project\\Development\\OSINT_analytics\\web_dashboard\\src\\main.ts"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update renderTopicFilters
topic_filters_regex = re.compile(
    r"function renderTopicFilters\(container: HTMLElement, state: DashboardState\) \{.*?(?=function startFeedTab)",
    re.DOTALL
)

new_topic_filters = """function renderTopicFilters(container: HTMLElement, currentTopic: string | null) {
        container.innerHTML = '';
        const wrap = document.createElement('div');
        wrap.className = 'topic-filter-bar';
        wrap.style.display = 'flex';
        wrap.style.gap = '0.5rem';
        wrap.style.overflowX = 'auto';
        wrap.style.paddingBottom = '1rem';
        wrap.style.marginBottom = '1rem';
        wrap.style.borderBottom = '1px solid var(--border)';

        const allBtn = document.createElement('button');
        allBtn.className = `topic-btn ${currentTopic === null ? 'topic-btn--active' : ''}`;
        allBtn.textContent = 'All Topics';
        allBtn.onclick = () => startFeedTab(null);
        wrap.appendChild(allBtn);

        TOPICS.forEach(t => {
            const btn = document.createElement('button');
            const isRestricted = usage?.topics.restricted.includes(t.code);
            btn.className = `topic-btn ${currentTopic === t.code ? 'topic-btn--active' : ''} ${isRestricted ? 'topic-btn--locked' : ''}`;
            btn.innerHTML = `${t.label}${isRestricted ? ' 🔒' : ''}`;
            
            btn.onclick = () => {
                if (isRestricted) {
                    const alertsContainer = document.querySelector<HTMLDivElement>('#alerts-container');
                    if (alertsContainer) alertsContainer.innerHTML = renderLockedFeature(t.label, 'pro');
                    stopPolling();
                } else {
                    startFeedTab(t.code);
                }
            };
            wrap.appendChild(btn);
        });

        container.appendChild(wrap);
    }
    
    """

content = topic_filters_regex.sub(new_topic_filters, content)

# 2. Update startFeedTab
start_feed_regex = re.compile(
    r"function startFeedTab\(\) \{.*?(?=async function renderReportsTab)",
    re.DOTALL
)

new_start_feed = """function startFeedTab(topic: string | null = null) {
        stopPolling()
        if (!user) {
            alertsContainer.innerHTML = renderLockedFeature('Intelligence Dashboard', 'free');
            mainTitle.innerHTML = 'Analyst Intelligence'
            healthContainer.innerHTML = ''
            return;
        }

        const proBadgeHtml = user.tier === 'pro' ? '<span style="font-size: 0.9rem; margin-left:1rem; padding: 4px 12px; background: rgba(88,166,255,0.1); border: 1px solid rgba(88,166,255,0.3); color: #c9d1d9; border-radius: 20px; vertical-align:middle; box-shadow: 0 0 10px rgba(88,166,255,0.2);">💎 PRO: Full Access Active</span>' : '';
        mainTitle.innerHTML = `Dashboard ${proBadgeHtml}`;
        healthContainer.innerHTML = ''

        alertsContainer.innerHTML = `
            <div id="topic-filters-container"></div>
            <div id="featured-reports-container" style="display:flex; gap:1.5rem; margin-bottom:2rem; flex-wrap:wrap;"></div>
            <div id="topic-reports-grid" class="reports-grid" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1.5rem; margin-bottom:1rem;"></div>
            <h3 style="margin-top: 2rem; margin-bottom: 1rem; color: #c9d1d9; border-bottom: 1px solid #30363d; padding-bottom: 0.5rem;">Live Alert Stream</h3>
            <div id="feed-alerts-inner"><div style="color:#8b949e;text-align:center;padding:2rem;">Fetching Intelligence Feed...</div></div>
        `;

        const filtersContainer = alertsContainer.querySelector('#topic-filters-container') as HTMLElement;
        const featuredContainer = alertsContainer.querySelector('#featured-reports-container') as HTMLElement;
        const reportsGrid = alertsContainer.querySelector('#topic-reports-grid') as HTMLElement;
        const feedAlertsInner = alertsContainer.querySelector('#feed-alerts-inner') as HTMLElement;

        renderTopicFilters(filtersContainer, topic);

        // Fetch and render the static reports section
        import('./modules/api').then(async m => {
            try {
                const reports = await m.fetchReports(20, topic ? topic : undefined);
                let gridReports = reports;

                if (!topic) {
                    const latestPremium = reports.find((r: any) => r.is_premium);
                    const latestFree = reports.find((r: any) => !r.is_premium);
                    
                    if (latestPremium) {
                        featuredContainer.innerHTML += `
                            <div class="report-card report-card--premium" style="flex:1; min-width:300px; border: 2px solid var(--tier-pro);">
                                <div class="premium-lock-badge" style="margin-bottom:0.5rem; display:inline-block; font-size:0.75rem;">💎 Featured Premium Intelligence</div>
                                <h2 style="margin: 0 0 1rem 0; font-size: 1.4rem;">${latestPremium.content_markdown.split('\\n')[0].replace('# ', '')}</h2>
                                <div style="color:#8b949e; font-size:0.9rem; margin-bottom: 1.5rem;">Comprehensive analysis encompassing multiple verified events.</div>
                                <button class="btn-fb active view-report-btn" data-id="${latestPremium.id}">Unlock Full Analysis</button>
                            </div>
                        `;
                    }
                    if (latestFree) {
                        featuredContainer.innerHTML += `
                            <div class="report-card" style="flex:1; min-width:300px; border: 1px solid var(--tier-grace); background: rgba(255,255,255,0.03);">
                                <div class="role-badge" style="margin-bottom:0.5rem; display:inline-block; font-size:0.75rem; background:rgba(255,255,255,0.1);">🌍 Daily Free Briefing</div>
                                <h3 style="margin: 0 0 1rem 0; font-size: 1.25rem;">${latestFree.content_markdown.split('\\n')[0].replace('# ', '')}</h3>
                                <div style="color:#8b949e; font-size:0.9rem; margin-bottom: 1.5rem;">Publicly accessible strategic overview and risk analysis.</div>
                                <button class="btn-fb active view-report-btn" data-id="${latestFree.id}">Read Briefing</button>
                            </div>
                        `;
                    }
                    
                    // Filter featured ones out of the grid
                    gridReports = reports.filter((r: any) => r.id !== latestPremium?.id && r.id !== latestFree?.id);
                } else {
                    featuredContainer.style.display = 'none';
                }

                if (gridReports.length > 0) {
                    reportsGrid.innerHTML = gridReports.map((r: any) => `
                        <div class="report-card ${r.is_premium ? 'report-card--premium' : ''}" data-id="${r.id}">
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:1rem;">
                                <span class="report-topic-badge">${r.topic_code}</span>
                                ${r.is_premium ? '<span class="premium-lock-badge">🔒 Premium</span>' : ''}
                            </div>
                            <h3 style="margin: 0 0 1rem 0; font-size: 1.1rem;">${r.content_markdown.split('\\n')[0].replace('# ', '')}</h3>
                            <button class="btn-fb active view-report-btn" style="width:100%; margin-top: auto;" data-id="${r.id}">View Intelligence</button>
                        </div>
                    `).join('');
                } else if (topic) {
                    reportsGrid.innerHTML = '<div style="color:#8b949e; text-align:center; grid-column: 1 / -1; padding: 1rem 0;">No reports available for this topic yet. Generate one via alerts to see it here.</div>';
                }

                // Bind clicks for all generated reports
                alertsContainer.querySelectorAll('.view-report-btn').forEach(btn => {
                    btn.addEventListener('click', async (e) => {
                        const id = (e.currentTarget as HTMLElement).dataset.id!;
                        try {
                            const fullReport = await m.fetchReport(id);
                            renderReportDetail(fullReport, alertsContainer, async (actionType) => {
                                 if (actionType === 'upgrade') {
                                     try {
                                         const response = await m.fetchCheckoutSession('pro', id);
                                         if (response.url) window.location.href = response.url;
                                     } catch (err) {
                                         document.querySelector<HTMLElement>('#nav-plans')?.click();
                                     }
                                 }
                            });
                        } catch (err) {
                            alert("Failed to load report detail (Missing auth?): " + err);
                        }
                    });
                });
            } catch (err) {
                console.error("Dashboard reports error:", err);
            }
        });

        const state = new DashboardState()
        state.topic = topic; // So alert feed matches topic
        state.subscribe((s: DashboardState) => {
            if (feedAlertsInner) renderAlerts(s.alerts, feedAlertsInner)
            if (s.health) renderHealth(s.health, healthContainer)
            renderSidebar(s.analysts, sidebarContainer)
        })
        state.startPolling(5000)
        polling = state
    }
    
    """

content = start_feed_regex.sub(new_start_feed, content)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Updated {file_path}")
