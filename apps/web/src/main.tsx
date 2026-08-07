import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import {
  createHttpEvidenceApiClient,
  createMockEvidenceApiClient,
} from "@quartet-coach/web-client";
import { App } from "./App";
import "./styles.css";

const isMockMode = import.meta.env.VITE_API_MODE === "mock";
const client = isMockMode
  ? createMockEvidenceApiClient()
  : createHttpEvidenceApiClient({
      baseUrl: import.meta.env.VITE_API_BASE_URL || "/api",
    });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App client={client} mockMode={isMockMode} />
  </StrictMode>,
);
