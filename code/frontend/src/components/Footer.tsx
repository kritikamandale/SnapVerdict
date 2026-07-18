import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="container">
        <div className="footer-inner">
          <span className="footer-brand">SnapVerdict</span>

          <div className="footer-links">
            <Link to="/demo">Try Demo</Link>
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub
            </a>
          </div>

          <p className="footer-disclosure">
            This is a demo/concept project built for portfolio purposes.
            SnapVerdict is not a real company. Not affiliated with any
            insurance or claims company. Built for the HackerRank Orchestrate
            hackathon.
          </p>
        </div>
      </div>
    </footer>
  );
}
