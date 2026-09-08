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
    <div className="auth-wrap">
      <div className="panel auth-card">
        <h2>{mode === "login" ? "Welcome back" : "Create your account"}</h2>
        <p className="sub">
          {mode === "login"
            ? "Sign in to shop, track orders, and get live updates."
            : "Join SmartCart in a few seconds."}
        </p>

        {error && <div className="form-error">{error}</div>}

        <form onSubmit={submit}>
          {mode === "register" && (
            <div className="field">
              <label>Full name</label>
              <input name="name" required placeholder="Jane Doe" />
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
            {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <div className="divider"><span>or continue with</span></div>
        <div className="social-btns">
          <a className="btn btn-ghost btn-block" href={api.socialLoginUrl("google")}>
            <span className="g-mark">G</span> Google
          </a>
          <a className="btn btn-ghost btn-block" href={api.socialLoginUrl("facebook")}>
            <span className="f-mark">f</span> Facebook
          </a>
        </div>

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
  );
}
