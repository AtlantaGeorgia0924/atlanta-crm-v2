import './App.css'

const importTargets = [
  ['Services/Billing', 'operational_billing_rows'],
  ['Stock/Inventory', 'operational_stock_rows'],
  ['Cash Flow', 'manual_expenses + related summary tables'],
  ['Contacts', 'clients'],
]

const modules = [
  'Authentication',
  'Inventory Management',
  'Service Management',
  'Debtors and Apply Payment',
  'Clients / Contacts',
  'Import Contacts from Sheet',
  'Cash Flow and Profit Calculation',
  'Manual Expenses',
  'Allowance Tracking',
  'Dashboard',
  'Refresh Workspace',
  'Sync to Google Sheets',
  'Settings / System Status',
]

function App() {
  return (
    <main className="app-shell">
      <section className="hero-card">
        <p className="eyebrow">Atlanta CRM v2 foundation</p>
        <h1>Clean architecture with Supabase at the center</h1>
        <p className="hero-copy">
          This rebuild starts from a brand-new Supabase project, imports legacy
          Google Sheets data once, and keeps every normal read and write inside
          Supabase.
        </p>
        <div className="pill-row" aria-label="system guarantees">
          <span className="pill pill-primary">Supabase = source of truth</span>
          <span className="pill">Google Sheets = import + manual sync only</span>
          <span className="pill">Heavy recalculations = async</span>
        </div>
      </section>

      <section className="grid two-column">
        <article className="panel">
          <h2>Delivery stack</h2>
          <dl className="definition-list">
            <div>
              <dt>Frontend</dt>
              <dd>React + Vite on Vercel</dd>
            </div>
            <div>
              <dt>Backend</dt>
              <dd>FastAPI on Render</dd>
            </div>
            <div>
              <dt>Database</dt>
              <dd>Supabase PostgreSQL</dd>
            </div>
            <div>
              <dt>Backup</dt>
              <dd>Google Sheets via manual sync only</dd>
            </div>
          </dl>
        </article>

        <article className="panel">
          <h2>Runtime rules</h2>
          <ul className="rule-list">
            <li>Refresh Workspace reloads directly from Supabase.</li>
            <li>No normal API endpoint calls Google Sheets.</li>
            <li>Cash Flow reads from precomputed summary tables.</li>
            <li>Apply Payment is designed for sub-second completion.</li>
          </ul>
        </article>
      </section>

      <section className="grid two-column">
        <article className="panel">
          <h2>Initial import mapping</h2>
          <div className="table">
            <div className="table-row table-head">
              <span>Sheet</span>
              <span>Supabase destination</span>
            </div>
            {importTargets.map(([sheet, target]) => (
              <div className="table-row" key={sheet}>
                <span>{sheet}</span>
                <span>{target}</span>
              </div>
            ))}
          </div>
          <p className="panel-note">All historical rows are preserved during import.</p>
        </article>

        <article className="panel">
          <h2>Core modules</h2>
          <ol className="module-list">
            {modules.map((module) => (
              <li key={module}>{module}</li>
            ))}
          </ol>
        </article>
      </section>
    </main>
  )
}

export default App
