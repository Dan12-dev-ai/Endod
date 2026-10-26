import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Endod Health OS",
    short_name: "Endod Health",
    description:
      "Understand your symptoms, reach the right hospital faster, and arrive with a clear record. You stay in control of your health data.",
    start_url: "/login",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#000000",
    theme_color: "#000000",
    lang: "en",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    categories: ["health", "medical"],
    shortcuts: [
      {
        name: "Start consultation",
        short_name: "Consult",
        description: "Open your symptom consultation",
        url: "/interview",
        icons: [{ src: "/icon-192.png", sizes: "192x192" }],
      },
      {
        name: "My health card",
        short_name: "Card",
        description: "View your health card",
        url: "/health-card",
        icons: [{ src: "/icon-192.png", sizes: "192x192" }],
      },
    ],
  };
}
