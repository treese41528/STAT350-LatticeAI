import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/global.css";
import "katex/dist/katex.min.css"; // self-hosted KaTeX CSS + fonts (no CDN)
import "./styles/katex-overrides.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
