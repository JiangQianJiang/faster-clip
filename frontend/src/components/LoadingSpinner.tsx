import type React from "react";

const spinnerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
  padding: 40,
};

const LoadingSpinner: React.FC = () => (
  <div style={spinnerStyle} role="status" aria-label="Loading">
    Loading...
  </div>
);

export default LoadingSpinner;
