$content = Get-Content src\pages\MissionWorkspace.tsx -Raw
$pattern = '(?s)\{\/\* Scrolling Content Container \*\/\}.*'
$replacement = @'
{/* Tab Content Container */}
        <div className="flex-1 w-full min-w-0">
          {activeSection === 'overview' && (
            <motion.section
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className="mb-6 flex items-center gap-3 border-b border-dark-border overflow-hidden pb-4">
                <Activity className="text-dark-muted h-6 w-6" />
                <h3 className="text-2xl font-bold text-white">Overview</h3>
              </div>
              <MissionOverview
                mission={mission}
                scans={scans}
                missionTargets={missionTargets}
                onScanClick={(scanId) => {
                  setFindingsFilter({ ...DEFAULT_FILTER_STATE, selectedScanId: scanId });
                  scrollToSection('findings');
                }}
              />
            </motion.section>
          )}

          {activeSection === 'targets' && (
            <motion.section
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className="mb-6 flex items-center gap-3 border-b border-dark-border pb-4">
                <Server className="text-dark-muted h-6 w-6" />
                <h3 className="text-2xl font-bold text-white">Targets</h3>
              </div>
              <TargetsTab
                missionId={missionId}
                clientId={mission.client_id}
                missionTargets={missionTargets}
                clientTargets={clientTargets}
                onRefresh={fetchData}
                onSwitchTab={(tab) => scrollToSection(tab)}
                onSwitchToFindings={(scanId) => {
                  setFindingsFilter({ ...DEFAULT_FILTER_STATE, selectedScanId: scanId ?? 'all' });
                  scrollToSection('findings');
                }}
                isLocked={!!mission.is_locked}
                clientAdConfigured={client?.ad_configured ?? false}
                clientAdDomain={client?.ad_domain}
              />
            </motion.section>
          )}

          {activeSection === 'findings' && (
            <motion.section
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className="mb-6 flex items-center gap-3 border-b border-dark-border pb-4">
                <AlertTriangle className="text-dark-muted h-6 w-6" />
                <h3 className="text-2xl font-bold text-white">Findings & Scans</h3>
              </div>
              <MissionFindings
                scans={scans}
                isLocked={!!mission.is_locked}
                filterState={findingsFilter}
                onFilterChange={setFindingsFilter}
                onTotalCount={setFindingsCount}
              />
            </motion.section>
          )}

          {activeSection === 'reports' && (
            <motion.section
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className="mb-6 flex items-center gap-3 border-b border-dark-border pb-4">
                <BarChart3 className="text-dark-muted h-6 w-6" />
                <h3 className="text-2xl font-bold text-white">Reports</h3>
              </div>
              <MissionReports missionId={missionId} missionName={mission?.name} isLocked={!!mission.is_locked} />
            </motion.section>
          )}
        </div>
      </div>
    </div>
  );
}
