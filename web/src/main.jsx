import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";
import { startAutoplay } from "./autoplay.js";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

startAutoplay(); // only active with ?autoplay in the URL (video recording helper)
