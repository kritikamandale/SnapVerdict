import { Link } from "react-router-dom";
import Footer from "../components/Footer";

const AUDIENCES = [
  {
    title: "Insurers",
    desc: "Speed upFirst Notice of Loss triage with automated visual evidence review.",
  },
  {
    title: "Warranty Providers",
    desc: "Quickly validate damage claims against warranty terms without manual inspection.",
  },
  {
    title: "E-Commerce & Logistics",
    desc: "Verify package damage claims at scale with structured, auditable assessments.",
  },
  {
    title: "Rental & Leasing",
    desc: "Document and assess vehicle condition disputes with objective AI analysis.",
  },
];

const STEPS = [
  {
    num: 1,
    title: "Upload evidence",
    desc: "Submit photos of the damaged item along with a short claim description.",
  },
  {
    num: 2,
    title: "AI reviews the images",
    desc: "Gemini vision model analyzes each image for visible damage, context, and severity.",
  },
  {
    num: 3,
    title: "Cross-reference history",
    desc: "The system checks the user's claim history for risk flags and patterns.",
  },
  {
    num: 4,
    title: "Get a verdict",
    desc: "Receive a structured decision with issue type, severity, and written justification.",
  },
];

const STATS = [
  { value: "44", label: "Claims Processed", accent: false },
  { value: "4", label: "Evidence Stages", accent: true },
  { value: "< 10s", label: "Per Claim", accent: false },
  { value: "3", label: "Claim Categories", accent: true },
];

const TICKER_ITEMS = [
  "Visual Evidence Review",
  "Damage Detection",
  "Risk Assessment",
  "Claim Verification",
  "Severity Analysis",
  "History Cross-Reference",
  "Structured Verdicts",
  "Automated Triage",
];

export default function LandingPage() {
  return (
    <div className="page-wrapper">
      <div className="page-content">
        {/* Hero */}
        <section className="hero">
          <div className="hero-bg">
            <span className="hero-shape hero-shape--1" />
            <span className="hero-shape hero-shape--2" />
            <span className="hero-shape hero-shape--3" />
            <span className="hero-shape hero-shape--4" />
          </div>
          <div className="container">
            <div className="hero-wordmark">SnapVerdict</div>
            <p className="hero-tagline">
              Automated visual review for damage claims — cars, laptops, and
              packages.
            </p>
            <div className="hero-ctas">
              <Link to="/demo" className="btn btn--accent btn--lg">
                Try the Demo
              </Link>
              <a
                href="https://github.com"
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn--primary btn--lg"
              >
                View on GitHub
              </a>
            </div>
          </div>
        </section>

        {/* Ticker */}
        <div className="ticker-band">
          <div className="ticker-track">
            {[...TICKER_ITEMS, ...TICKER_ITEMS].map((item, i) => (
              <span key={i} className="ticker-item">
                <span className="ticker-dot" />
                {item}
              </span>
            ))}
          </div>
        </div>

        {/* Stats */}
        <section className="section stats-section">
          <div className="container">
            <div className="stats-grid">
              {STATS.map((s) => (
                <div key={s.label} className={`stat-card ${s.accent ? "stat-card--accent" : ""}`}>
                  <div className="stat-value">{s.value}</div>
                  <div className="stat-label">{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Problem */}
        <section className="section">
          <div className="container">
            <h2 className="section-title">Who it's for</h2>
            <p className="section-subtitle">
              Damage claim review is slow, subjective, and hard to scale. These
              teams feel it the most.
            </p>
            <div className="audience-grid">
              {AUDIENCES.map((a) => (
                <div key={a.title} className="card card-hover audience-card">
                  <h3>{a.title}</h3>
                  <p>{a.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="section">
          <div className="container">
            <h2 className="section-title">How it works</h2>
            <p className="section-subtitle">
              A five-stage pipeline that turns photos and a claim description
              into a structured verdict.
            </p>
            <div className="steps-grid">
              {STEPS.map((s) => (
                <div key={s.num} className="card card-hover step-card">
                  <div className="step-number">{s.num}</div>
                  <h3>{s.title}</h3>
                  <p>{s.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Live Demo CTA */}
        <section className="section">
          <div className="container">
            <div className="card card--lg cta-block">
              <h2 className="section-title">Try it yourself</h2>
              <p>
                This calls a real AI pipeline on the backend — upload photos and
                a claim description to get a live verdict.
              </p>
              <Link to="/demo" className="btn btn--accent btn--lg">
                Open the Demo
              </Link>
            </div>
          </div>
        </section>
      </div>

      <Footer />
    </div>
  );
}
