'use client'

import { useEffect, useState } from 'react'
import {
  BookOpen,
  Calculator,
  Cpu,
  ExternalLink,
  Layers,
  ScrollText,
  ShieldCheck,
  X,
  Clock,
  Database,
  AlertTriangle,
  GitBranch,
  TrendingDown,
} from 'lucide-react'

interface MethodologyModalProps {
  open: boolean
  onClose: () => void
}

type TabKey = 'architecture' | 'ml' | 'economics' | 'citations'

export function MethodologyModal({ open, onClose }: MethodologyModalProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('architecture')

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-md sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-border-strong bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex h-11 shrink-0 items-center justify-between border-b border-border-strong bg-panel px-4 font-mono">
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-accent" />
            <span className="text-[12px] font-semibold uppercase tracking-widest text-foreground">
              System Methodology & Technical Documentation
            </span>
            <span className="rounded-[3px] border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[9px] font-mono font-bold text-accent">
              v2.4-PROD
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex items-center gap-1.5 text-[11px] text-dim transition-colors hover:text-foreground"
          >
            <kbd className="rounded border border-border bg-surface px-1.5 py-0.5 text-[9px] font-mono">ESC</kbd>
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex shrink-0 border-b border-border bg-surface/50 text-[11px] font-mono uppercase">
          <TabButton
            active={activeTab === 'architecture'}
            onClick={() => setActiveTab('architecture')}
            icon={<Layers className="h-3.5 w-3.5" />}
            label="01. Architecture & ASOF ETL"
          />
          <TabButton
            active={activeTab === 'ml'}
            onClick={() => setActiveTab('ml')}
            icon={<Cpu className="h-3.5 w-3.5" />}
            label="02. Two-Stage Hurdle ML"
          />
          <TabButton
            active={activeTab === 'economics'}
            onClick={() => setActiveTab('economics')}
            icon={<Calculator className="h-3.5 w-3.5" />}
            label="03. Friction & Dead-Zone Math"
          />
          <TabButton
            active={activeTab === 'citations'}
            onClick={() => setActiveTab('citations')}
            icon={<ScrollText className="h-3.5 w-3.5" />}
            label="04. Citations & Bibliography"
          />
        </div>

        {/* Content Body */}
        <div className="min-h-0 flex-1 overflow-y-auto p-6 font-sans text-[13px] leading-relaxed text-foreground/90">
          {activeTab === 'architecture' && <ArchitectureTab />}
          {activeTab === 'ml' && <MachineLearningTab />}
          {activeTab === 'economics' && <EconomicsTab />}
          {activeTab === 'citations' && <CitationsTab />}
        </div>

        {/* Status Footer */}
        <div className="flex h-8 shrink-0 items-center justify-between border-t border-border-strong bg-panel px-4 font-mono text-[10px] uppercase text-dim">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full led-up" />
            <span>IEEE 754-2019 Banker&apos;s Rounding Active</span>
          </span>
          <span>DuckDB Vectorized OLAP Engine · Pure Chronological 14D Embargo</span>
        </div>
      </div>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-2 border-r border-border px-4 py-2.5 font-medium transition-colors ${
        active
          ? 'border-b-2 border-b-accent bg-surface font-semibold text-accent'
          : 'text-dim hover:bg-surface-2 hover:text-foreground'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}

function ArchitectureTab() {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-mono text-[13px] font-bold uppercase tracking-wider text-accent">
          01. Vectorized OLAP Processing & Temporal ASOF Windowing
        </h3>
        <p className="mt-1.5 text-muted-foreground text-[13px] leading-normal">
          Market price quotes from different vendors arrive at different times. Joining these timestamps with standard SQL joins introduces lookahead bias by accidentally pairing historical quotes with future retail prices.
        </p>
      </div>

      {/* Timeline Alignment */}
      <div className="rounded-md border border-border bg-surface-2/40 p-4">
        <div className="flex items-center justify-between border-b border-border/60 pb-2 font-mono text-[10px] font-bold uppercase text-dim">
          <span className="flex items-center gap-1.5 text-accent">
            <Clock className="h-3.5 w-3.5" />
            <span>Lookahead-Safe Price Matching (ASOF Join)</span>
          </span>
          <span>MAX LOOKBACK: &le; 3 DAYS</span>
        </div>

        <div className="my-3 overflow-x-auto rounded bg-background p-3.5">
          <div className="min-w-[580px] font-mono text-[11px]">
            <div className="flex items-center justify-between text-[10px] text-dim mb-1.5">
              <span>t - 3d</span>
              <span>t - 2d</span>
              <span>t - 1d</span>
              <span className="text-accent font-bold">t_quote (NOW)</span>
            </div>
            
            <div className="relative h-7 w-full rounded bg-surface-3 flex items-center px-2">
              <div className="absolute left-[20%] h-3 w-3 rounded-full bg-muted-foreground" title="Old Retail Price (Ignored)" />
              <div className="absolute left-[65%] h-3.5 w-3.5 rounded-full border-2 border-accent bg-accent/20" title="t_preceding (Matched)" />
              <div className="absolute right-2 h-3.5 w-3.5 rounded-full bg-up" title="t_quote (Buylist Offer)" />
              
              <div className="absolute left-[66%] right-3 top-1/2 -translate-y-1/2 border-t-2 border-dashed border-accent flex items-center justify-center">
                <span className="bg-background px-1.5 text-[9.5px] text-accent font-mono font-bold">&larr; ASOF JOIN &larr;</span>
              </div>
            </div>

            <div className="flex items-center justify-between text-[10px] mt-2">
              <span className="text-dim">Retail Price (Outdated)</span>
              <span className="text-accent font-medium">&bull; Nearest Preceding Price (t_preceding)</span>
              <span className="text-up font-medium">&bull; Target Buylist Quote (t_quote)</span>
            </div>
          </div>
        </div>

        <div className="rounded border border-accent/30 bg-accent/5 p-3.5">
          <div className="font-mono text-[10px] font-bold uppercase tracking-wider text-accent mb-1.5">
            Mathematical Formulation
          </div>
          <div className="font-mono text-[13px] font-semibold text-foreground bg-background/90 p-3 rounded border border-border text-center">
            max(t<sub>preceding</sub>) &emsp; s.t. &emsp; t<sub>preceding</sub> &le; t<sub>quote</sub> &emsp; &and; &emsp; (t<sub>quote</sub> &minus; t<sub>preceding</sub>) &le; 3 DAYS
          </div>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-3 text-[11px]">
          <div className="rounded border border-border bg-surface p-2.5">
            <span className="font-mono font-bold text-accent">t_quote</span>
            <p className="text-muted-foreground mt-0.5 text-[12px] leading-snug">Card Kingdom buylist quote timestamp.</p>
          </div>
          <div className="rounded border border-border bg-surface p-2.5">
            <span className="font-mono font-bold text-accent">t_preceding</span>
            <p className="text-muted-foreground mt-0.5 text-[12px] leading-snug">Nearest preceding TCGplayer retail price.</p>
          </div>
          <div className="rounded border border-border bg-surface p-2.5">
            <span className="font-mono font-bold text-accent">RANGE INTERVAL</span>
            <p className="text-muted-foreground mt-0.5 text-[12px] leading-snug">
              Rolling window: <code className="font-mono text-forecast">6 DAYS PRECEDING</code>.
            </p>
          </div>
        </div>
      </div>

      {/* Ingestion Specs */}
      <div className="rounded-md border border-border bg-surface-2/40 p-4">
        <div className="flex items-center justify-between">
          <h4 className="font-sans font-semibold text-foreground flex items-center gap-1.5 text-[13px]">
            <Database className="h-4 w-4 text-accent" />
            <span>Memory-Safe Streaming Ingestion</span>
          </h4>
          <span className="rounded bg-up/10 px-2 py-0.5 font-mono text-[9.5px] font-bold text-up border border-up/30">
            RAM &lt; 150MB
          </span>
        </div>
        <p className="mt-1.5 text-muted-foreground text-[12.5px] leading-relaxed">
          Raw price exports exceed 1.2GB uncompressed. The pipeline streams records incrementally using Python&apos;s <code className="font-mono font-semibold text-accent">ijson.kvitems</code>, batching 50,000 records per transaction into DuckDB columnar tables without loading the entire JSON file into memory.
        </p>
      </div>
    </div>
  )
}

