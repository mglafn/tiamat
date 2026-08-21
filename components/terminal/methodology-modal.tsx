"use client"

import { useEffect, useState } from "react"
import {
  BookOpen,
  X,
  Cpu,
  ShieldCheck,
  Scale,
  Layers,
  TrendingUp,
  Database,
  DollarSign,
} from "lucide-react"

interface MethodologyModalProps {
  open: boolean
  onClose: () => void
}

type TabKey = "architecture" | "hurdle" | "cqr" | "kelly" | "economics" | "duckdb"

export function MethodologyModal({ open, onClose }: MethodologyModalProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("architecture")

  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [open, onClose])

  if (!open) return null

  return (
    // 1. Toned-down backdrop opacity (0.68) with a soft 6px blur
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        backgroundColor: "rgba(5, 8, 12, 0.68)",
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        zoom: 1.3,
      }}
      onClick={onClose}
      role="presentation"
    >
      {/* 2. Scaled up proportionally to 920px with matching typography and spacing */}
      <div
        style={{
          height: "800",
          width: "1120px",
          maxWidth: "94vw",
          maxHeight: "88vh",
          backgroundColor: "var(--surface, #181d28)",
          color: "var(--foreground, #e8eaed)",
          fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          borderRadius: "14px",
          border: "1px solid var(--border-strong, #323c4d)",
          boxShadow: "0 30px 60px -15px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.05)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "20px 24px",
            borderBottom: "1px solid var(--border-strong, #323c4d)",
            backgroundColor: "var(--panel, #141822)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "14px", flex: 1, minWidth: 0 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "42px",
                height: "42px",
                borderRadius: "10px",
                backgroundColor: "rgba(74, 222, 128, 0.12)",
                color: "var(--accent, #4ade80)",
                border: "1px solid rgba(74, 222, 128, 0.25)",
                flexShrink: 0,
              }}
            >
              <BookOpen size={20} />
            </div>
            <div style={{ minWidth: 0 }}>
              <h2 style={{ fontSize: "16px", fontWeight: 700, margin: 0, color: "var(--foreground, #fff)", letterSpacing: "-0.01em" }}>
                System Methodology & Mathematical Grounding
              </h2>
              <p style={{ fontSize: "13px", margin: "3px 0 0 0", color: "var(--dim, #8b9bb4)" }}>
                Two-Stage Hurdle ML · Conformal CQR Bounds · Amihud-Kelly Sizing · ASOF ETL Specs
              </p>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexShrink: 0 }}>
            <kbd
              style={{
                padding: "3px 8px",
                fontSize: "11px",
                fontFamily: "monospace",
                borderRadius: "5px",
                border: "1px solid var(--border-strong, #323c4d)",
                backgroundColor: "var(--surface-2, #202736)",
                color: "var(--dim, #8b9bb4)",
              }}
            >
              ESC
            </kbd>
            <button
              type="button"
              onClick={onClose}
              style={{
                background: "none",
                border: "none",
                color: "var(--dim, #8b9bb4)",
                cursor: "pointer",
                padding: "6px",
                borderRadius: "6px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div
          style={{
            display: "flex",
            gap: "8px",
            padding: "10px 20px",
            borderBottom: "1px solid var(--border, #283140)",
            backgroundColor: "var(--panel, #141822)",
            overflowX: "auto",
          }}
        >
          <TabItem active={activeTab === "architecture"} onClick={() => setActiveTab("architecture")} icon={<Layers size={15} />} label="Architecture" />
          <TabItem active={activeTab === "hurdle"} onClick={() => setActiveTab("hurdle")} icon={<Cpu size={15} />} label="Two-Stage ML" />
          <TabItem active={activeTab === "cqr"} onClick={() => setActiveTab("cqr")} icon={<ShieldCheck size={15} />} label="CQR Shield" />
          <TabItem active={activeTab === "kelly"} onClick={() => setActiveTab("kelly")} icon={<TrendingUp size={15} />} label="Kelly Sizing" />
          <TabItem active={activeTab === "economics"} onClick={() => setActiveTab("economics")} icon={<DollarSign size={15} />} label="Unit Economics" />
          <TabItem active={activeTab === "duckdb"} onClick={() => setActiveTab("duckdb")} icon={<Database size={15} />} label="DuckDB ASOF" />
        </div>

        {/* Body Content */}
        <div style={{ padding: "24px", overflowY: "auto", flex: 1 }}>
          {activeTab === "architecture" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              <div>
                <h3 style={{ fontSize: "15px", fontWeight: 700, margin: "0 0 6px 0", color: "#fff" }}>
                  Core Quantitative Architecture & Pipeline Invariants
                </h3>
                <p style={{ fontSize: "13.5px", lineHeight: 1.6, margin: 0, color: "var(--dim, #94a3b8)" }}>
                  The terminal provides mathematical grounding and real-time execution telemetry for secondary-market Magic: The Gathering singles. The architecture is engineered around 3 core disciplines:
                </p>
              </div>

              {/* 3-Card Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "14px" }}>
                <FeatureCard
                  accent="cyan"
                  icon={<Cpu size={18} />}
                  title="Two-Stage Hurdle ML"
                  description="Decouples price spike probability classification from conditional magnitude estimation with asymmetric loss penalization."
                />
                <FeatureCard
                  accent="green"
                  icon={<ShieldCheck size={18} />}
                  title="CQR Defensive Shield"
                  description="Conformalized Quantile Regression generates 90% finite-sample lower prediction bounds (LPB) to veto value traps."
                />
                <FeatureCard
                  accent="gold"
                  icon={<Scale size={18} />}
                  title="Full Fee Grounding"
                  description="Rigorous rate cards incorporating direct postage, commissions, 2.5% payment processing, condition risk haircut (κ), and dead-zone cliffs."
                />
              </div>
            </div>
          )}

          {activeTab === "hurdle" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px", lineHeight: 1.65, color: "var(--dim, #94a3b8)" }}>
              <h3 style={{ fontSize: "15px", fontWeight: 700, margin: 0, color: "#fff" }}>Two-Stage Hurdle Model</h3>
              <p style={{ margin: 0 }}>
                Directly predicting raw price returns introduces severe zero-inflation noise. We separate forecasting into two distinct stages:
              </p>
              <ul style={{ margin: 0, paddingLeft: "22px", display: "flex", flexDirection: "column", gap: "6px" }}>
                <li><strong style={{ color: "#fff" }}>Stage 1 (Classifier):</strong> Predicts probability τ of a significant price surge (≥ 12% in 7 days).</li>
                <li><strong style={{ color: "#fff" }}>Stage 2 (Regressor):</strong> Custom asymmetric loss function heavily penalizing over-predictions (γ=5.0) to prevent capital destruction on falling knives.</li>
              </ul>
            </div>
          )}

          {activeTab === "cqr" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px", lineHeight: 1.65, color: "var(--dim, #94a3b8)" }}>
              <h3 style={{ fontSize: "15px", fontWeight: 700, margin: 0, color: "#fff" }}>Conformal Quantile Regression (CQR)</h3>
              <p style={{ margin: 0 }}>
                Provides model-agnostic, distribution-free prediction intervals with exact 90% coverage guarantees on calibration holdouts. If the lower prediction bound (LPB) breaches -15%, the terminal automatically triggers a defensive veto.
              </p>
            </div>
          )}

          {activeTab === "kelly" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px", lineHeight: 1.65, color: "var(--dim, #94a3b8)" }}>
              <h3 style={{ fontSize: "15px", fontWeight: 700, margin: 0, color: "#fff" }}>Amihud-Constrained Kelly Sizing</h3>
              <p style={{ margin: 0 }}>
                Position sizing is determined via fractional Kelly criterion scaled down by the 30-day Amihud Illiquidity metric to prevent moving the thin secondary market book upon entry or liquidation.
              </p>
            </div>
          )}

          {activeTab === "economics" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px", lineHeight: 1.65, color: "var(--dim, #94a3b8)" }}>
              <h3 style={{ fontSize: "15px", fontWeight: 700, margin: 0, color: "#fff" }}>Landed Basis & Fee Decomposition</h3>
              <p style={{ margin: 0 }}>
                Every trade simulation accounts for all real-world vendor take-rates: TCGplayer Pro (8.95%) vs Non-Pro (10.75%) tiers, $1.12 per-order base fee, 2.5% payment processing, outbound freight, and condition downgrade salvage factors.
              </p>
            </div>
          )}

          {activeTab === "duckdb" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px", lineHeight: 1.65, color: "var(--dim, #94a3b8)" }}>
              <h3 style={{ fontSize: "15px", fontWeight: 700, margin: 0, color: "#fff" }}>DuckDB In-Memory OLAP & ASOF Temporal Joins</h3>
              <p style={{ margin: 0 }}>
                Market features and arbitrage spreads are calculated using columnar DuckDB window functions and point-in-time <code style={{ backgroundColor: "var(--surface-2, #202736)", padding: "2px 6px", borderRadius: "4px", color: "var(--accent, #4ade80)", fontFamily: "monospace", fontSize: "13px" }}>ASOF JOIN</code> queries, strictly eliminating lookahead bias with a 14-day chronological embargo.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 24px",
            borderTop: "1px solid var(--border-strong, #323c4d)",
            backgroundColor: "var(--panel, #141822)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", color: "var(--up, #4ade80)", fontWeight: 600 }}>
            <span style={{ width: "7px", height: "7px", borderRadius: "50%", backgroundColor: "var(--up, #4ade80)", display: "inline-block" }} />
            <span>CHRONOLOGICAL 14-DAY EMBARGO · ZERO LOOKAHEAD LEAKAGE</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              backgroundColor: "var(--surface-2, #202736)",
              color: "var(--foreground, #fff)",
              border: "1px solid var(--border-strong, #323c4d)",
              borderRadius: "6px",
              padding: "7px 18px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}

function TabItem({
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
      style={{
        display: "flex",
        alignItems: "center",
        gap: "7px",
        padding: "7px 14px",
        borderRadius: "6px",
        fontSize: "13px",
        fontWeight: active ? 600 : 500,
        cursor: "pointer",
        border: active ? "1px solid rgba(74, 222, 128, 0.4)" : "1px solid transparent",
        backgroundColor: active ? "rgba(74, 222, 128, 0.12)" : "transparent",
        color: active ? "var(--accent, #4ade80)" : "var(--dim, #8b9bb4)",
        whiteSpace: "nowrap",
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}

function FeatureCard({
  accent,
  icon,
  title,
  description,
}: {
  accent: "cyan" | "green" | "gold"
  icon: React.ReactNode
  title: string
  description: string
}) {
  const colors = {
    cyan: "var(--accent, #4ade80)",
    green: "var(--up, #4ade80)",
    gold: "var(--warn, #facc15)",
  }

  return (
    <div
      style={{
        borderRadius: "10px",
        border: "1px solid var(--border, #283140)",
        backgroundColor: "var(--surface-2, #1b212d)",
        padding: "16px",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "8px", color: colors[accent], fontWeight: 700, fontSize: "13px" }}>
        {icon}
        <span>{title}</span>
      </div>
      <p style={{ margin: 0, fontSize: "13px", lineHeight: 1.55, color: "var(--dim, #94a3b8)" }}>
        {description}
      </p>
    </div>
  )
}