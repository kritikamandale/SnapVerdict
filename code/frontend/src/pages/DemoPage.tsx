import { useState, useRef } from "react";
import Footer from "../components/Footer";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const COLD_START_DELAY_MS = 4000;

interface ClaimResult {
  error?: boolean;
  error_type?: string;
  error_message?: string;
  evidence_standard_met?: string;
  evidence_standard_met_reason?: string;
  risk_flags?: string;
  issue_type?: string;
  object_part?: string;
  claim_status?: string;
  claim_status_justification?: string;
  supporting_image_ids?: string;
  valid_image?: string;
  severity?: string;
  model?: string;
}

export default function DemoPage() {
  const [images, setImages] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [userClaim, setUserClaim] = useState("");
  const [claimObject, setClaimObject] = useState("car");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ClaimResult | null>(null);
  const [waking, setWaking] = useState(false);
  const wakeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setImages(files);
    setPreviews(files.map((f) => URL.createObjectURL(f)));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setWaking(false);

    const fd = new FormData();
    images.forEach((img) => fd.append("images", img));
    fd.append("user_claim", userClaim);
    fd.append("claim_object", claimObject);

    wakeTimer.current = setTimeout(() => {
      setWaking(true);
    }, COLD_START_DELAY_MS);

    try {
      const res = await fetch(`${API_BASE}/claims`, {
        method: "POST",
        body: fd,
      });
      const data: ClaimResult = await res.json();
      console.log("[SnapVerdict] Raw API response:", JSON.stringify(data, null, 2));
      setResult(data);
    } catch {
      setResult({
        error: true,
        error_type: "network",
        error_message: "Could not reach the API server. Is the backend running?",
      });
    } finally {
      if (wakeTimer.current) {
        clearTimeout(wakeTimer.current);
        wakeTimer.current = null;
      }
      setLoading(false);
      setWaking(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setImages([]);
    setPreviews([]);
    setUserClaim("");
    setClaimObject("car");
    setWaking(false);
    if (wakeTimer.current) {
      clearTimeout(wakeTimer.current);
      wakeTimer.current = null;
    }
  };

  return (
    <div className="page-wrapper">
      <div className="page-content">
        <div className="demo-header">
          <div className="container">
            <h1>Claim Verification Demo</h1>
            <p>
              Upload evidence images and describe the damage to get an AI-powered
              verdict.
            </p>
          </div>
        </div>

        <section className="section" style={{ paddingTop: 0 }}>
          <div className="container container--narrow">
            {waking && (
              <div className="card cold-start-banner">
                <h3>Waking up the backend</h3>
                <p>
                  First request after inactivity can take up to a minute.
                  Thanks for your patience.
                </p>
              </div>
            )}

            <form className="card card--lg" onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label" htmlFor="claim-object">
                  Claim Object
                </label>
                <select
                  id="claim-object"
                  className="form-select"
                  value={claimObject}
                  onChange={(e) => setClaimObject(e.target.value)}
                >
                  <option value="car">Car</option>
                  <option value="laptop">Laptop</option>
                  <option value="package">Package</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="user-claim">
                  Describe the Damage
                </label>
                <textarea
                  id="user-claim"
                  className="form-textarea"
                  rows={4}
                  placeholder="e.g. Scratch on the front bumper from a parking lot incident"
                  value={userClaim}
                  onChange={(e) => setUserClaim(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label">Evidence Images</label>
                <label className="upload-zone">
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    onChange={handleImageChange}
                  />
                  {images.length === 0
                    ? "Click to select images, or drag and drop"
                    : `${images.length} image${images.length > 1 ? "s" : ""} selected`}
                </label>
                {previews.length > 0 && (
                  <div className="preview-row">
                    {previews.map((src, i) => (
                      <img
                        key={i}
                        src={src}
                        alt={`Preview ${i + 1}`}
                        className="preview-thumb"
                      />
                    ))}
                  </div>
                )}
              </div>

              <div style={{ display: "flex", gap: "0.75rem" }}>
                <button
                  type="submit"
                  className="btn btn--accent btn--full"
                  disabled={loading || images.length === 0 || !userClaim.trim()}
                >
                  {loading ? (
                    <span className="spinner-wrap">
                      <span className="spinner" />
                      Analyzing…
                    </span>
                  ) : (
                    "Verify Claim"
                  )}
                </button>
                {result && (
                  <button
                    type="button"
                    className="btn btn--outline"
                    onClick={handleReset}
                  >
                    Reset
                  </button>
                )}
              </div>
            </form>

            {result && <ResultCard result={result} previews={previews} />}
          </div>
        </section>
      </div>

      <Footer />
    </div>
  );
}

/* ── Result display ─────────────────────────────────────────────────── */

function ResultCard({
  result,
  previews,
}: {
  result: ClaimResult;
  previews: string[];
}) {
  /* ── Error path (explicit error flag from API) ── */
  if (result.error) {
    if (result.error_type === "quota_exhausted") {
      return (
        <div className="card card--lg error-banner error-banner--quota">
          <h3>Daily API Capacity Reached</h3>
          <p>
            The demo uses Google Gemini's free tier, which resets daily. Please
            try again later.
          </p>
        </div>
      );
    }
    if (result.error_type === "network") {
      return (
        <div className="card card--lg error-banner error-banner--error">
          <h3>Connection Error</h3>
          <p>{result.error_message}</p>
        </div>
      );
    }
    return (
      <div className="card card--lg error-banner error-banner--error">
        <h3>Something went wrong</h3>
        <p>{result.error_message || "An unexpected error occurred."}</p>
      </div>
    );
  }

  /* ── "No usable data" path ── */
  const hasClaimStatus =
    result.claim_status &&
    result.claim_status !== "unknown" &&
    result.claim_status !== "";

  const hasAnyData =
    result.issue_type ||
    result.object_part ||
    result.severity ||
    result.claim_status_justification;

  if (!hasClaimStatus || !hasAnyData) {
    return (
      <div className="card card--lg no-result-card">
        <h3>No Result</h3>
        <p>
          {result.error_message ||
            "The analysis returned no usable data. This may be due to API quota limits or an issue with the submitted images."}
        </p>
      </div>
    );
  }

  /* ── Success path ── */
  const statusClass =
    result.claim_status === "supported"
      ? "badge--success"
      : result.claim_status === "contradicted"
        ? "badge--danger"
        : "badge--warning";

  const flags = (result.risk_flags || "none")
    .split(";")
    .map((f) => f.trim())
    .filter((f) => f && f !== "none");

  return (
    <div className="card card--lg">
      <div className="result-header">
        <span className={`badge ${statusClass}`}>
          {result.claim_status!.replace(/_/g, " ")}
        </span>
        {result.model && <span className="model-tag">{result.model}</span>}
      </div>

      <div className="result-grid">
        <Field label="Issue Type" value={result.issue_type?.replace(/_/g, " ")} />
        <Field
          label="Object Part"
          value={result.object_part?.replace(/_/g, " ")}
        />
        <Field label="Severity" value={result.severity} />
        <Field
          label="Valid Image"
          value={result.valid_image === "true" ? "Yes" : "No"}
        />
      </div>

      {result.claim_status_justification && (
        <div className="justification">
          <h4>Justification</h4>
          <p>{result.claim_status_justification}</p>
        </div>
      )}

      {flags.length > 0 && (
        <div className="flags-section">
          <h4>Risk Flags</h4>
          <div className="flag-pills">
            {flags.map((f) => (
              <span key={f} className="chip">
                {f.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>
      )}

      {previews.length > 0 && (
        <div className="evaluated-images">
          <h4>Evidence Images</h4>
          <div className="preview-row">
            {previews.map((src, i) => (
              <img
                key={i}
                src={src}
                alt={`Evidence ${i + 1}`}
                className="preview-thumb"
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string }) {
  return (
    <div className="field-display">
      <span className="field-label">{label}</span>
      <span className="field-value">{value || "—"}</span>
    </div>
  );
}
