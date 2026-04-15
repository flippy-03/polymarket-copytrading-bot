export default function SettingsPage() {
  return (
    <div className="max-w-xl space-y-4">
      <h2 className="text-xl font-bold">Settings</h2>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        Copytrading strategies are configured from{" "}
        <code>src/strategies/common/config.py</code> and environment variables
        (<code>PAPER_MODE</code>, <code>BASKET_INITIAL_CAPITAL</code>,{" "}
        <code>SCALPER_INITIAL_CAPITAL</code>). No runtime settings are exposed here
        yet — edit the <code>.env</code> file and restart the daemons.
      </p>
    </div>
  );
}
