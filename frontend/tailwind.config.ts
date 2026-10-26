import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0f172a",
        panel: "#111827",
        // Modern enterprise surfaces — neutral zinc scale + an indigo/violet
        // brand accent, used across the shared shell and every page.
        surface: {
          0: "#08080a",
          1: "#0e0e12",
          2: "#131318",
          3: "#1a1a21",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(0,0,0,0.3), 0 1px 3px 0 rgba(0,0,0,0.2)",
        elevated: "0 4px 24px -4px rgba(0,0,0,0.5), 0 1px 2px rgba(0,0,0,0.4)",
      },
      borderRadius: {
        xl2: "1rem",
      },
    },
  },
  plugins: [],
};

export default config;
