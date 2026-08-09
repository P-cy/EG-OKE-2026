import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Synthwave palette
        neon: {
          pink: "#ff2d95",
          purple: "#b026ff",
          blue: "#00e5ff",
          yellow: "#ffe600",
          green: "#39ff14",
        },
        bg: {
          deep: "#0a0118",
          panel: "#140a2e",
          panel2: "#1d1042",
        },
      },
      fontFamily: {
        display: ['"Press Start 2"', "ui-monospace", "monospace"],
        mono: ['"VT323"', "ui-monospace", "monospace"],
        body: ['"Noto Sans Thai"', "Inter", "system-ui", "sans-serif"],
      },
      boxShadow: {
        neon: "0 0 5px var(--tw-shadow-color), 0 0 20px var(--tw-shadow-color)",
        "neon-lg":
          "0 0 10px var(--tw-shadow-color), 0 0 40px var(--tw-shadow-color)",
      },
      keyframes: {
        flicker: {
          "0%, 19.999%, 22%, 62.999%, 64%, 100%": { opacity: "1" },
          "20%, 21.999%, 63%, 63.999%": { opacity: "0.4" },
        },
        scanline: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        "grid-pan": {
          "0%": { backgroundPosition: "0 0" },
          "100%": { backgroundPosition: "0 40px" },
        },
      },
      animation: {
        flicker: "flicker 3s linear infinite",
        scanline: "scanline 8s linear infinite",
        "grid-pan": "grid-pan 1s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
