import { useState } from "react";
import { api } from "../api";

export default function AuthPage({ onSuccess }) {
  const [mode, setMode] = useState("login");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    const form = new FormData(e.target);
    setError("");
    setBusy(true);
    try {
      if (mode === "login") {
        await api.login(form.get("email"), form.get("password"));
      } else {
        await api.register(form.get("name"), form.get("email"), form.get("password"));
      }
      onSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-art">
        <button className="brand" onClick={() => {}}>
          <span className="dot">🛍️</span> SMART<span className="dot">•</span>SHOP
        </button>
        <div className="hero-copy">
          <p className="eyebrow">FASTAPI · DJANGO · REACT</p>
          <h1>Everything you need.<br /><em>One smart store.</em></h1>
          <p>
            Products, carts, orders, payments and invoices — connected to a real
            role-based backend. Pay by card or cash, and track every order live.
          </p>
          <div className="hero-badges">
            <span>🚚 Free delivery</span>
            <span>💳 Stripe &amp; 💵 cash</span>
            <span>🔔 Live tracking</span>
          </div>
        </div>
        <div className="art-orbit orbit-a" />
        <div className="art-orbit orbit-b" />
      </div>

      <div className="auth-panel">
        <div className="auth-card">
          <div className="brand">SMART<span className="dot">•</span>SHOP</div>

          <div className="auth-tabs">
            <button className={`tab ${mode === "login" ? "active" : ""}`} onClick={() => { setMode("login"); setError(""); }}>
              Sign in
            </button>
            <button className={`tab ${mode === "register" ? "active" : ""}`} onClick={() => { setMode("register"); setError(""); }}>
              Create account
            </button>
          </div>

          {error && <div className="form-error">{error}</div>}

          <form onSubmit={submit} className="auth-form">
            {mode === "login" ? (
              <>
                <h2>Welcome back</h2>
                <p className="muted">Sign in to continue to your account.</p>
              </>
            ) : (
              <>
                <h2>Create account</h2>
                <p className="muted">New accounts are created as <b>customer</b>.</p>
              </>
            )}

            {mode === "register" && (
              <div className="field">
                <label>Name</label>
                <input name="name" required minLength={2} placeholder="Your name" />
              </div>
            )}
            <div className="field">
              <label>Email</label>
              <input name="email" type="email" required placeholder="you@example.com" />
            </div>
            <div className="field">
              <label>Password</label>
              <input
                name="password" type="password" required minLength={8}
                placeholder={mode === "register" ? "At least 8 characters" : "••••••••"}
              />
            </div>
            <button className="btn btn-primary btn-block" disabled={busy}>
              {busy ? "Please wait…" : mode === "login" ? "Sign in →" : "Create account →"}
            </button>
          </form>

          {mode === "login" && (
            <>
              <div className="divider"><span>or continue with</span></div>
              <div className="oauth-row">
                <a className="btn btn-outline" href={api.socialLoginUrl("google")}>
                  <span className="g-mark">G</span> Google
                </a>
                <a className="btn btn-outline" href={api.socialLoginUrl("facebook")}>
                  <span className="f-mark">f</span> Facebook
                </a>
              </div>
            </>
          )}

          <div className="auth-switch">
            {mode === "login" ? (
              <>New here? <button onClick={() => { setMode("register"); setError(""); }}>Create an account</button></>
            ) : (
              <>Already have an account? <button onClick={() => { setMode("login"); setError(""); }}>Sign in</button></>
            )}
          </div>
          <p className="demo-note">New accounts start as customers — ask an admin to promote yours.</p>
        </div>
      </div>
    </div>
  );
}
