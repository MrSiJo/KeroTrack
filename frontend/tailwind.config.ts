import forms from "@tailwindcss/forms";
import type { Config } from "tailwindcss";

// rgb(var(--token) / <alpha>) lets utility classes still take opacity
// modifiers like `bg-bg-page/70`. The CSS variables are defined in
// `src/app.css` and swap under :root.light vs the default dark palette.
const surface = (varName: string) => `rgb(var(${varName}) / <alpha-value>)`;

export default {
  content: ["./src/**/*.{html,svelte,ts,js}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          page: surface("--bg-page"),
          panel: surface("--bg-panel"),
          elev: surface("--bg-elev"),
        },
        border: {
          DEFAULT: surface("--border-default"),
          strong: surface("--border-strong"),
        },
        text: {
          DEFAULT: surface("--text-default"),
          muted: surface("--text-muted"),
          subtle: surface("--text-subtle"),
          label: surface("--text-label"),
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
