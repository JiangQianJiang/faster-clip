import { useState, useEffect, useCallback, type FormEvent } from "react";
import { getAccessToken, setAccessToken, clearAccessToken, verifyToken } from "../auth";
import { THEME } from "../theme";

interface AuthGateProps {
  children: React.ReactNode;
}

export default function AuthGate({ children }: AuthGateProps) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);

  // Check if already authenticated on mount
  useEffect(() => {
    const existing = getAccessToken();
    if (existing) {
      verifyToken(existing).then((valid) => {
        if (valid) {
          setAuthenticated(true);
        } else {
          clearAccessToken();
        }
        setChecking(false);
      });
    } else {
      setChecking(false);
    }
  }, []);

  // Listen for 401 events from authFetch
  useEffect(() => {
    const handler = () => {
      setAuthenticated(false);
      clearAccessToken();
    };
    window.addEventListener("auth:unauthorized", handler);
    return () => window.removeEventListener("auth:unauthorized", handler);
  }, []);

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      setError("");

      if (!token.trim()) {
        setError("请输入访问令牌");
        return;
      }

      setLoading(true);
      try {
        const valid = await verifyToken(token.trim());
        if (valid) {
          setAccessToken(token.trim());
          setAuthenticated(true);
          setToken("");
        } else {
          setError("令牌无效，请重试");
        }
      } catch {
        setError("验证失败，请检查网络连接");
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  const handleExit = useCallback(() => {
    clearAccessToken();
    setAuthenticated(false);
    setToken("");
    setError("");
  }, []);

  if (checking) {
    return (
      <div style={styles.container}>
        <p style={{ color: THEME.colors.textSecondary }}>验证访问状态...</p>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div style={styles.container}>
        <div style={styles.card}>
          <h1 style={styles.title}>直播切片助手</h1>
          <p style={styles.subtitle}>请输入访问令牌以继续</p>

          <form onSubmit={handleSubmit} style={styles.form}>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="访问令牌"
              style={styles.input}
              autoFocus
              disabled={loading}
            />
            {error && <p style={styles.error}>{error}</p>}
            <button type="submit" style={styles.button} disabled={loading}>
              {loading ? "验证中..." : "验证并进入"}
            </button>
          </form>

          <p style={styles.hint}>
            令牌由管理员提供。关闭浏览器标签页后需重新输入。
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Exit button in corner when authenticated */}
      <button
        onClick={handleExit}
        style={styles.exitButton}
        title="退出共享访问（不会清除 API Key）"
      >
        退出共享访问
      </button>
      {children}
    </>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: "100vh",
    backgroundColor: THEME.colors.bgPage,
    fontFamily: "system-ui, sans-serif",
  },
  card: {
    width: "100%",
    maxWidth: 400,
    padding: "32px 24px",
    textAlign: "center",
  },
  title: {
    fontSize: 24,
    fontWeight: 700,
    color: THEME.colors.textPrimary,
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    color: THEME.colors.textSecondary,
    marginBottom: 24,
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  input: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 14,
    border: `1px solid ${THEME.colors.border}`,
    borderRadius: THEME.radius.md,
    outline: "none",
    boxSizing: "border-box" as const,
  },
  button: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 14,
    fontWeight: 600,
    color: "#fff",
    backgroundColor: THEME.colors.primary,
    border: "none",
    borderRadius: THEME.radius.md,
    cursor: "pointer",
  },
  error: {
    fontSize: 13,
    color: THEME.colors.errorText,
    margin: 0,
  },
  hint: {
    fontSize: 12,
    color: THEME.colors.textSecondary,
    marginTop: 16,
    lineHeight: 1.5,
  },
  exitButton: {
    position: "fixed",
    top: 8,
    right: 12,
    zIndex: 9999,
    padding: "4px 10px",
    fontSize: 12,
    color: THEME.colors.textSecondary,
    backgroundColor: "transparent",
    border: `1px solid ${THEME.colors.border}`,
    borderRadius: THEME.radius.sm,
    cursor: "pointer",
  },
};
