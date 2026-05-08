import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces — warm, paper-like
        bg: {
          DEFAULT: "#fbfaf6",
          elevated: "#ffffff",
          subtle: "#f3f1ea",
          inverse: "#0f1614",
        },
        // Text
        ink: {
          DEFAULT: "#101512",
          muted: "#5b5751",
          dim: "#8a857d",
        },
        // Borders & rules
        rule: {
          DEFAULT: "#e7e2d6",
          strong: "#cfc8b6",
        },
        // Accent — deep clinical teal/evergreen
        accent: {
          DEFAULT: "#0f5d54",
          strong: "#0a4640",
          soft: "#e6f1ee",
        },
        // Verdict — desaturated traffic-light, editorial
        verdict: {
          supported: "#1a6b3a",
          contradicted: "#a3271f",
          notfound: "#9a6708",
          partial: "#3a4ba6",
          unknown: "#6b6660",
        },
        // Entity classes — muted, distinct
        entity: {
          drug: "#3a4ba6",
          disease: "#a3271f",
          symptom: "#0f5d54",
          phenotype: "#0f5d54",
          effect: "#7a4a8c",
          medical: "#6b6660",
        },
      },
      fontFamily: {
        sans: ['"Inter"', "system-ui", "sans-serif"],
        serif: ['"Source Serif 4"', '"Source Serif Pro"', "Georgia", "serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      letterSpacing: {
        tightish: "-0.015em",
        tighter2: "-0.025em",
      },
      boxShadow: {
        card: "0 1px 0 rgba(16,21,18,0.04), 0 1px 2px rgba(16,21,18,0.04)",
        focus: "0 0 0 3px rgba(15,93,84,0.18)",
      },
    },
  },
  plugins: [],
};

export default config;
