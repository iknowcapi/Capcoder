/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  theme: {
    extend: {
      fontFamily: {
        bbs: ["'VT323'", "monospace"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        phosphor: "#39FF14",
        phosphor2: "#1F8A0E",
        phosphor3: "#124B08",
        neon_magenta: "#FF00FF",
        neon_cyan: "#00FFFF",
        neon_yellow: "#FFEA00",
        amber_warn: "#FFB000",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        blink: { "50%": { opacity: "0" } },
        flicker: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.92" } },
        scanline: { "0%": { transform: "translateY(-100%)" }, "100%": { transform: "translateY(100vh)" } },
        glitch: {
          "0%,100%": { textShadow: "2px 0 #FF00FF, -2px 0 #00FFFF" },
          "50%": { textShadow: "-2px 0 #FF00FF, 2px 0 #00FFFF" },
        },
      },
      animation: {
        blink: "blink 1s steps(2) infinite",
        flicker: "flicker 3s infinite",
        scanline: "scanline 8s linear infinite",
        glitch: "glitch 1.4s infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