function MachineLearningTab() {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-mono text-[13px] font-bold uppercase tracking-wider text-accent">
          02. Handling Zero-Inflation with Two-Stage Hurdle Modeling
        </h3>
        <p className="mt-1.5 text-muted-foreground text-[13px] leading-normal">
          Over 70% of cards experience zero price change over a 7-day window. Standard regression models try to fit small fractional noise (&plusmn;0.15%), degrading accuracy on assets that never actually moved.
        </p>
      </div>

      {/* Decision Flow */}
      <div className="rounded-md border border-border bg-surface-2/40 p-4">
        <div className="font-mono text-[10px] font-bold uppercase text-dim mb-3 flex items-center gap-1.5">
          <GitBranch className="h-3.5 w-3.5 text-accent" />
          <span>Inference Pipeline & Confidence Gate (&tau; = 0.89)</span>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="rounded border border-border bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-up text-[12px]">Stage 1: Breakout Classifier</span>
              <span className="font-mono text-[10px] text-dim">XGBClassifier</span>
            </div>
            <p className="mt-1 text-[11.5px] text-muted-foreground">
              Predicts probability of clearing the &plusmn;4.50% volatility threshold:
            </p>
            <div className="my-2 rounded bg-background p-2 font-mono text-[11.5px] font-bold text-accent border border-border text-center">
              P(|Return<sub>7d</sub>| &ge; 4.50% | X)
            </div>
            <div className="font-mono text-[10px] text-dim">
              Trained with weighted log-loss (<code className="text-foreground font-semibold">scale_pos_weight</code>).
            </div>
          </div>

          <div className="rounded border border-border bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-forecast text-[12px]">Stage 2: Magnitude Regressor</span>
              <span className="font-mono text-[10px] text-dim">XGBRegressor</span>
            </div>
            <p className="mt-1 text-[11.5px] text-muted-foreground">
              Estimates return magnitude only for predicted movers:
            </p>
            <div className="my-2 rounded bg-background p-2 font-mono text-[11.5px] font-bold text-accent border border-border text-center">
              E[Return<sub>7d</sub> | |Return<sub>7d</sub>| &ge; 4.50%, X]
            </div>
            <div className="font-mono text-[10px] text-dim">
              Optimized with L1 loss (<code className="text-foreground font-semibold">reg:absoluteerror</code>).
            </div>
          </div>
        </div>

        <div className="mt-3.5 rounded border border-warn/30 bg-warn/5 p-3.5">
          <div className="flex items-center justify-between font-mono text-[11px]">
            <span className="font-bold text-warn flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5" />
              <span>Decision Gate: &tau; = 0.89 Calibration</span>
            </span>
            <span className="text-[9.5px] text-dim">14-DAY CALENDAR EMBARGO</span>
          </div>
          <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">
            If model confidence in a price move is below <code className="font-mono font-semibold text-foreground">89%</code>, the output defaults to <code className="font-mono font-bold text-accent">0.00%</code>. This eliminates unprofitable low-conviction trades while preserving <strong className="text-foreground font-semibold">66.65% directional accuracy</strong> on active movers.
          </p>
        </div>
      </div>

      {/* Model Benchmark Grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-center font-mono">
        <div className="rounded border border-border bg-surface p-2.5">
          <div className="text-[9.5px] uppercase text-dim">Model MAE</div>
          <div className="text-[14px] font-bold text-accent mt-0.5">4.0236%</div>
        </div>
        <div className="rounded border border-border bg-surface p-2.5">
          <div className="text-[9.5px] uppercase text-dim">Naive Baseline</div>
          <div className="text-[14px] font-bold text-muted-foreground mt-0.5">4.0389%</div>
        </div>
        <div className="rounded border border-border bg-surface p-2.5">
          <div className="text-[9.5px] uppercase text-dim">Directional Acc.</div>
          <div className="text-[14px] font-bold text-up mt-0.5">66.65%</div>
        </div>
        <div className="rounded border border-border bg-surface p-2.5">
          <div className="text-[9.5px] uppercase text-dim">Out-of-Time Test</div>
          <div className="text-[14px] font-bold text-foreground mt-0.5">476,539</div>
        </div>
      </div>
    </div>
  )
}

function EconomicsTab() {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-mono text-[13px] font-bold uppercase tracking-wider text-accent">
          03. Tiered Fee Schedules & Dead-Zone Price Clamping
        </h3>
        <p className="mt-1.5 text-muted-foreground text-[13px] leading-normal">
          Calculates net take-home profit by accounting for tiered marketplace commission fees, payment processing, shipping costs, and physical grading downgrade risk.
        </p>
      </div>

      {/* Fee Table */}
      <div className="rounded-md border border-border bg-surface-2/40 p-4">
        <h4 className="font-semibold text-foreground text-[12px] mb-2 font-mono">TCGplayer Direct Net Payout Schedule</h4>
        <div className="divide-y divide-border/60 rounded border border-border bg-surface font-mono text-[11px]">
          <div className="flex items-center justify-between p-2.5">
            <span className="text-dim">P &lt; $0.40</span>
            <span className="font-semibold text-down">Payout = $0.00 (Ineligible)</span>
          </div>
          <div className="flex items-center justify-between p-2.5">
            <span className="text-dim">$0.40 &le; P &lt; $2.50</span>
            <span className="font-semibold text-foreground">Payout = 0.50 &times; P</span>
          </div>
          <div className="flex items-center justify-between p-2.5">
            <span className="text-dim">P &ge; $2.50</span>
            <span className="font-semibold text-accent">Payout = P &minus; $1.12 &minus; min(8.95%&times;P, $75) &minus; 2.5%&times;P&times;(1+tax)</span>
          </div>
        </div>
      </div>

      {/* Dead-Zone Cliff Card */}
      <div className="rounded-md border border-warn/40 bg-warn/5 p-4 text-[12px]">
        <div className="flex items-center justify-between font-mono">
          <h4 className="font-semibold text-warn flex items-center gap-1.5 text-[12px]">
            <TrendingDown className="h-4 w-4" />
            <span>The [$2.50, $2.67] Fee Cliff</span>
          </h4>
          <span className="rounded bg-warn/15 px-1.5 py-0.5 text-[9px] font-bold text-warn border border-warn/30">
            AUTO-CLAMP: $2.49
          </span>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2.5 text-center font-mono">
          <div className="rounded border border-up/30 bg-up/10 p-2.5">
            <div className="text-[9.5px] uppercase text-dim">List at $2.49 (50% Tier)</div>
            <div className="text-[13px] font-bold text-up mt-0.5">Net Payout: $1.25</div>
          </div>
          <div className="rounded border border-down/30 bg-down/10 p-2.5">
            <div className="text-[9.5px] uppercase text-dim">List at $2.50 (Step-Up Tier)</div>
            <div className="text-[13px] font-bold text-down mt-0.5">Net Payout: $1.09</div>
          </div>
        </div>

        <p className="mt-3 text-muted-foreground text-[12px] leading-relaxed">
          Raising the listing price from $2.49 to $2.50 triggers a fixed $1.12 direct fee, causing an immediate <strong className="text-down font-semibold">-$0.15 drop</strong> in net payout. The engine automatically clamps target prices between [$2.50, $2.67] down to <strong className="text-foreground font-semibold">$2.49</strong> to maximize realized profit.
        </p>
      </div>

      {/* Grading Haircut */}
      <div className="rounded-md border border-border bg-surface-2/40 p-4">
        <h4 className="font-semibold text-foreground text-[12px] font-mono">Condition Risk Haircut (&kappa;_risk)</h4>
        <p className="mt-1 text-muted-foreground text-[12px] leading-normal">
          Models physical authentication inspection: 3.5% Near Mint &rarr; Lightly Played downgrade rate (&delta;), 0.5% rejection rate (&phi;), and 75% inventory salvage recovery:
        </p>
        <div className="my-2.5 rounded bg-background p-3 font-mono text-[12px] font-bold text-accent border border-border text-center">
          &kappa;<sub>risk</sub> = 1 &minus; [ &delta; &times; ((max(P<sub>direct</sub>, P<sub>mkt50</sub>) &minus; 0.75 C<sub>acq</sub>) / P<sub>direct</sub>) + &phi; ]
        </div>
      </div>
    </div>
  )
}

