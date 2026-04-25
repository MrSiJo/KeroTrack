import forms from "@tailwindcss/forms";
import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{html,svelte,ts,js}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          page: "#0a0f1c",
          panel: "#0f172a",
          elev: "#1a2438",
        },
        border: {
          DEFAULT: "#1e293b",
          strong: "#334155",
        },
        text: {
          DEFAULT: "#e2e8f0",
          muted: "#94a3b8",
          subtle: "#64748b",
          label: "#475569",
        },
        brand: {
          blue: "#3b82f6",
          "blue-2": "#60a5fa",
          "blue-3": "#93c5fd",
          teal: "#2dd4bf",
          amber: "#f59e0b",
          red: "#ef4444",
          emerald: "#10b981",
          violet: "#a78bfa",
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontVariantNumeric: {
        tabular: 'tabular-nums',
      },
    },
  },
  plugins: [forms],
} satisfies Config;
