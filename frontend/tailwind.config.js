/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0B0F13",
        panel: "#12181F",
        border: "#232B33",
        muted: "#8B98A5",
        accent: "#4FD1C5",
        pass: "#3FB950",
        fail: "#F85149",
        warn: "#D4A72C",
      },
      fontFamily: {
        display: ["Space Grotesk", "sans-serif"],
        sans: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