function CitationsTab() {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-mono text-[13px] font-bold uppercase tracking-wider text-accent">
          04. Academic Literature & Official Platform Citations
        </h3>
        <p className="mt-1.5 text-muted-foreground text-[13px] leading-normal">
          Primary econometric literature and platform documentation supporting the terminal architecture.
        </p>
      </div>

      <div className="space-y-2.5">
        <CitationCard
          title="Some Statistical Models for Econometric Data with More than One Observation at Zero"
          authors="Cragg, J. G. (1971)"
          venue="Econometrica: Journal of the Econometric Society, 39(5), 829-844"
          doi="10.2307/1909582"
          href="https://doi.org/10.2307/1909582"
          description="Foundational formulation of the Two-Stage Hurdle Model for zero-inflated continuous distributions."
        />

        <CitationCard
          title="Advances in Financial Machine Learning"
          authors="López de Prado, Marcos (2018)"
          venue="John Wiley & Sons, ISBN: 978-1-119-48208-6"
          href="https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086"
          description="Principles for chronological embargoes and purged cross-validation to prevent label leakage in financial time series."
        />

        <CitationCard
          title="DuckDB: an Embeddable Analytical Database"
          authors="Raasveldt, M., & Mühleisen, H. (2019)"
          venue="Proceedings of the ACM SIGMOD International Conference on Management of Data, 1981-1984"
          doi="10.1145/3299869.3320212"
          href="https://doi.org/10.1145/3299869.3320212"
          description="Vectorized columnar execution engine enabling sub-100ms temporal ASOF joins and SQL windowing."
        />

        <CitationCard
          title="IEEE Standard for Floating-Point Arithmetic (IEEE Std 754-2019)"
          authors="IEEE Computer Society (2019)"
          venue="IEEE Standards Association, DOI: 10.1109/IEEESTD.2019.8766229"
          doi="10.1109/IEEESTD.2019.8766229"
          href="https://doi.org/10.1109/IEEESTD.2019.8766229"
          description="Specification of ROUND_HALF_EVEN (Banker's Rounding) to eliminate cumulative ledger drift."
        />
      </div>

      <div className="border-t border-border pt-3.5">
        <h4 className="mb-2 font-mono text-[10.5px] font-semibold uppercase text-dim">Primary Platform Rate Card Citations</h4>
        <ul className="space-y-2 text-[11.5px] text-muted-foreground">
          <li>
            <a
              href="https://help.tcgplayer.com/hc/en-us/articles/201357836-TCGplayer-Fees"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 transition-colors hover:text-accent"
            >
              <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-accent" />
              <span>TCGplayer Marketplace &amp; Pro Fee Schedule (Seller Help Center, 2026)</span>
              <ExternalLink className="h-3 w-3 text-dim" />
            </a>
          </li>
          <li>
            <a
              href="https://help.tcgplayer.com/hc/en-us/articles/234771747-TCGplayer-Direct-Direct-Fee"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 transition-colors hover:text-accent"
            >
              <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-accent" />
              <span>TCGplayer Direct &amp; Store Your Products (SYP) Guidelines (Louisville Operations, 2026)</span>
              <ExternalLink className="h-3 w-3 text-dim" />
            </a>
          </li>
        </ul>
      </div>
    </div>
  )
}

function CitationCard({
  title,
  authors,
  venue,
  doi,
  href,
  description,
}: {
  title: string
  authors: string
  venue: string
  doi?: string
  href?: string
  description: string
}) {
  const targetUrl = href ?? (doi ? `https://doi.org/${doi}` : undefined)

  return (
    <a
      href={targetUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="group block rounded-md border border-border bg-surface-2/30 p-3 transition-colors hover:border-accent/50 hover:bg-surface-2/60"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-sans font-semibold text-foreground text-[12.5px] transition-colors group-hover:text-accent">
          {title}
        </span>
        <div className="flex shrink-0 items-center gap-1.5 font-mono">
          {doi && (
            <span className="rounded bg-background px-1.5 py-0.5 text-[9px] text-dim transition-colors group-hover:text-foreground">
              DOI: {doi}
            </span>
          )}
          <ExternalLink className="h-3.5 w-3.5 text-dim transition-colors group-hover:text-accent" />
        </div>
      </div>
      <div className="mt-1 font-mono text-[11px] text-accent">
        {authors} &middot; <span className="text-dim">{venue}</span>
      </div>
      <p className="mt-1.5 font-sans text-[11.5px] text-muted-foreground leading-relaxed">{description}</p>
    </a>
  )
}