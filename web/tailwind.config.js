/** Tokens live in src/styles/index.css as CSS variables (light "survey paper" and dark "monsoon night"). */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        paper: "rgb(var(--paper) / <alpha-value>)",
        "paper-2": "rgb(var(--paper-2) / <alpha-value>)",
        "paper-3": "rgb(var(--paper-3) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        "ink-2": "rgb(var(--ink-2) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        memory: "rgb(var(--memory) / <alpha-value>)",
        "memory-soft": "rgb(var(--memory-soft) / <alpha-value>)",
        lost: "rgb(var(--lost) / <alpha-value>)",
        built: "rgb(var(--built) / <alpha-value>)",
        live: "rgb(var(--live) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-body)"],
        display: ["var(--font-body)"],
      },
      maxWidth: { prose: "68ch" },
      borderRadius: { plate: "3px" },
    },
  },
  plugins: [],
};
