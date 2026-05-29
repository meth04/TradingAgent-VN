import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-primary": "#F5F0E8",
        "bg-card": "#FFFDF7",
        "bg-header": "#2C2C2C",
        "text-primary": "#1A1A1A",
        "text-secondary": "#6B6B6B",
        "text-header": "#F5F0E8",
        "accent-green": "#2D8B4E",
        "accent-red": "#C0392B",
        "accent-gold": "#D4A843",
        border: "#2C2C2C",
        "border-light": "#D5CFC3",
      },
    },
  },
  plugins: [],
};

export default config;
